# Known failing tests (2026-10-06)

Run: `python -m unittest discover -s . -p "test_*.py"` inside `core/` on an H: drive path. 616 tests, 605 pass, 2 skipped, 9 fail.

| Tests | Count | Cause |
|---|---|---|
| `test_marvin_training.test_active_marvin_identity_*` and `test_model_router_lifecycle.test_memory_failure_*` | 2 | Stale assertions. The code now says MARVIN everywhere after the JARVIS to MARVIN recode, and these tests still check the old expectation. Fix the tests, not the code. |
| `test_workflow_execution` (5 tests) | 5 | They read the private workflow card catalog under `data/`, which is not published. They need that catalog or fixtures built from it. |
| `test_start_storage` (2 tests) | 2 | They check the live start script against the real cache layout on the owner's machine. |

Left out of this copy on purpose: the `data/` folder, the third-party `library/` skills, the vendored three.js, and 3 test files that contain token-like strings. Those 3 tests are not part of the 616.
