# Best code ranking (2026-10-06)

Method: static scan of every code root on H: that was reachable. Score = functions and classes + 3 per test function - 5 per stub file - 2 per file that does not parse. Tests were run only for the first row. F: copies are not ranked yet because they have not landed on H:.

| Rank | Root | Files | Lines | Functions | Tests | Stub files | Unparseable | Run result |
|---|---|---|---|---|---|---|---|---|
| 1 | Enterprise Source (preserved V1 core and V4 core copies) | 173 | 36943 | 2886 | 663 | 2 | 0 | not run |
| 2 | V1 app (marvin_brain, nexen_decide, memory, vault tools) | 160 | 33374 | 2558 | 606 | 2 | 14 | not run |
| 3 | NEXEN application (this repo, `nexen/`) | 81 | 13410 | 931 | 180 | 8 | 0 | 173 of 173 pass |
| 4 | integrations | 36 | 6235 | 464 | 180 | 0 | 1 | not run |
| 5 | Business Operations | 26 | 7153 | 478 | 95 | 0 | 0 | not run |
| 6 | marvin | 32 | 5091 | 363 | 111 | 0 | 3 | not run |
| 7 | loop | 18 | 4450 | 290 | 81 | 0 | 0 | not run |
| 8 | tools | 40 | 5669 | 243 | 46 | 0 | 1 | not run |
| 9 | clipping (baseline clipper, default engine) | 14 | 2350 | 134 | 36 | 1 | 0 | not run |
| 10 | apps (75 script shortcuts) | 126 | 5851 | 230 | 10 | 26 | 3 | stubs |

## What is in this repo and why
- `nexen/`: rank 3. The only root whose full test suite was run and passes.
- `modules/`: 15 modules with real function or class logic, picked from rank 10. Run through the approval-gated bridge. Several only print fixed text, so a clean run does not prove they do real work.
- Not included yet: ranks 1, 2 and 4 to 9. They are larger and unrun here, so they need their own test pass and a privacy scrub before publishing.

## Not yet done
- Rank the F: NEXEN version folders after they land on H:.
- Run the test suites of ranks 1, 2, 4 to 9 and promote what passes.
- Pull code out of the chat archives once the export folders are named.

## F: versions graded so far (2026-10-06)
Only 3 of the 11 F: version folders in `f-size-report.txt` have reached H: so far.

| Version | Files | Functions | Tests | Score | Files not in current core | Files that differ |
|---|---|---|---|---|---|---|
| H: V1 app (current core) | 160 | 2558 | 606 | 4338 | n/a | n/a |
| F NEXEN_Autonomy_v0.1 (snapshot copy) | 101 | 1616 | 389 | 2749 | 0 | 12 |
| F NEXEN_Autonomy_v0.1 (F mirror, 2026-09-26) | 107 | 1594 | 389 | 2727 | 0 | 11 |
| F NEXEN_THIS_PC_ONLY_v4 | 0 | 0 | 0 | 0 | 0 | 0 |

Verdict: the current H: core already contains every Python file from both Autonomy copies and has 217 more tests. `NEXEN_THIS_PC_ONLY_v4` holds no Python. Nothing from these three is added to the build.
Not yet landed on H: `NEXEN_CORE_20260907`, `NEXEN_REINSTALL`, `NEXEN_MASTER`, `NEXEN_AUTONOMY`, `NEXEN_REV2`, `NEXEN_GAME`, `NEXEN_REALITY_COMPILER_V1`, `NEXEN master plan`, `NEXEN 1.1.2`.
