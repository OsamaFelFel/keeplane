# Try data classes in the protected local preview

Start the [account preview](accounts-local.md), sign in at
[Data classes](http://127.0.0.1:3000/data-classes), and open **Add class**. A new
installation starts with Public, Internal and Confidential. You can add a
class, rename it, and choose from models already set up in Keeplane. **Edit**
also changes the model list. Removing a class asks for confirmation because
its model approvals will change; if it was a model's only approved class, that
model needs setup again. A class assigned to a project cannot be removed.

The local preview stores classes and model approvals in the same persistent
Docker volume. Restarting the protected app keeps both. The Models and routing
setup dialog reads the current class list, including classes you add or rename.
The class list counts only models whose current gateway definition still
matches their Keeplane approval. When a gateway model changes, it disappears
from the effective class list until an admin sets it up again; the admin cannot
add that stale model to another class.

Run the [plain-English cases](../../tests/e2e/data-classes-cases.md):

```sh
python3 tests/e2e/test_data_classes.py
python3 tests/e2e/test_data_classes_store.py
```

The live suite records [HTTP evidence](../../tests/e2e/runs/2026-10-09-data-classes.json).
It creates and removes one trial class and one trial approval. It requires the
`local-fixture` model to be present and unapproved before it starts, so it
will refuse to overwrite your own approval. The isolated database suite checks
the project-in-use rule; there is no Projects UI or API yet.

This is the starter-class part of Spec 005. Project class assignment, routing
enforcement and personal-data detection remain to be built and tested. The
Docker model preview at port 3000 uses this same protected account session.
