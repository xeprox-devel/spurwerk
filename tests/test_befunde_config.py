"""Befunde config.json: atomares/serialisiertes Speichern, defekte Datei
beiseitelegen statt überschreiben, unbekannte verschachtelte Schlüssel."""

import json
import os
import pathlib
import threading
import time

import pytest

import config
from core.model import OutputSettings, RuleProfile, StereoSettings


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    """Alle Config-Pfade in tmp_path — nie die echte config.json anfassen."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config, "LEGACY_INI", tmp_path / "config.ini")
    monkeypatch.setattr(config, "base_path", lambda: tmp_path)
    return tmp_path


def sample(tmdb="key-1", profile_name="Mein Profil"):
    profile = RuleProfile(name=profile_name, lang_priority=["de", "ja"],
                          stereo=StereoSettings(codec="eac3", channels="5.1"),
                          output=OutputSettings(suffix="_neu"))
    return config.AppConfig(tools={"mkvmerge": "C:/Jürgen/mkvmerge.exe"},
                            tmdb_key=tmdb, output_dir="D:/Filme",
                            user_profiles=[profile],
                            session=[{"path": "C:/Größe.mkv"}])


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def aside_files(folder):
    return [p for p in folder.iterdir() if ".defekt-" in p.name]


# ── Speichern ─────────────────────────────────────────────────────────────


def test_round_trip(cfgdir):
    config.save(sample())
    cfg = config.load()
    assert cfg.tools == {"mkvmerge": "C:/Jürgen/mkvmerge.exe"}
    assert cfg.tmdb_key == "key-1"
    assert cfg.output_dir == "D:/Filme"
    assert cfg.session == [{"path": "C:/Größe.mkv"}]
    (p,) = cfg.user_profiles
    assert p.name == "Mein Profil" and p.lang_priority == ["de", "ja"]
    assert p.stereo.codec == "eac3" and p.output.suffix == "_neu"
    assert cfg.load_notice == ""
    # keine Temp-Datei bleibt liegen, alles liegt neben CONFIG_FILE
    assert names(cfgdir) == ["config.json"]


def test_vorige_gute_fassung_bleibt_als_bak(cfgdir):
    config.save(sample(tmdb="alt"))
    config.save(sample(tmdb="neu"))
    config.save(sample(tmdb="neu"))   # unverändert → .bak bleibt „alt“
    assert json.loads(config.CONFIG_FILE.read_text("utf-8"))["tmdb_key"] == "neu"
    bak = cfgdir / "config.json.bak"
    assert json.loads(bak.read_text("utf-8"))["tmdb_key"] == "alt"
    assert names(cfgdir) == ["config.json", "config.json.bak"]


def test_defekte_datei_wird_nie_zur_sicherung(cfgdir):
    config.save(sample(tmdb="gut"))
    config.save(sample(tmdb="gut2"))            # .bak = „gut“
    config.CONFIG_FILE.write_bytes(b'{"tmdb_key": "hal')
    config.save(sample(tmdb="gut3"))
    bak = cfgdir / "config.json.bak"
    assert json.loads(bak.read_text("utf-8"))["tmdb_key"] == "gut"


def test_abgebrochenes_schreiben_laesst_alte_datei_heil(cfgdir, monkeypatch):
    config.save(sample(tmdb="alt"))
    before = config.CONFIG_FILE.read_bytes()

    def boom(*_args):
        raise OSError("Datenträger voll")
    monkeypatch.setattr(config.os, "fsync", boom)
    with pytest.raises(OSError):
        config.save(sample(tmdb="neu"))

    assert config.CONFIG_FILE.read_bytes() == before
    assert not list(cfgdir.glob("*.tmp"))


def test_ersetzen_wiederholt_bei_kurzer_sperre(cfgdir, monkeypatch):
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("Virenscanner hält die Datei")
        return real_replace(src, dst)
    monkeypatch.setattr(config.os, "replace", flaky)
    config.save(sample(tmdb="x"))
    assert config.load().tmdb_key == "x"


def test_speichern_ist_serialisiert(cfgdir, monkeypatch):
    real_write = config._write_atomic
    state = {"active": 0, "max": 0}
    guard = threading.Lock()

    def slow_write(path, raw):
        with guard:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.005)
        try:
            real_write(path, raw)
        finally:
            with guard:
                state["active"] -= 1
    monkeypatch.setattr(config, "_write_atomic", slow_write)

    def worker(i):
        for j in range(5):
            config.save(sample(tmdb=f"t{i}-{j}" * (i + 1)))
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["max"] == 1
    json.loads(config.CONFIG_FILE.read_text("utf-8"))   # gültig, nicht zerrissen
    assert config.load().load_notice == ""


def test_zweite_instanz_kollidiert_nicht_beim_temp(cfgdir, monkeypatch):
    """Zwei Spurwerk-Instanzen im selben Ordner (_SAVE_LOCK hilft nur
    innerhalb eines Prozesses): die andere schreibt mitten in unser
    Speichern hinein — keine darf der anderen die Temp-Datei wegnehmen."""
    real_fsync = os.fsync
    state = {"andere": False}

    def fsync_mit_zweiter_instanz(fd):
        real_fsync(fd)
        if not state["andere"]:
            state["andere"] = True
            config._write_atomic(config.CONFIG_FILE, b'{"tmdb_key": "B"}')
    monkeypatch.setattr(config.os, "fsync", fsync_mit_zweiter_instanz)

    config._write_atomic(config.CONFIG_FILE, b'{"tmdb_key": "A"}')  # wirft nicht
    assert config.CONFIG_FILE.read_bytes() == b'{"tmdb_key": "A"}'
    assert names(cfgdir) == ["config.json"]


# ── Laden ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [
    b'{"tmdb_key": "abc", "user_profiles": [',        # zerrissen
    b'{"tmdb_key": "J\xfcrgen"}',                      # ANSI statt UTF-8
    b'[]',                                            # kein Objekt
    b'null',
    b'{"user_profiles": ["kaputt"]}',                 # falscher Typ
    b'{"tools": 5}',
    b'',
])
def test_defekte_datei_wird_beiseitegelegt(cfgdir, raw):
    config.CONFIG_FILE.write_bytes(raw)
    cfg = config.load()                                # darf nie werfen
    assert cfg.user_profiles == [] and cfg.tools == {}
    assert "beschädigt" in cfg.load_notice
    assert "Standardeinstellungen" in cfg.load_notice
    assert not config.CONFIG_FILE.exists()
    (aside,) = aside_files(cfgdir)
    assert aside.read_bytes() == raw

    # das nächste Speichern überschreibt die defekte Fassung nicht
    config.save(cfg)
    assert aside.read_bytes() == raw


def test_defekte_datei_faellt_auf_sicherung_zurueck(cfgdir):
    config.save(sample(tmdb="alt"))
    config.save(sample(tmdb="neu"))                    # .bak = „alt“
    config.CONFIG_FILE.write_bytes(b'{"tmdb_key": "neu", "user_pro')
    cfg = config.load()
    assert cfg.tmdb_key == "alt"
    assert [p.name for p in cfg.user_profiles] == ["Mein Profil"]
    assert "Sicherung" in cfg.load_notice
    assert len(aside_files(cfgdir)) == 1


def test_wiederhergestellte_sicherung_ueberlebt_absturz(cfgdir):
    """Absturz vor dem ersten Speichern nach der Wiederherstellung: der
    nächste Start darf nicht auf Standard fallen und die Sicherung nicht
    durch zwei Speichervorgänge verloren gehen."""
    config.save(sample(tmdb="alt"))
    config.save(sample(tmdb="neu"))                    # .bak = „alt“
    config.CONFIG_FILE.write_bytes(b'{"tmdb_')
    assert "Sicherung" in config.load().load_notice
    assert config.CONFIG_FILE.exists()                 # sofort zurückgeschrieben

    cfg = config.load()                                # zweiter Start
    assert cfg.tmdb_key == "alt" and cfg.load_notice == ""
    assert [p.name for p in cfg.user_profiles] == ["Mein Profil"]
    cfg.window_geometry = "800x600"
    config.save(cfg)
    cfg.window_geometry = "900x600"
    config.save(cfg)
    bak = json.loads((cfgdir / "config.json.bak").read_text("utf-8"))
    assert bak["tmdb_key"] == "alt"
    assert [p["name"] for p in bak["user_profiles"]] == ["Mein Profil"]


def test_rueckschreiben_der_sicherung_darf_scheitern(cfgdir, monkeypatch):
    config.save(sample(tmdb="alt"))
    config.save(sample(tmdb="neu"))
    config.CONFIG_FILE.write_bytes(b"{kaputt")

    def voll(*_args):
        raise OSError("Datenträger voll")
    monkeypatch.setattr(config, "_write_atomic", voll)
    cfg = config.load()                                # darf nie werfen
    assert cfg.tmdb_key == "alt" and "Sicherung" in cfg.load_notice


def test_nicht_beiseitegelegte_datei_wird_beim_laden_nicht_ueberschrieben(
        cfgdir, monkeypatch):
    config.save(sample(tmdb="alt"))
    config.save(sample(tmdb="neu"))
    config.CONFIG_FILE.write_bytes(b"{kaputt")
    monkeypatch.setattr(config, "_set_aside", lambda _path: None)
    cfg = config.load()
    assert cfg.tmdb_key == "alt" and "daneben" not in cfg.load_notice
    assert config.CONFIG_FILE.read_bytes() == b"{kaputt"


def test_kurze_lesesperre_legt_gute_datei_nicht_beiseite(cfgdir, monkeypatch):
    """Eine zweite Instanz ersetzt gerade config.json → kurzer
    PermissionError beim Öffnen; das ist kein Schaden."""
    config.save(sample(tmdb="gut"))
    real_read = pathlib.Path.read_bytes
    calls = {"n": 0}

    def gesperrt(self):
        if self == config.CONFIG_FILE:
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("andere Instanz ersetzt gerade")
        return real_read(self)
    monkeypatch.setattr(pathlib.Path, "read_bytes", gesperrt)
    cfg = config.load()
    assert cfg.tmdb_key == "gut" and cfg.load_notice == ""
    assert not aside_files(cfgdir)


def test_anhaltende_lesesperre_wird_gemeldet(cfgdir, monkeypatch):
    config.CONFIG_FILE.write_bytes(json.dumps({"tmdb_key": "x"}).encode())
    real_read = pathlib.Path.read_bytes

    def gesperrt(self):
        if self == config.CONFIG_FILE:
            raise PermissionError("Zugriff verweigert")
        return real_read(self)
    monkeypatch.setattr(pathlib.Path, "read_bytes", gesperrt)
    monkeypatch.setattr(config.time, "sleep", lambda _s: None)
    cfg = config.load()                                # darf nie werfen
    assert "ließ sich nicht lesen" in cfg.load_notice
    assert "Standardeinstellungen" in cfg.load_notice
    (aside,) = aside_files(cfgdir)                     # erhalten, nicht überschrieben
    assert json.loads(aside.read_bytes())["tmdb_key"] == "x"


def test_defekte_sicherung_ergibt_standardwerte(cfgdir):
    config.CONFIG_FILE.write_bytes(b"{kaputt")
    (cfgdir / "config.json.bak").write_bytes(b"[1, 2")
    cfg = config.load()
    assert cfg.tmdb_key == "" and "Standardeinstellungen" in cfg.load_notice


def test_zweimal_defekt_in_derselben_sekunde(cfgdir):
    for _ in range(2):
        config.CONFIG_FILE.write_bytes(b"{kaputt")
        config.load()
    assert len(aside_files(cfgdir)) == 2


def test_fehlende_datei_nimmt_nicht_die_sicherung(cfgdir):
    """config.json löschen = bewusst auf Standard zurücksetzen."""
    config.save(sample(tmdb="alt"))
    config.save(sample(tmdb="neu"))
    config.CONFIG_FILE.unlink()
    cfg = config.load()
    assert cfg.tmdb_key == "" and cfg.load_notice == ""


def test_utf8_bom_wird_toleriert(cfgdir):
    config.CONFIG_FILE.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"tmdb_key": "bom"}).encode())
    cfg = config.load()
    assert cfg.tmdb_key == "bom" and cfg.load_notice == ""
    assert not aside_files(cfgdir)


def test_unbekannte_verschachtelte_schluessel_werden_ignoriert(cfgdir):
    """Config aus einer neueren Version: neue Felder in stereo/output
    dürfen nicht alles auf Standard zurücksetzen."""
    data = {"version": 1, "tmdb_key": "k", "user_profiles": [{
        "name": "Neu", "neues_feld": 1,
        "stereo": {"codec": "eac3", "channels": "5.1", "zukunft": True},
        "output": {"suffix": "_x", "zukunft": "ja"},
    }]}
    config.CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")
    cfg = config.load()
    (p,) = cfg.user_profiles
    assert p.name == "Neu"
    assert p.stereo.codec == "eac3" and p.stereo.channels == "5.1"
    assert p.output.suffix == "_x"
    assert cfg.tmdb_key == "k" and cfg.load_notice == ""
    assert not aside_files(cfgdir)


def test_stereo_output_null_ergibt_standard(cfgdir):
    data = {"user_profiles": [{"name": "P", "stereo": None, "output": None}]}
    config.CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")
    (p,) = config.load().user_profiles
    assert p.stereo == StereoSettings() and p.output == OutputSettings()
