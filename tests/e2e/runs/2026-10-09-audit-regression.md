# Audit slice regression — 9 October 2026

All 103 checks below passed on the local feature branch after adding the Audit
settings slice. The protected Docker preview recovered after planned restarts
and is available at port 3001. The original Docker and kind previews returned
HTTP 200 on `/health` at ports 3000 and 13000. The live Audit run used the
signed-in admin, restored its switches and removed its temporary class and
developer. Its nine clearly named
trial records remain in the local volume, as an append-only audit should.

| Check | Cases passed | Evidence |
| --- | ---: | --- |
| Authenticated Audit page, switches, settings records, search, persistence and developer denial | 9/9 | [Audit JSON](2026-10-09-audit.json) and [plain-English cases](../audit-cases.md) |
| Fresh-store options, atomic settings records, literal search and paging | 3/3 | `python3 tests/e2e/test_audit_store.py` |
| Model approval | 10/10 | [JSON](2026-10-09-model-approval.json) |
| Data classes | 8/8 | [JSON](2026-10-09-data-classes.json) |
| Accounts and roles | 13/13 | [JSON](2026-10-09-accounts.json) |
| Live model replacement and rollback | 5/5 | [JSON](2026-10-09-model-replacement.json) |
| Model edit | 5/5 | [JSON](2026-10-09-model-edit.json) |
| Original model preview, Docker and kind | 7/7 each | `test_local.py` with ports 3000 and 13000 |
| Real Qwen, Docker and kind | 2/2 each | `test_qwen.py` with ports 3000 and 13000 |
| Guarded local endpoint | 4/4 | `test_guarded_endpoint.py` inside the app container |
| Runner discovery and registration, Docker and kind | 4/4 each | `test_runner_flow.py` with ports 3000 and 13000 |
| Two-replica kind failover and supplied-gateway path | 7/7 | `test_kind.py`; replacement gateway pod became ready |
| Stack version lock | 4/4 | `test_stack_lock.py` |
| Management-read retry | 3/3 | `test_management_retry.py` |
| Qwen context and output behavior, Docker and kind | 2/2 each | `test_model_runtime.py --docker` and `--kind` |
| Existing catalog and data-class store invariants | 1/1 each | `test_model_catalog.py`, `test_data_classes_store.py` |

The Audit run covers setting changes in the current protected preview. It does
not prove held-back-request or model-answer records, since those event sources
are not yet built. The kind checks cover its existing model stack, not a kind
deployment of the new Audit slice.
