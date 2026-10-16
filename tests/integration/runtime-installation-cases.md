# Managed runtime installer

Run `pytest tests/integration/test_runtime_installation.py`. These storage and
filesystem cases check that enrollment remains disabled during publication,
that loaded and trusted configuration match, and that current approvals,
complete definitions and shared keys are checked again before enabling.

A partial applied guard, changed model, withdrawn approval/key, unsupported
Personal or legacy model, or a repeated enrollment leaves access disabled. The
generated configuration stays available to the operator for inspection; the
service does not retry writes or roll them back automatically.

The two publication fault cases inject an error after the enabled file has been
replaced. The installer attempts to disable it. If that cleanup also fails, the
command reports that the access state is unconfirmed; the caller must stop the
gateway. These are filesystem fault injections, not observed native failures.

The unit fixture substitutes the applied-policy barrier to isolate ordering.
Actual pinned-native command acceptance separately checks the full compiled
entry/final/provider policy and protected requests. Reports stay outside Git.
