"""Sitzungs-Serialisierung: Round-Trip der Job-Konfiguration."""

from core import session
from core.dv import VIDEO_MODE_HDR10
from core.model import Action, Origin
from core.planner import build_plan
from tests.helpers import film_std, profile_de


def configured_plan():
    plan = build_plan(film_std(), profile_de())
    plan.profile_name = "Test DE"
    plan.stereo.codec = "eac3"
    plan.stereo.channels = "5.1"
    plan.video_mode = VIDEO_MODE_HDR10
    plan.set_action(2, Action.DROP)          # en-Audio manuell raus (Override)
    plan.output_path = "C:/out/film [HDR10].mkv"
    return plan


def test_round_trip_erhaelt_konfiguration():
    original = configured_plan()
    job = session.serialize_plan(original)

    # frischer Plan aus denselben Medien (wie nach Neu-Scan)
    fresh = build_plan(film_std(), profile_de())
    session.restore_plan(fresh, job)

    assert fresh.profile_name == "Test DE"
    assert fresh.stereo.codec == "eac3"
    assert fresh.stereo.channels == "5.1"
    assert fresh.video_mode == VIDEO_MODE_HDR10
    assert fresh.decisions[2].action is Action.DROP
    assert fresh.decisions[2].origin is Origin.MANUAL


def test_nur_manuelle_overrides_gespeichert():
    plan = build_plan(film_std(), profile_de())
    plan.set_action(2, Action.COPY)          # manuell
    job = session.serialize_plan(plan)
    # Regel-Entscheidungen tauchen NICHT als Override auf
    assert set(job["overrides"]) == {"2"}


def test_veraltete_trackids_werden_ignoriert():
    job = session.serialize_plan(configured_plan())
    job["overrides"]["99"] = "drop"          # Track existiert nicht mehr
    fresh = build_plan(film_std(), profile_de())
    session.restore_plan(fresh, job)          # darf nicht werfen
    assert 99 not in fresh.decisions


def test_defekter_eintrag_bricht_nicht():
    fresh = build_plan(film_std(), profile_de())
    session.restore_plan(fresh, {"overrides": {"x": "quatsch"}})
    # Plan bleibt nutzbar (Default-Regel)
    assert fresh.decisions[0].action is Action.COPY
