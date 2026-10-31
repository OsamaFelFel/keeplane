"""Complexity levels: Keeplane's automatic pick and an admin's change.

Spec 004 ST13 and D104, with the owner's level decision for this release:
three levels, Simple, Standard and Complex. Keeplane ranks the models that are
set up by context window, smallest first, then by model ID. Simple gets the
first, Complex the last and Standard the middle one. A model whose context
window Keeplane was not told ranks below every model with a known one.

Keeplane's picks are worked out again on every read, so they follow models as
they are added, set up or removed. An admin's change is stored and always wins
while its model is set up. Nothing here judges a task's complexity or routes a
task to a level.
"""

from .models import ComplexityLevel

LEVELS = tuple((level.value, level.label) for level in ComplexityLevel)
LEVEL_NAMES = dict(LEVELS)
KEEPLANE_PICK = "Keeplane's pick"


class LevelError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class ModelInUse(Exception):
    """Routing still uses a model, so it can't be removed."""

    def __init__(self, model_id, levels):
        super().__init__(model_id)
        self.model_id, self.levels = model_id, list(levels)

    def body(self):
        return {
            "error": f"{self.model_id} is still in use. "
            "Move these to another model first, then remove it.",
            "in_use": {"levels": self.levels, "persona_rules": []},
        }


def ranked(context_windows):
    """Order set-up models smallest context first, then by model ID."""
    return sorted(
        context_windows,
        key=lambda model_id: (context_windows[model_id] or 0, model_id),
    )


def automatic_picks(context_windows):
    """Map each level to Keeplane's pick from {model ID: context tokens or None}."""
    order = ranked(context_windows)
    if not order:
        return dict.fromkeys(LEVEL_NAMES)
    return {
        "simple": order[0],
        "standard": order[(len(order) - 1) // 2],
        "complex": order[-1],
    }


def level_rows(context_windows, admin_choices):
    """Describe each level for Models and routing.

    context_windows holds only models that are set up now. An admin's pick
    whose model is not set up now stays recorded, but the level uses
    Keeplane's pick until that model is set up again.
    """
    picks = automatic_picks(context_windows)
    rows = []
    for level, name in LEVELS:
        chosen = admin_choices.get(level)
        available = chosen is not None and chosen in context_windows
        rows.append(
            {
                "level": level,
                "name": name,
                "model_id": chosen if available else picks[level],
                "keeplane_pick": picks[level],
                "changed_by_admin": chosen is not None,
                "admin_model_id": chosen,
                "admin_model_set_up": available if chosen is not None else None,
            }
        )
    return rows


def complexity_levels(catalog, set_up_model_ids):
    """Read the stored choices and context windows, then describe each level."""
    return level_rows(
        catalog.context_windows(set_up_model_ids), catalog.level_choices()
    )


def describe_level_change(level, previous, chosen):
    """Say what an admin changed for one level, for the settings record."""
    before = f"model {previous}" if previous else KEEPLANE_PICK
    after = f"model {chosen}" if chosen else KEEPLANE_PICK
    return f"Changed complexity pick {LEVEL_NAMES[level]}: {before} to {after}"
