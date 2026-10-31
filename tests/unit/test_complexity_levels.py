"""Keeplane's automatic complexity picks and how admin changes are shown.

Spec 004 ST13 and D104. The plain-English cases are in
complexity-level-cases.md.
"""

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "components/control-plane")
)

from model_registry.levels import (
    LEVELS,
    ModelInUse,
    automatic_picks,
    describe_level_change,
    level_rows,
)


def picks(windows):
    result = automatic_picks(windows)
    return result["simple"], result["standard"], result["complex"]


def test_cl_01_three_levels_in_order():
    assert LEVELS == (
        ("simple", "Simple"),
        ("standard", "Standard"),
        ("complex", "Complex"),
    )


def test_cl_02_no_set_up_model_means_no_pick():
    assert automatic_picks({}) == {"simple": None, "standard": None, "complex": None}


def test_cl_03_smallest_middle_and_largest_context():
    windows = {"large": 128000, "small": 8192, "medium": 32768}
    assert picks(windows) == ("small", "medium", "large")


def test_cl_04_one_model_takes_every_level():
    assert picks({"only": 4096}) == ("only", "only", "only")


def test_cl_05_two_models_standard_takes_the_smaller():
    assert picks({"b-large": 200000, "a-small": 4096}) == (
        "a-small",
        "a-small",
        "b-large",
    )


def test_cl_06_even_count_standard_takes_the_lower_middle():
    windows = {"m1": 1000, "m2": 2000, "m3": 3000, "m4": 4000}
    assert picks(windows) == ("m1", "m2", "m4")


def test_cl_07_ties_are_broken_by_model_id():
    windows = {"charlie": 8192, "alpha": 8192, "bravo": 8192}
    assert picks(windows) == ("alpha", "bravo", "charlie")
    # The order the models arrive in never changes the picks.
    assert picks(dict(reversed(list(windows.items())))) == (
        "alpha",
        "bravo",
        "charlie",
    )


def test_cl_08_unknown_context_ranks_below_every_known_one():
    windows = {"cloud-a": None, "local-small": 2048, "cloud-b": None}
    assert picks(windows) == ("cloud-a", "cloud-b", "local-small")


def test_cl_09_admin_change_wins_and_keeps_keeplanes_pick_visible():
    windows = {"small": 1000, "large": 9000}
    rows = {row["level"]: row for row in level_rows(windows, {"complex": "small"})}
    assert rows["complex"] == {
        "level": "complex",
        "name": "Complex",
        "model_id": "small",
        "keeplane_pick": "large",
        "changed_by_admin": True,
        "admin_model_id": "small",
        "admin_model_set_up": True,
    }
    assert rows["simple"] == {
        "level": "simple",
        "name": "Simple",
        "model_id": "small",
        "keeplane_pick": "small",
        "changed_by_admin": False,
        "admin_model_id": None,
        "admin_model_set_up": None,
    }


def test_cl_10_admin_model_not_set_up_now_uses_keeplanes_pick_but_stays_recorded():
    rows = level_rows({"local": 4096}, {"standard": "gone"})
    standard = rows[1]
    assert standard["model_id"] == "local"
    assert standard["changed_by_admin"] is True
    assert standard["admin_model_id"] == "gone"
    assert standard["admin_model_set_up"] is False


def test_cl_11_settings_record_wording():
    assert (
        describe_level_change("complex", None, "large")
        == "Changed complexity pick Complex: Keeplane's pick to model large"
    )
    assert (
        describe_level_change("simple", "a", "b")
        == "Changed complexity pick Simple: model a to model b"
    )
    assert (
        describe_level_change("standard", "a", None)
        == "Changed complexity pick Standard: model a to Keeplane's pick"
    )


def test_cl_12_in_use_answer_lists_levels_and_no_persona_rules_yet():
    assert ModelInUse("m", ["Complex"]).body() == {
        "error": "m is still in use. Move these to another model first, then remove it.",
        "in_use": {"levels": ["Complex"], "persona_rules": []},
    }
