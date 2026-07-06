"""Die Spurtabelle — das Herzstück von Spurwerk.

Eigenes Treeview-Widget mit Checkbox-Grafiken in Spalte #0 (Pillow,
theme-genau) und einem Aktions-Menü an der Zelle. Jede Zeile beantwortet:
Was ist diese Spur, kommt sie mit, und was passiert mit ihr?
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import ttkbootstrap as ttk
from ttkbootstrap import utility

from core.dv import VIDEO_MODE_COPY, VIDEO_MODE_HDR10
from core.langs import display_name
from core.model import Action, FilePlan, Origin, StereoSettings, Track

from . import theme

TYPE_LABELS = {"video": "Video", "audio": "Audio", "subtitles": "Untertitel"}

_CHANNEL_NAMES = {1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}


def _fmt_channels(track: Track) -> str:
    if track.type != "audio" or not track.channels:
        return "—"
    return _CHANNEL_NAMES.get(track.channels, f"{track.channels}ch")


class TrackTable(ttk.Frame):
    """Zeigt den FilePlan der ausgewählten Datei; Änderungen laufen direkt
    ins Modell und lösen `on_change` aus."""

    def __init__(self, master, *, on_change: Callable[[], None]):
        super().__init__(master)
        self.on_change = on_change
        self.plan: FilePlan | None = None
        self.locked = False   # während eines Laufs sind Pläne eingefroren
        # z. B. „AC3 2.0“ — Startwert aus dem Default, vom Panel überschrieben
        self.convert_label = StereoSettings().short_label()
        self.dovi_ok = False    # dovi_tool verfügbar (vom Hauptfenster gesetzt)
        self._images = theme.make_check_images(self)   # Referenzen halten!

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        scale = lambda px: utility.scale_size(self, px)  # noqa: E731
        columns = ("typ", "codec", "sprache", "kanaele", "name", "aktion", "q")
        self.tree = ttk.Treeview(self, columns=columns, show="tree headings",
                                 selectmode="browse", height=6)
        headings = [("#0", "An", 56), ("typ", "Typ", 84),
                    ("codec", "Codec", 120), ("sprache", "Sprache", 96),
                    ("kanaele", "Kanäle", 64), ("name", "Name", 150),
                    ("aktion", "Aktion", 150), ("q", "Q", 34)]
        for col, text, width in headings:
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=scale(width),
                             stretch=(col in ("name", "codec")))
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                           bootstyle="round-dark")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)

        self.tree.tag_configure("dropped", foreground=theme.MUTED)
        self.tree.tag_configure("stereo", foreground=theme.COLORS["primary"])

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Button-3>", self._on_context)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Motion>", self._on_motion)

    # ── Befüllung ─────────────────────────────────────────────────────────

    def set_plan(self, plan: FilePlan | None) -> None:
        self.plan = plan
        self.tree.delete(*self.tree.get_children())
        if plan is None:
            return
        for track in plan.media.tracks:
            self.tree.insert("", "end", iid=str(track.id), text=f" {track.id}",
                             values=self._row_values(track))
        self.refresh()

    def refresh(self) -> None:
        """Synchronisiert Bilder, Aktionstexte, Q-Spalte und Färbung."""
        if self.plan is None:
            return
        for track in self.plan.media.tracks:
            iid = str(track.id)
            if not self.tree.exists(iid):
                continue
            dec = self.plan.decisions[track.id]
            self.tree.item(iid, image=self._image_for(dec.action),
                           values=self._row_values(track))
            if dec.action is Action.DROP:
                self.tree.item(iid, tags=("dropped",))
            elif dec.action.is_stereo:
                self.tree.item(iid, tags=("stereo",))
            else:
                self.tree.item(iid, tags=())

    def _action_label(self, action: Action) -> str:
        return {
            Action.COPY: "Kopieren",
            Action.STEREO_ADD: f"Kopie + {self.convert_label}",
            Action.STEREO_REPLACE: f"→ {self.convert_label} (ersetzt)",
            Action.DROP: "—",
        }[action]

    _VIDEO_MODE_LABELS = {VIDEO_MODE_HDR10: "DV/HDR → HDR10"}

    def _is_first_video(self, track: Track) -> bool:
        videos = self.plan.media.by_type("video")
        return bool(videos) and videos[0].id == track.id

    def _row_values(self, track: Track) -> tuple:
        dec = self.plan.decisions[track.id]
        if (track.type == "video" and dec.action.keeps_original
                and self.plan.video_mode != VIDEO_MODE_COPY
                and self._is_first_video(track)):
            action = self._VIDEO_MODE_LABELS.get(self.plan.video_mode,
                                                 "Kopieren")
        else:
            action = self._action_label(dec.action)
        if dec.action is not Action.DROP and (
                track.type == "audio"
                or (track.type == "video" and self._is_first_video(track)
                    and self.plan.dv is not None
                    and getattr(self.plan.dv, "has_dv", False))):
            action += "  ▾"
        if self._is_default_audio(track):
            action += "   ★"
        return (TYPE_LABELS.get(track.type, track.type), track.codec_name,
                display_name(track.lang), _fmt_channels(track),
                track.name or "—", action, dec.origin.value)

    def _is_default_audio(self, track: Track) -> bool:
        return (self.plan is not None and track.type == "audio"
                and self.plan.default_audio_source == track.id)

    def _image_for(self, action: Action):
        if action is Action.DROP:
            return self._images["off"]
        if action.is_stereo:
            return self._images["stereo"]
        return self._images["on"]

    # ── Interaktion ───────────────────────────────────────────────────────

    def _track_at(self, y: int) -> Track | None:
        iid = self.tree.identify_row(y)
        if not iid or self.plan is None:
            return None
        return self.plan.media.track(int(iid))

    def _on_click(self, event) -> str | None:
        if self.locked:
            return "break"
        track = self._track_at(event.y)
        if track is None:
            return None
        column = self.tree.identify_column(event.x)
        region = self.tree.identify("region", event.x, event.y)
        if column == "#0" and region == "tree":
            self._toggle(track)
            return "break"          # Selektion nicht ändern
        if column == "#6":          # Aktion-Spalte
            self.tree.selection_set(str(track.id))
            self._post_action_menu(track, event.x_root, event.y_root)
            return "break"
        return None

    def _on_context(self, event) -> None:
        if self.locked:
            return
        track = self._track_at(event.y)
        if track is None:
            return
        self.tree.selection_set(str(track.id))
        self._post_action_menu(track, event.x_root, event.y_root,
                               with_extras=True)

    def _on_space(self, _event) -> str:
        if self.locked:
            return "break"
        for iid in self.tree.selection():
            if self.plan:
                self._toggle(self.plan.media.track(int(iid)), notify=False)
        self._changed()
        return "break"

    def _on_motion(self, event) -> None:
        column = self.tree.identify_column(event.x)
        region = self.tree.identify("region", event.x, event.y)
        clickable = (region in ("tree", "cell")
                     and column in ("#0", "#6")
                     and self.tree.identify_row(event.y))
        self.tree.configure(cursor="hand2" if clickable else "")

    def _toggle(self, track: Track, notify: bool = True) -> None:
        dec = self.plan.decisions[track.id]
        new = Action.DROP if dec.action is not Action.DROP else Action.COPY
        self.plan.set_action(track.id, new, Origin.MANUAL)
        if notify:
            self._changed()

    def _post_action_menu(self, track: Track, x: int, y: int,
                          with_extras: bool = False) -> None:
        menu = tk.Menu(self, tearoff=0)
        dec = self.plan.decisions[track.id]

        def add(label: str, action: Action) -> None:
            marker = "●  " if dec.action is action else "    "
            menu.add_command(label=marker + label,
                             command=lambda a=action: self._set_action(track, a))

        if track.type == "audio":
            add("Kopieren (verlustfrei)", Action.COPY)
            add(f"Kopie + {self.convert_label} (Original behalten)",
                Action.STEREO_ADD)
            add(f"Durch {self.convert_label} ersetzen", Action.STEREO_REPLACE)
            add("Entfernen", Action.DROP)
            if with_extras and dec.action is not Action.DROP:
                menu.add_separator()
                menu.add_command(
                    label="Als Standard-Audiospur",
                    command=lambda: self._make_default(track))
        elif track.type == "video" and self._is_first_video(track):
            self._add_video_entries(menu, track, dec)
        else:
            add("Behalten (verlustfrei)", Action.COPY)
            add("Entfernen", Action.DROP)

        menu.tk_popup(x, y)

    def _add_video_entries(self, menu: tk.Menu, track: Track, dec) -> None:
        """Videospur-Menü inkl. DV/HDR-Remux (verlustfrei, kein Encoding)."""
        mode = self.plan.video_mode
        dvi = self.plan.dv

        def marker(active: bool) -> str:
            return "●  " if active else "    "

        menu.add_command(
            label=marker(dec.action is Action.COPY and mode == VIDEO_MODE_COPY)
            + "Kopieren (verlustfrei)",
            command=lambda: self._set_video_mode(track, VIDEO_MODE_COPY))

        # DV/HDR entfernen → HDR10 (der einzige DV-Modus)
        if dvi is None:
            reason = "DV-Analyse fehlt — FFmpeg über ⚙ neu laden (bringt ffprobe mit)"
        elif not self.dovi_ok:
            reason = dvi.hdr10_blocked_reason() or "dovi_tool fehlt (⚙)"
        else:
            reason = dvi.hdr10_blocked_reason()
        label = (marker(mode == VIDEO_MODE_HDR10)
                 + "DV/HDR entfernen → HDR10 — bei Kompatibilitätsproblemen")
        if reason:
            menu.add_command(label=f"{label}   — {reason}", state="disabled")
        else:
            menu.add_command(
                label=label,
                command=lambda: self._set_video_mode(track, VIDEO_MODE_HDR10))

        menu.add_separator()
        menu.add_command(label=marker(dec.action is Action.DROP) + "Entfernen",
                         command=lambda: self._drop_video(track))

    def _set_video_mode(self, track: Track, mode: str) -> None:
        self.plan.video_mode = mode
        self.plan.set_action(track.id, Action.COPY, Origin.MANUAL)
        self._changed()

    def _drop_video(self, track: Track) -> None:
        self.plan.video_mode = VIDEO_MODE_COPY   # Modus ist ohne Videospur sinnlos
        self._set_action(track, Action.DROP)

    def _set_action(self, track: Track, action: Action) -> None:
        self.plan.set_action(track.id, action, Origin.MANUAL)
        self._changed()

    def _make_default(self, track: Track) -> None:
        dec = self.plan.decisions[track.id]
        self.plan.set_default_audio(track.id, on_stereo=dec.action.is_stereo)
        self._changed()

    # ── Massenaktionen (Buttons im Sektionskopf) ──────────────────────────

    def set_all(self, keep: bool) -> None:
        if self.plan is None or self.locked:
            return
        for track in self.plan.media.tracks:
            self.plan.set_action(
                track.id, Action.COPY if keep else Action.DROP, Origin.MANUAL)
        self._changed()

    def _changed(self) -> None:
        self.refresh()
        self.on_change()
