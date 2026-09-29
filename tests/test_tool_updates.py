"""Werkzeug-Updates: Versionsvergleich, Abfrage der neuesten Versionen und
Prüfsummen-Pflicht für dovi_tool. Komplett ohne Netz — die Quellen werden
per monkeypatch ersetzt."""

import hashlib
import io
import json
import subprocess
import threading
import zipfile

import pytest

from core import downloader
from core import tools as toolchain
from core.tools import CURRENT, OUTDATED, UNKNOWN, ToolStatus


def _status(**versions) -> dict[str, ToolStatus]:
    return {name: ToolStatus(name, f"C:/tools/{name}.exe", version)
            for name, version in versions.items()}


class TestComparableVersion:
    def test_release_nummern(self):
        assert toolchain.comparable_version("94.0") == (94, 0)
        assert toolchain.comparable_version("9.0.2") == (9, 0, 2)

    def test_entwicklungs_builds_sind_nicht_vergleichbar(self):
        # gyan-Git-Build (nach dem Kürzen in probe) und BtbN-Master
        assert toolchain.comparable_version("2025-09-04") == ()
        assert toolchain.comparable_version("N-121000-gabc1234-20250904") == ()

    def test_leer(self):
        assert toolchain.comparable_version("") == ()


class TestUpdateState:
    def test_veraltet(self):
        assert toolchain.update_state("94.0", "102.0") == OUTDATED
        assert toolchain.update_state("2.3.2", "2.3.4") == OUTDATED

    def test_numerisch_nicht_lexikografisch(self):
        # „102.0“ < „94.0“ als Text — als Zahl ist 102 neuer
        assert toolchain.update_state("94.0", "102.0") == OUTDATED
        assert toolchain.update_state("102.0", "94.0") == CURRENT

    def test_gleich_ist_aktuell(self):
        assert toolchain.update_state("102.0", "102.0") == CURRENT

    def test_neuer_als_release_gilt_als_aktuell(self):
        # nie zu einem Downgrade raten
        assert toolchain.update_state("2.4.0", "2.3.4") == CURRENT

    def test_unbekannt(self):
        assert toolchain.update_state("9.0.2", None) == UNKNOWN
        assert toolchain.update_state("2025-09-04", "9.0.2") == UNKNOWN
        assert toolchain.update_state("", "9.0.2") == UNKNOWN


class TestPendingUpdates:
    def test_nur_sicher_veraltete(self):
        status = _status(mkvmerge="94.0", ffmpeg="2025-09-04",
                         ffprobe="2025-09-04", dovi_tool="2.3.4")
        latest = {"mkvtoolnix": "102.0", "ffmpeg": "9.0.2",
                  "dovi_tool": "2.3.4"}
        updates = toolchain.pending_updates(status, latest)
        assert updates == [toolchain.ToolUpdate("mkvtoolnix", "94.0",
                                                "102.0")]

    def test_fehlende_werkzeuge_zaehlen_nicht(self):
        status = _status(mkvmerge="", ffmpeg="9.0.2", ffprobe="9.0.2")
        latest = {"mkvtoolnix": "102.0", "ffmpeg": "9.0.2",
                  "dovi_tool": "2.3.4"}
        assert toolchain.pending_updates(status, latest) == []

    def test_ohne_pruefergebnis_nichts(self):
        status = _status(mkvmerge="94.0", ffmpeg="8.0", ffprobe="8.0",
                         dovi_tool="2.3.2")
        assert toolchain.pending_updates(status, {}) == []
        assert toolchain.pending_updates(
            status, {"mkvtoolnix": None, "ffmpeg": None,
                     "dovi_tool": None}) == []


class TestProbeVersionstext:
    """probe() kürzt die echten --version-Ausgaben auf die Nummer."""

    @pytest.fixture
    def fake_exe(self, tmp_path):
        exe = tmp_path / "tool.exe"
        exe.write_bytes(b"")
        return str(exe)

    def _probe(self, monkeypatch, name, path, stdout):
        def fake_run(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, stdout=stdout,
                                               stderr="")
        monkeypatch.setattr(toolchain.subprocess, "run", fake_run)
        return toolchain.probe(name, path).version

    def test_gyan_release_build(self, monkeypatch, fake_exe):
        out = ("ffmpeg version 9.0.2-essentials_build-www.gyan.dev "
               "Copyright (c) 2000-2026 the FFmpeg developers")
        assert self._probe(monkeypatch, "ffmpeg", fake_exe, out) == "9.0.2"

    def test_gyan_git_build(self, monkeypatch, fake_exe):
        out = ("ffmpeg version 2025-09-04-git-2611874a50-full_build-www."
               "gyan.dev Copyright (c) 2000-2025 the FFmpeg developers")
        assert self._probe(monkeypatch, "ffmpeg", fake_exe,
                           out) == "2025-09-04"

    def test_btbn_master_build_bleibt_erkennbar(self, monkeypatch, fake_exe):
        out = "ffmpeg version N-121000-gabc1234-20250904 Copyright"
        version = self._probe(monkeypatch, "ffmpeg", fake_exe, out)
        assert version.startswith("N-")
        assert toolchain.comparable_version(version) == ()

    def test_mkvmerge(self, monkeypatch, fake_exe):
        out = "mkvmerge v94.0 ('Initiate') 64-bit"
        assert self._probe(monkeypatch, "mkvmerge", fake_exe, out) == "94.0"


class TestLatestVersions:
    def test_alle_quellen_erreichbar(self, monkeypatch):
        monkeypatch.setattr(downloader, "mkvtoolnix_latest_version",
                            lambda timeout=None: "102.0")
        monkeypatch.setattr(downloader, "_get_text",
                            lambda url, timeout=None: "9.0.2")
        monkeypatch.setattr(
            downloader, "_final_url", lambda url, timeout=None:
            "https://github.com/quietvoid/dovi_tool/releases/tag/2.3.4")
        assert downloader.latest_versions() == {
            "mkvtoolnix": "102.0", "ffmpeg": "9.0.2", "dovi_tool": "2.3.4"}

    def test_ausfall_einer_quelle_wirft_nie(self, monkeypatch):

        def offline(*_a, **_k):
            raise OSError("keine Verbindung")
        monkeypatch.setattr(downloader, "mkvtoolnix_latest_version", offline)
        monkeypatch.setattr(downloader, "_get_text",
                            lambda url, timeout=None: "<html>Fehler</html>")
        monkeypatch.setattr(
            downloader, "_final_url", lambda url, timeout=None:
            "https://github.com/quietvoid/dovi_tool/releases/tag/2.3.4")
        latest = downloader.latest_versions()
        assert latest["mkvtoolnix"] is None
        assert latest["ffmpeg"] is None   # Fehlerseite ist keine Version
        assert latest["dovi_tool"] == "2.3.4"

    def test_dovi_weiterleitung_ohne_tag_ist_keine_version(self, monkeypatch):
        # landet die Weiterleitung nicht auf …/tag/<nr> (z. B. Login-Seite),
        # darf daraus keine Version werden
        monkeypatch.setattr(
            downloader, "_final_url", lambda url, timeout=None:
            "https://github.com/quietvoid/dovi_tool/releases")
        with pytest.raises(ValueError):
            downloader._latest_dovi_tool()

    def test_release_nummer_filtert_muell(self):
        assert downloader._release_number("v2.3.4") == "2.3.4"
        assert downloader._release_number(" 102.0\n") == "102.0"
        for junk in ("", "release", "404", "9.0.2-beta", "<html>"):
            with pytest.raises(ValueError):
                downloader._release_number(junk)


class TestDoviToolPruefsumme:
    """dovi_tool wird jetzt gegen den GitHub-Asset-Digest geprüft."""

    @staticmethod
    def _zip_bytes() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("dovi_tool.exe", b"MZ fake exe")
        return buf.getvalue()

    def _setup(self, monkeypatch, digest: str | None):
        payload = self._zip_bytes()
        asset = {"name": "dovi_tool-2.3.4-x86_64-pc-windows-msvc.zip",
                 "browser_download_url": "https://example.invalid/d.zip"}
        if digest is not None:
            asset["digest"] = digest
        release = {"tag_name": "2.3.4", "assets": [asset]}
        monkeypatch.setattr(downloader, "_get_bytes",
                            lambda url, timeout=None:
                            json.dumps(release).encode())

        def fake_download(url, dest, progress, label, cancel):
            dest.write_bytes(payload)
            return hashlib.sha256(payload).hexdigest()
        monkeypatch.setattr(downloader, "_download", fake_download)
        return payload

    def test_passender_digest(self, monkeypatch, tmp_path):
        payload = self._zip_bytes()
        self._setup(monkeypatch,
                    "sha256:" + hashlib.sha256(payload).hexdigest())
        result = downloader.download_dovi_tool(
            tmp_path, lambda *_: None, threading.Event())
        assert result.version == "2.3.4"
        assert (tmp_path / "dovi_tool.exe").read_bytes() == b"MZ fake exe"
        assert not list(tmp_path.glob("*.zip"))   # Archiv aufgeräumt

    def test_falscher_digest_bricht_ab(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, "sha256:" + "0" * 64)
        with pytest.raises(downloader.DownloadError, match="SHA-256"):
            downloader.download_dovi_tool(
                tmp_path, lambda *_: None, threading.Event())
        assert not (tmp_path / "dovi_tool.exe").exists()
        assert not list(tmp_path.glob("*.zip"))

    def test_ohne_digest_weiter_moeglich(self, monkeypatch, tmp_path):
        # ältere Releases ohne Digest: Download bleibt möglich
        self._setup(monkeypatch, None)
        result = downloader.download_dovi_tool(
            tmp_path, lambda *_: None, threading.Event())
        assert result.version == "2.3.4"

    def test_api_limit_ersatzweg_ueber_release_link(self, monkeypatch,
                                                     tmp_path):
        payload = self._zip_bytes()

        def api_limit(url, timeout=None):
            raise OSError("HTTP Error 403: rate limit exceeded")
        monkeypatch.setattr(downloader, "_get_bytes", api_limit)
        monkeypatch.setattr(
            downloader, "_final_url", lambda url, timeout=None:
            "https://github.com/quietvoid/dovi_tool/releases/tag/2.3.4")
        seen = {}

        def fake_download(url, dest, progress, label, cancel):
            seen["url"] = url
            dest.write_bytes(payload)
            return hashlib.sha256(payload).hexdigest()
        monkeypatch.setattr(downloader, "_download", fake_download)
        steps = []
        result = downloader.download_dovi_tool(
            tmp_path, lambda msg, _pct: steps.append(msg), threading.Event())
        assert result.version == "2.3.4"
        assert seen["url"] == (
            "https://github.com/quietvoid/dovi_tool/releases/download/"
            "2.3.4/dovi_tool-2.3.4-x86_64-pc-windows-msvc.zip")
        assert any("Release-Link" in s for s in steps)
        # Release-Seite auch nicht erreichbar → ohne Digest, ehrlich markiert
        assert result.verified is False

    def test_ersatzweg_holt_digest_von_der_release_seite(self, monkeypatch,
                                                         tmp_path):
        payload = self._zip_bytes()
        good = hashlib.sha256(payload).hexdigest()
        name = "dovi_tool-2.3.4-x86_64-pc-windows-msvc.zip"
        # Auszug der echten Seite (29.09.2026): Nachbardatei davor, damit
        # der Regex nachweislich den Digest DIESES Assets nimmt
        page = (f'<button aria-label="Copy to clipboard digest for '
                f'libdovi-3.4.0-x86_64-pc-windows-msvc.zip" type="button" '
                f'value="sha256:{"1" * 64}"></button>'
                f'<button aria-label="Copy to clipboard digest for {name}" '
                f'type="button" value="sha256:{good}" class="Button">')

        def fake_get_bytes(url, timeout=None):
            if "api.github.com" in url:
                raise OSError("HTTP Error 403: rate limit exceeded")
            assert url.endswith("/expanded_assets/2.3.4")
            return page.encode()
        monkeypatch.setattr(downloader, "_get_bytes", fake_get_bytes)
        monkeypatch.setattr(
            downloader, "_final_url", lambda url, timeout=None:
            "https://github.com/quietvoid/dovi_tool/releases/tag/2.3.4")

        def fake_download(url, dest, progress, label, cancel):
            dest.write_bytes(payload)
            return good
        monkeypatch.setattr(downloader, "_download", fake_download)
        result = downloader.download_dovi_tool(
            tmp_path, lambda *_: None, threading.Event())
        assert result.verified is True

    def test_asset_sha256_parser(self):
        good = "a" * 64
        assert downloader._asset_sha256({"digest": f"sha256:{good}"}) == good
        assert downloader._asset_sha256({"digest": "SHA256:" + good.upper()}
                                        ) == good
        assert downloader._asset_sha256({}) is None
        assert downloader._asset_sha256({"digest": "sha512:abc"}) is None
        assert downloader._asset_sha256({"digest": "sha256:kurz"}) is None


class TestNachbesserungen:
    """Befunde aus der Projektprüfung rund um die Werkzeuge."""

    def test_ffprobe_neben_selbst_gewaehltem_ffmpeg(self, tmp_path):
        own = tmp_path / "eigenes"
        own.mkdir()
        (own / "ffmpeg.exe").write_bytes(b"")
        (own / "ffprobe.exe").write_bytes(b"")
        base = tmp_path / "app"
        (base / "tools").mkdir(parents=True)
        paths = toolchain.detect_tools(
            base, {"ffmpeg": str(own / "ffmpeg.exe")})
        assert paths["ffprobe"] == str(own / "ffprobe.exe")

    def test_ffprobe_sonst_aus_tools(self, tmp_path):
        base = tmp_path / "app"
        (base / "tools").mkdir(parents=True)
        for name in ("ffmpeg", "ffprobe"):
            (base / "tools" / f"{name}.exe").write_bytes(b"")
        paths = toolchain.detect_tools(base, {})
        assert paths["ffprobe"] == str(base / "tools" / "ffprobe.exe")

    def test_entpacken_hinterlaesst_keine_part_reste(self, monkeypatch,
                                                     tmp_path):
        archive = tmp_path / "a.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("bin/ffmpeg.exe", b"x" * 1000)

        def in_use(self, target):   # Ziel-EXE läuft gerade
            raise PermissionError("in Benutzung")
        monkeypatch.setattr(downloader.Path, "replace", in_use)
        with pytest.raises(downloader.DownloadError, match="Austausch"):
            downloader._extract_members(
                archive, {"bin/ffmpeg.exe": "ffmpeg.exe"}, tmp_path,
                lambda *_: None)
        assert not list(tmp_path.glob("*.part"))

    def test_ohne_pruefsumme_wird_als_ungeprueft_gemeldet(self, monkeypatch,
                                                          tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("x/bin/ffmpeg.exe", b"MZ")
            zf.writestr("x/bin/ffprobe.exe", b"MZ")
        payload = buf.getvalue()

        def no_sums(url, timeout=None):   # .sha256 gerade nicht abrufbar
            raise OSError("HTTP Error 404")
        monkeypatch.setattr(downloader, "_get_text", no_sums)

        def fake_download(url, dest, progress, label, cancel):
            dest.write_bytes(payload)
            return hashlib.sha256(payload).hexdigest()
        monkeypatch.setattr(downloader, "_download", fake_download)
        result = downloader.download_ffmpeg(
            tmp_path, lambda *_: None, threading.Event())
        assert result.verified is False
        assert (tmp_path / "ffprobe.exe").exists()

    @staticmethod
    def _ffmpeg_zip(tag: bytes) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("x/bin/ffmpeg.exe", b"ffmpeg " + tag)
            zf.writestr("x/bin/ffprobe.exe", b"ffprobe " + tag)
        return buf.getvalue()

    def test_paket_wird_ganz_oder_gar_nicht_getauscht(self, monkeypatch,
                                                     tmp_path):
        (tmp_path / "ffmpeg.exe").write_bytes(b"ffmpeg alt")
        (tmp_path / "ffprobe.exe").write_bytes(b"ffprobe alt")
        archive = tmp_path / "neu.zip"
        archive.write_bytes(self._ffmpeg_zip(b"neu"))
        real_replace = downloader.Path.replace

        def fail_on_ffprobe(self, target):
            # zweiter Austausch scheitert (Platte voll, Virenscanner …)
            if self.name == "ffprobe.part":
                raise OSError("Datenträger voll")
            return real_replace(self, target)
        monkeypatch.setattr(downloader.Path, "replace", fail_on_ffprobe)
        with pytest.raises(downloader.DownloadError, match="bleibt"):
            downloader._extract_members(
                archive, {"bin/ffmpeg.exe": "ffmpeg.exe",
                          "bin/ffprobe.exe": "ffprobe.exe"},
                tmp_path, lambda *_: None)
        # beide wieder alt — kein neues ffmpeg neben altem ffprobe
        assert (tmp_path / "ffmpeg.exe").read_bytes() == b"ffmpeg alt"
        assert (tmp_path / "ffprobe.exe").read_bytes() == b"ffprobe alt"
        assert not list(tmp_path.glob("*.part"))

    def test_austausch_klappt_und_raeumt_auf(self, tmp_path):
        (tmp_path / "ffmpeg.exe").write_bytes(b"ffmpeg alt")
        (tmp_path / "ffprobe.exe").write_bytes(b"ffprobe alt")
        (tmp_path / "ffmpeg.old").write_bytes(b"rest vom letzten Mal")
        archive = tmp_path / "neu.zip"
        archive.write_bytes(self._ffmpeg_zip(b"neu"))
        downloader._extract_members(
            archive, {"bin/ffmpeg.exe": "ffmpeg.exe",
                      "bin/ffprobe.exe": "ffprobe.exe"},
            tmp_path, lambda *_: None)
        assert (tmp_path / "ffmpeg.exe").read_bytes() == b"ffmpeg neu"
        assert (tmp_path / "ffprobe.exe").read_bytes() == b"ffprobe neu"
        assert not list(tmp_path.glob("*.old*"))
        assert not list(tmp_path.glob("*.part"))

    def _gyan_setup(self, monkeypatch, gyan_error: Exception):
        monkeypatch.setattr(downloader, "_gyan_version", lambda: "9.0.2")
        btbn = self._ffmpeg_zip(b"btbn-master")
        calls = []

        def fake_from(url, sums_url, version, tools_dir, progress, cancel,
                      **_kw):
            calls.append(url)
            if url == downloader.GYAN_ZIP:
                raise gyan_error
            (tools_dir / "ffmpeg.exe").write_bytes(btbn)
            return downloader.DownloadResult("ffmpeg", version, [])
        monkeypatch.setattr(downloader, "_ffmpeg_from", fake_from)
        return calls

    def test_update_weicht_nie_auf_entwicklungs_build_aus(self, monkeypatch,
                                                         tmp_path):
        (tmp_path / "ffmpeg.exe").write_bytes(b"ffmpeg 8.1")   # Update-Fall
        calls = self._gyan_setup(
            monkeypatch, downloader.SourceUnreachable("Zeitüberschreitung"))
        with pytest.raises(downloader.DownloadError):
            downloader.download_ffmpeg(tmp_path, lambda *_: None,
                                       threading.Event())
        assert calls == [downloader.GYAN_ZIP]
        assert (tmp_path / "ffmpeg.exe").read_bytes() == b"ffmpeg 8.1"

    def test_pruefsummenfehler_wird_nie_umgangen(self, monkeypatch,
                                                  tmp_path):
        calls = self._gyan_setup(monkeypatch, downloader.DownloadError(
            "SHA-256-Prüfung fehlgeschlagen"))
        with pytest.raises(downloader.DownloadError, match="SHA-256"):
            downloader.download_ffmpeg(tmp_path, lambda *_: None,
                                       threading.Event())
        assert calls == [downloader.GYAN_ZIP]   # kein BtbN-Ausweichen

    def test_ersteinrichtung_darf_ausweichen(self, monkeypatch, tmp_path):
        calls = self._gyan_setup(
            monkeypatch, downloader.SourceUnreachable("gyan.dev offline"))
        downloader.download_ffmpeg(tmp_path, lambda *_: None,
                                   threading.Event())
        assert len(calls) == 2 and "BtbN" in calls[1]

    def test_haertung_versionen_und_namen(self):
        with pytest.raises(ValueError):
            downloader._release_number("2.3.²")      # isdigit, aber kein ASCII
        with pytest.raises(ValueError):
            downloader._release_number("../../1.0")
        # BtbN-Release-Build ist vergleichbar, der Master-Snapshot nicht
        assert toolchain.comparable_version("n9.0.2") == (9, 0, 2)
        assert toolchain.update_state("n8.0", "9.0.2") == OUTDATED

    def test_expect_hash_beide_formate(self):
        digest = "ab" * 32
        # gyan: nur der Digest
        assert downloader._expect_hash(digest + "\n", "x.zip") == digest
        # BtbN/MKVToolNix: „hash  name“ pro Zeile, exakter Namensvergleich
        sums = (f"{'cd' * 32}  other-ffmpeg-win64-gpl.zip\n"
                f"{digest}  ffmpeg-win64-gpl.zip\n")
        assert downloader._expect_hash(sums,
                                       "ffmpeg-win64-gpl.zip") == digest
        assert downloader._expect_hash(sums, "fehlt.zip") is None
