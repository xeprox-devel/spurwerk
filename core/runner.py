"""Job-Ausführung: FilePlans → fertige MKVs.

Läuft in einem Worker-Thread (oder synchron in Tests) und meldet Fortschritt
über eine Queue an die UI. Kein tkinter-Import. Ein Fehler bricht nur die
betroffene Datei ab, nie den Batch.

Queue-Protokoll (Tupel):
  ("LOG", text, tag)              tag: None|"info"|"error"|"success"|"step"|"dim"
  ("STATUS", text)
  ("PROGRESS_FILE", pct)          0..100 für die aktuelle Datei
  ("PROGRESS_TOTAL", pct)
  ("FILE_STATUS", path, FileStatus, fehlertext)
  ("BATCH_DONE", erfolge, gesamt, abgebrochen)
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .commands import build_ffmpeg_downmix, build_mkvmerge_mux, stereo_temp_name
from .model import FilePlan, FileStatus, StereoSettings

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_GUI_PROGRESS_RE = re.compile(r"#GUI#progress (\d+)%")


class JobError(Exception):
    pass


class JobRunner:
    def __init__(self, tools: dict[str, str], ui_queue: queue.Queue,
                 cancel: threading.Event | None = None):
        self.tools = tools
        self.q = ui_queue
        self.cancel = cancel or threading.Event()
        self._active_proc: subprocess.Popen | None = None

    # ── öffentliche API ───────────────────────────────────────────────────

    def run(self, plans: list[FilePlan], settings: StereoSettings) -> int:
        """Arbeitet alle Pläne ab; Rückgabe = Anzahl erfolgreicher Dateien."""
        total = len(plans)
        success = 0
        for idx, plan in enumerate(plans):
            if self.cancel.is_set():
                plan.status = FileStatus.SKIPPED
                self._file_status(plan)
                continue
            self.q.put(("PROGRESS_TOTAL", int(idx / total * 100)))
            self.q.put(("LOG", "─" * 62, "dim"))
            self.q.put(("LOG",
                        f"Datei {idx + 1}/{total}: {Path(plan.media.path).name}",
                        "step"))
            self.q.put(("STATUS",
                        f"[{idx + 1}/{total}] {Path(plan.media.path).name}"))
            if self._run_single(plan, settings):
                success += 1
        self.q.put(("PROGRESS_FILE", 100))
        self.q.put(("PROGRESS_TOTAL", 100))
        self.q.put(("BATCH_DONE", success, total, self.cancel.is_set()))
        return success

    def terminate_active(self) -> None:
        """Bricht den gerade laufenden Unterprozess ab (Cancel-Pfad der UI)."""
        proc = self._active_proc
        if proc and proc.poll() is None:
            proc.terminate()

    # ── eine Datei ────────────────────────────────────────────────────────

    def _run_single(self, plan: FilePlan, settings: StereoSettings) -> bool:
        plan.status = FileStatus.RUNNING
        plan.error = ""
        self._file_status(plan)
        self.q.put(("PROGRESS_FILE", 0))

        temp_dir: str | None = None
        output_created = False   # nur selbst Erzeugtes darf aufgeräumt werden
        try:
            self._validate(plan)
            stereo_tracks = plan.stereo_sources()
            steps = len(stereo_tracks) + 1
            stereo_files: dict[int, str] = {}

            if stereo_tracks:
                temp_dir = tempfile.mkdtemp(prefix="spurwerk-")
                for i, track in enumerate(stereo_tracks):
                    self._check_cancel()
                    out = str(Path(temp_dir) / stereo_temp_name(track, settings))
                    self.q.put(("LOG",
                                f"  [{i + 1}/{steps}] Downmix Spur {track.id} "
                                f"({track.lang}, {track.channels}ch) → "
                                f"{settings.codec.upper()} {settings.bitrate} "
                                f"Stereo …", "step"))
                    cmd = build_ffmpeg_downmix(
                        self.tools["ffmpeg"], plan, track, settings, out)
                    self._run_ffmpeg(cmd, plan.media.duration_s,
                                     slice_start=i * 100 // steps,
                                     slice_end=(i + 1) * 100 // steps)
                    stereo_files[track.id] = out

            self._check_cancel()
            self.q.put(("LOG", f"  [{steps}/{steps}] Muxe → "
                               f"{Path(plan.output_path).name} …", "step"))
            Path(plan.output_path).parent.mkdir(parents=True, exist_ok=True)
            mux_cmd = build_mkvmerge_mux(
                self.tools["mkvmerge"], plan, settings, stereo_files)
            output_created = True
            self._run_mkvmerge(mux_cmd,
                               slice_start=(steps - 1) * 100 // steps,
                               slice_end=100)

            plan.status = FileStatus.DONE
            self._file_status(plan)
            self.q.put(("LOG", f"  Fertig: {plan.output_path}", "success"))
            return True

        except _Cancelled:
            plan.status = FileStatus.SKIPPED
            plan.error = "abgebrochen"
            self._file_status(plan)
            if output_created:
                self._remove_partial(plan)
            return False
        except (JobError, OSError, subprocess.SubprocessError) as exc:
            plan.status = FileStatus.ERROR
            plan.error = str(exc)
            self._file_status(plan)
            self.q.put(("LOG", f"  FEHLER: {exc}", "error"))
            if output_created:
                self._remove_partial(plan)
            return False
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _validate(self, plan: FilePlan) -> None:
        if not plan.has_output():
            raise JobError("Keine Spur für die Ausgabe ausgewählt.")
        src = Path(plan.media.path)
        dst = Path(plan.output_path)
        if not src.exists():
            raise JobError(f"Quelldatei nicht gefunden: {src}")
        try:
            same = dst.exists() and src.samefile(dst)
        except OSError:
            same = str(src).lower() == str(dst).lower()
        if same or str(src).lower() == str(dst).lower():
            raise JobError("Ausgabedatei wäre identisch mit der Quelldatei.")

    # ── Prozess-Ausführung mit Fortschritt ────────────────────────────────

    def _run_ffmpeg(self, cmd: list[str], duration_s: float,
                    slice_start: int, slice_end: int) -> None:
        stderr_tail = self._stream_process(
            cmd,
            progress_cb=lambda line: self._ffmpeg_progress(
                line, duration_s, slice_start, slice_end))
        proc = self._active_proc
        if proc and proc.returncode != 0 and not self.cancel.is_set():
            raise JobError(
                f"FFmpeg-Fehler (Exit {proc.returncode}): {stderr_tail[-600:]}")

    def _ffmpeg_progress(self, line: str, duration_s: float,
                         start: int, end: int) -> None:
        if not line.startswith("out_time_ms=") or duration_s <= 0:
            return
        value = line.split("=", 1)[1].strip()
        if value in ("N/A", ""):
            return
        try:
            elapsed_us = int(value)   # trotz Namens: Mikrosekunden
        except ValueError:
            return
        frac = min(1.0, elapsed_us / (duration_s * 1_000_000))
        self.q.put(("PROGRESS_FILE", start + int(frac * (end - start))))

    def _run_mkvmerge(self, cmd: list[str],
                      slice_start: int, slice_end: int) -> None:
        def on_line(line: str) -> None:
            m = _GUI_PROGRESS_RE.search(line)
            if m:
                frac = int(m.group(1)) / 100
                self.q.put(("PROGRESS_FILE",
                            slice_start + int(frac * (slice_end - slice_start))))

        stderr_tail = self._stream_process(cmd, progress_cb=on_line)
        proc = self._active_proc
        if proc is None or self.cancel.is_set():
            return
        if proc.returncode == 1:
            self.q.put(("LOG",
                        f"  mkvmerge-Warnung: {stderr_tail[-300:].strip()}",
                        "info"))
        elif proc.returncode >= 2:
            raise JobError(
                f"mkvmerge-Fehler (Exit {proc.returncode}): "
                f"{stderr_tail[-600:]}")

    def _stream_process(self, cmd: list[str], progress_cb) -> str:
        """Startet den Prozess, streamt stdout an progress_cb, sammelt stderr."""
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            creationflags=_CREATE_NO_WINDOW)
        self._active_proc = proc
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if self.cancel.is_set():
                    proc.terminate()
                    break
                progress_cb(line.strip())
            stderr = proc.stderr.read() if proc.stderr else ""
            proc.wait()
            return stderr
        finally:
            self._active_proc = None

    # ── Kleinkram ─────────────────────────────────────────────────────────

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise _Cancelled()

    def _file_status(self, plan: FilePlan) -> None:
        self.q.put(("FILE_STATUS", plan.media.path, plan.status, plan.error))

    def _remove_partial(self, plan: FilePlan) -> None:
        try:
            out = Path(plan.output_path)
            src = Path(plan.media.path)
            # Doppelter Boden: niemals die Quelldatei anfassen
            if out.exists() and not (src.exists() and out.samefile(src)):
                out.unlink()
                self.q.put(("LOG",
                            "  Unvollständige Ausgabedatei gelöscht.", "info"))
        except OSError:
            pass


class _Cancelled(Exception):
    pass
