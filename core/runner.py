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
        """Arbeitet alle Pläne ab; Rückgabe = Anzahl erfolgreicher Dateien.

        BATCH_DONE ist per try/finally garantiert — die UI darf niemals auf
        eine Abschlussnachricht warten, die nie kommt.
        """
        total = len(plans)
        success = 0
        try:
            self._mark_output_collisions(plans)
            for idx, plan in enumerate(plans):
                if plan.status is FileStatus.ERROR:   # Kollision vorab erkannt
                    self._file_status(plan)
                    continue
                if self.cancel.is_set():
                    plan.status = FileStatus.SKIPPED
                    self._file_status(plan)
                    continue
                self.q.put(("PROGRESS_TOTAL", int(idx / total * 100)))
                self.q.put(("LOG", "─" * 62, "dim"))
                self.q.put((
                    "LOG",
                    f"Datei {idx + 1}/{total}: {Path(plan.media.path).name}",
                    "step"))
                self.q.put((
                    "STATUS",
                    f"[{idx + 1}/{total}] {Path(plan.media.path).name}"))
                if self._run_single(plan, settings):
                    success += 1
        finally:
            self.q.put(("PROGRESS_FILE", 100))
            self.q.put(("PROGRESS_TOTAL", 100))
            self.q.put(("BATCH_DONE", success, total, self.cancel.is_set()))
        return success

    def _mark_output_collisions(self, plans: list[FilePlan]) -> None:
        """Zwei Quelldateien mit demselben Ausgabepfad: nur die erste läuft."""
        seen: dict[str, str] = {}
        for plan in plans:
            key = os.path.normcase(os.path.abspath(plan.output_path))
            if key in seen:
                plan.status = FileStatus.ERROR
                plan.error = (f"Ausgabepfad kollidiert mit "
                              f"{Path(seen[key]).name} — bitte Ausgabename "
                              f"oder -ordner ändern.")
                self.q.put(("LOG",
                            f"Übersprungen: {Path(plan.media.path).name} — "
                            f"{plan.error}", "error"))
            else:
                seen[key] = plan.media.path

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
        # Aufräum-Regel: nur löschen, was DIESER Lauf nachweislich angefasst
        # hat — nie das intakte Ergebnis eines früheren Laufs wegwerfen.
        before_sig = self._output_signature(plan)
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
            self._run_mkvmerge(mux_cmd,
                               slice_start=(steps - 1) * 100 // steps,
                               slice_end=100)
            # Abbruch mitten im Mux hinterlässt eine abgeschnittene Datei —
            # das darf niemals als DONE enden.
            self._check_cancel()

            plan.status = FileStatus.DONE
            self._file_status(plan)
            self.q.put(("LOG", f"  Fertig: {plan.output_path}", "success"))
            return True

        except _Cancelled:
            plan.status = FileStatus.SKIPPED
            plan.error = "abgebrochen"
            self._file_status(plan)
            if self._output_signature(plan) != before_sig:
                self._remove_partial(plan)
            return False
        except Exception as exc:  # letzte Verteidigung: Batch nie sterben lassen
            plan.status = FileStatus.ERROR
            plan.error = str(exc)
            self._file_status(plan)
            self.q.put(("LOG", f"  FEHLER: {exc}", "error"))
            if self._output_signature(plan) != before_sig:
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
        returncode, stderr = self._stream_process(
            cmd,
            progress_cb=lambda line: self._ffmpeg_progress(
                line, duration_s, slice_start, slice_end))
        if self.cancel.is_set():
            return
        if returncode != 0:
            raise JobError(
                f"FFmpeg-Fehler (Exit {returncode}): {stderr[-600:].strip()}")

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

        returncode, stderr = self._stream_process(cmd, progress_cb=on_line)
        if self.cancel.is_set():
            return
        if returncode == 1:
            self.q.put(("LOG",
                        f"  mkvmerge-Warnung: {stderr[-300:].strip()}",
                        "info"))
        elif returncode != 0:   # >=2 = Fehler, negativ = per Signal beendet
            raise JobError(
                f"mkvmerge-Fehler (Exit {returncode}): "
                f"{stderr[-600:].strip()}")

    def _stream_process(self, cmd: list[str], progress_cb) -> tuple[int, str]:
        """Startet den Prozess, streamt stdout an progress_cb und liefert
        (Returncode, stderr). stderr wird parallel in einem eigenen Thread
        geleert — sonst blockiert das Kind, sobald es mehr als den
        Pipe-Puffer (~64 KB) an Fehlermeldungen schreibt."""
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            creationflags=_CREATE_NO_WINDOW)
        self._active_proc = proc

        stderr_chunks: list[str] = []
        drain = threading.Thread(
            target=lambda: stderr_chunks.append(
                proc.stderr.read() if proc.stderr else ""),
            daemon=True)
        drain.start()

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if self.cancel.is_set():
                    proc.terminate()
                    break
                progress_cb(line.strip())
            proc.wait()
            drain.join(timeout=10)
            return proc.returncode, "".join(stderr_chunks)
        finally:
            self._active_proc = None

    # ── Kleinkram ─────────────────────────────────────────────────────────

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise _Cancelled()

    def _file_status(self, plan: FilePlan) -> None:
        self.q.put(("FILE_STATUS", plan.media.path, plan.status, plan.error))

    @staticmethod
    def _output_signature(plan: FilePlan) -> tuple[int, int] | None:
        """Fingerabdruck der Ausgabedatei (None = existiert nicht)."""
        try:
            st = Path(plan.output_path).stat()
            return (st.st_size, st.st_mtime_ns)
        except OSError:
            return None

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
