# React UI unit cases

Run `npm run test:unit` from `components/admin-ui/web/`. Vitest discovers test
files in this top-level `tests/unit/ui/` directory; component source has no
colocated tests.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| UI-01 | Open Create user, enter a too-short username and password, then submit. | Developer is selected by default, validation explains both inputs, and no request reaches the account API. |
