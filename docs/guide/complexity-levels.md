# Complexity levels

Keeplane has three complexity levels: **Simple**, **Standard** and
**Complex**. Each level has one model. Open **Models and routing** as an admin;
the **Complexity** table under Models shows each level's model and whether it
is **Keeplane's pick** or **changed by an admin**.

Keeplane judging a task's complexity is still being built, so the CLI does not
send a task's level yet. When a level is named, a
[persona rule](persona-rules.md) for the task's persona and the developer's own
switch both come before the level's model; the order is in
[Persona rules](persona-rules.md#which-model-a-task-goes-to).

## Keeplane's pick

As soon as one model is set up, every level has a model. Keeplane ranks the
models that are set up by context window, smallest first:

- **Simple** gets the model with the smallest context window.
- **Complex** gets the model with the largest context window.
- **Standard** gets the middle one. With an even number of models it takes the
  smaller of the two middle models, so with two models Simple and Standard
  share the smaller one.
- Models with the same context window are ordered by model ID.

Keeplane knows a model's context window when it is added from a local runner
that serves that one model and reports its context, the same value Add model
shows as **Active context**. Keeplane is not told the context window of cloud
models or of models added outside Keeplane; these rank below every model with
a known context window. There is no field to enter it. Change a level when
Keeplane's pick does not suit you.

Keeplane's picks follow the models: adding, setting up or removing a model
works the picks out again. A model added outside Keeplane is never picked until
an admin sets it up, and a model whose gateway definition changed is not picked
until it is set up again.

## Change a level

1. Choose **Change** on the level's row.
2. In **Model for [level]**, choose a model and **Save**. Only models that are
   set up are offered. The dialog also names Keeplane's current pick.
3. To give the level back to Keeplane, choose **Use Keeplane's pick**.

An admin's choice always wins over Keeplane's pick and does not move when
models are added or removed. If its model stops being set up, for example
because its gateway definition changed, the row says so and Keeplane's pick is
shown until the model is set up again. Admin choices apply to the whole
organization; a project with a data class only uses models approved for its
class, so when the admin's model isn't allowed there, the level uses Keeplane's
pick among the models that project may use.

## Removing a model a level uses

A model that an admin chose for a level, or that a persona rule uses, can't be
removed. **Remove model** (or **Remove Keeplane setup**) shows **[model] is
still in use** and lists the levels and persona rules. Change those levels to another model or back to Keeplane's pick first,
then remove it. Nothing is sent to the gateway while the model is in use.

A model that is only Keeplane's pick for a level can be removed; Keeplane picks
another model for that level.

## Audit

While **Changes to models, routing and data classes** is on in
[Audit](audit-local.md), each change adds one record, for example
`Changed complexity pick Complex: Keeplane's pick to model alpha` or
`Changed complexity pick Complex: model alpha to Keeplane's pick`. Saving the
same choice again adds nothing. Keeplane's own picks moving after a model
change are not admin changes and are not recorded.

## Checks

The [plain-English cases](../../tests/integration/complexity-level-cases.md)
list the unit, integration, React and browser checks:

```sh
.venv/bin/python -m pytest tests/unit/test_complexity_levels.py tests/integration/test_complexity_levels.py tests/unit/test_model_removal.py
npm --prefix components/admin-ui run test:unit
```

How the picks are stored is described in the
[architecture note](../architecture/complexity-levels.md).
