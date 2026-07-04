"""Regel-Engine: Automatik, Fallbacks, Warnungen, Override-Schutz."""

import pytest

from core.model import Action, Origin
from core.planner import build_plan, reapply_rules, reset_manual
from tests.helpers import film_std, media, profile_de, track


def actions(plan):
    return {tid: dec.action for tid, dec in plan.decisions.items()}


class TestStandardfall:
    def test_nur_deutsch_mit_stereo_kopie(self):
        plan = build_plan(film_std(), profile_de())
        assert actions(plan) == {
            0: Action.COPY,            # Video
            1: Action.STEREO_ADD,      # de 5.1 → Original + Stereo
            2: Action.DROP,            # en
            3: Action.DROP,            # fr Kommentar
            4: Action.COPY,            # de-Sub forced
            5: Action.DROP,            # en-Sub
        }
        assert plan.default_audio_source == 1
        assert plan.default_audio_is_stereo is True
        assert plan.warnings == []

    def test_remux_only_bei_stereo_never(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never"))
        assert plan.is_remux_only
        assert plan.decisions[1].action is Action.COPY
        assert plan.default_audio_source == 1
        assert plan.default_audio_is_stereo is False

    def test_stereo_replace(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="replace"))
        assert plan.decisions[1].action is Action.STEREO_REPLACE
        assert plan.kept_ids("audio") == []
        assert plan.default_audio_is_stereo is True

    def test_alle_sprachen_behalten(self):
        plan = build_plan(film_std(), profile_de(audio_policy="all",
                                                 drop_commentary=False))
        assert plan.decisions[2].action is Action.COPY
        assert plan.decisions[3].action is Action.COPY

    def test_stereo_nur_fuer_topsprache(self):
        # de UND en behalten → Stereo nur für die de-Spur
        plan = build_plan(film_std(), profile_de(lang_priority=["de", "en"]))
        assert plan.decisions[1].action is Action.STEREO_ADD
        assert plan.decisions[2].action is Action.COPY

    def test_ausgabepfad_aus_profil(self):
        from pathlib import Path
        plan = build_plan(film_std(), profile_de())
        assert Path(plan.output_path) == Path("C:/filme/test_remux.mkv")


class TestFallbacksUndWarnungen:
    def test_kein_deutsch_erste_spur_plus_warnung(self):
        m = media(track(0, "video"),
                  track(1, "audio", "en", channels=6),
                  track(2, "audio", "ja", channels=2))
        plan = build_plan(m, profile_de())
        assert plan.decisions[1].action in (Action.COPY, Action.STEREO_ADD)
        assert plan.decisions[2].action is Action.DROP
        assert any("Keine Audiospur" in w for w in plan.warnings)

    def test_zwei_deutsche_spuren_warnung(self):
        m = media(track(0, "video"),
                  track(1, "audio", "de", channels=6),
                  track(2, "audio", "de", channels=2))
        plan = build_plan(m, profile_de())
        assert any("2 Audiospuren" in w for w in plan.warnings)

    def test_und_spur_wird_behalten_mit_warnung(self):
        m = media(track(0, "video"), track(1, "audio", "und", channels=2))
        plan = build_plan(m, profile_de())
        assert plan.decisions[1].action is Action.COPY
        assert any("Sprachkennung" in w for w in plan.warnings)

    def test_und_drop_greift_nicht_wenn_einzige_spur(self):
        m = media(track(0, "video"), track(1, "audio", "und", channels=2))
        plan = build_plan(m, profile_de(und_audio="drop"))
        # Fallback: nie eine tonlose Datei bauen
        assert plan.decisions[1].action is Action.COPY
        assert any("Keine Audiospur" in w for w in plan.warnings)

    def test_kommentarspur_heuristik(self):
        m = media(track(0, "video"),
                  track(1, "audio", "de", channels=6),
                  track(2, "audio", "de", channels=2,
                        name="Director's Commentary"))
        plan = build_plan(m, profile_de())
        assert plan.decisions[2].action is Action.DROP
        # nur 1 behaltene de-Spur → keine Abweichler-Warnung
        assert plan.warnings == []


class TestUntertitel:
    def test_forced_only(self):
        plan = build_plan(film_std(), profile_de(sub_policy="forced_only"))
        assert plan.decisions[4].action is Action.COPY
        assert plan.decisions[5].action is Action.DROP

    def test_none_aber_forced_bleibt(self):
        plan = build_plan(film_std(), profile_de(sub_policy="none"))
        assert plan.decisions[4].action is Action.COPY   # forced de
        assert plan.decisions[5].action is Action.DROP

    def test_none_ohne_forced_schutz(self):
        plan = build_plan(film_std(), profile_de(sub_policy="none",
                                                 keep_forced_subs=False))
        assert plan.decisions[4].action is Action.DROP


class TestOverrides:
    def test_reapply_schuetzt_manuelles(self):
        plan = build_plan(film_std(), profile_de())
        plan.set_action(2, Action.COPY)                  # en manuell behalten
        reapply_rules(plan, profile_de())
        assert plan.decisions[2].action is Action.COPY
        assert plan.decisions[2].origin is Origin.MANUAL
        assert plan.decisions[1].action is Action.STEREO_ADD

    def test_reset_manual_verwirft_overrides(self):
        plan = build_plan(film_std(), profile_de())
        plan.set_action(2, Action.COPY)
        reset_manual(plan, profile_de())
        assert plan.decisions[2].action is Action.DROP
        assert plan.decisions[2].origin is Origin.RULE

    def test_stereo_auf_video_verboten(self):
        plan = build_plan(film_std(), profile_de())
        with pytest.raises(ValueError):
            plan.set_action(0, Action.STEREO_ADD)

    def test_default_wandert_bei_abwahl(self):
        plan = build_plan(film_std(), profile_de(stereo_policy="never",
                                                 lang_priority=["de", "en"]))
        assert plan.default_audio_source == 1
        plan.set_action(1, Action.DROP)                  # Default-Spur abwählen
        assert plan.default_audio_source == 2            # wandert zur en-Spur
        assert plan.default_audio_is_stereo is False

    def test_stereo_make_default_false(self):
        plan = build_plan(film_std(), profile_de(stereo_make_default=False))
        assert plan.default_audio_source == 1
        assert plan.default_audio_is_stereo is False
