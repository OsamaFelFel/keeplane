# Persona rules

A persona rule sends one persona's work to a model you choose, for example
every task the **Architect** works on goes to your strongest model. Open
**Models and routing** as an admin; the **Persona rules** table lists each rule
as **Persona is [persona]** and the model it routes to.

The personas are the predefined ones an agent starts from: **Architect**,
**Developer** and **Frontend**. Each persona has at most one rule.

## Add a rule

1. Choose **Add rule**. It is available once at least one model is set up.
2. In **When the persona is**, choose the persona.
3. In **Route to**, choose a model. Only models that are set up are offered;
   a model added outside Keeplane can't be chosen until you set it up.
4. Choose **Add rule**. The rule shows under **Persona rules**.

If the persona already has a rule, the dialog says which model it uses now, and
adding the new rule replaces it.

If a rule's model stops being set up, for example because its gateway
definition changed outside Keeplane, the row says the rule sends no work. The
rule is kept and applies again once the model is set up again.

## Which model a task goes to

Inside what the developer's project allows, Keeplane decides in this order:

1. **The developer's switch.** A model the developer switched to always wins
   over persona rules and Keeplane's picks. A switch to a model the project
   doesn't allow is refused.
2. **The persona rule** for the persona working on the task.
3. **The complexity level's model** (see [complexity levels](complexity-levels.md)).
   An admin's level change wins while the project may use that model;
   otherwise Keeplane picks among the models the project may use.
4. **The first allowed model**, by model ID.

Each step only counts when its model is allowed for the task: set up in
Keeplane, approved for the project's data class when classes are on, and with a
usable key. If a rule's model is not allowed, for example because the project
is Confidential and the model is approved only for Public, the next step
decides. No task ever goes to a model that is only in the gateway.

When the developer's own key for the model they switched to is missing, refused
or out of date, the task moves to another allowed model in the same order, and
the answer says why.

Keeplane judging a task's complexity is still being built, and the CLI does not
send a task's persona or level yet: new Developer CLI work waits for its spec.
Today the order above is answered by the developer runtime API
`GET /api/runtime/projects/<project>/task-model`, which takes an optional
`model_id` (the developer's switch), `persona` and `level`, and returns the
model, which step chose it (`developer`, `persona_rule`, `complexity_level` or
`first_allowed`) and, when the developer's own key was the problem, why. The
gateway still checks every request itself.

## Removing a model a rule uses

A model that a persona rule uses can't be removed. **Remove model** (or
**Remove Keeplane setup**) shows **[model] is still in use** and lists
**Persona rule: [persona]** alongside any complexity levels. Add a rule for
that persona with another model first, then remove it. Nothing is sent to the
gateway while the model is in use.

## Audit

While **Changes to models, routing and data classes** is on in
[Audit](audit-local.md), each change adds one record:
`Added persona rule Architect: route to model alpha`,
`Changed persona rule Architect: model alpha to model beta` or
`Removed persona rule Architect: it routed to model beta`. Adding the same rule
again adds nothing.

## Checks

The plain-English cases are in [the unit cases](../../tests/unit/persona-rule-cases.md),
[the admin cases](../../tests/integration/persona-rule-cases.md) and
[the routing cases](../../tests/integration/task-routing-cases.md):

```sh
.venv/bin/python -m pytest tests/unit/test_persona_rules.py tests/integration/test_persona_rules.py tests/integration/test_task_routing.py
npm --prefix components/admin-ui run test:unit
```

How rules are stored and applied is in the
[routing architecture note](../architecture/task-routing.md).
