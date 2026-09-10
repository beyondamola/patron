# Reliability roadmap execution

The attached roadmap and LONG_TERM_PLAN.md remain the acceptance contract.
No gate is complete solely because its local tests pass.

## Gates

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| G0 | Verified | Unit baseline: 56 passed, 8 skipped. Real Docker suite: 8 passed, 56 deselected, 48.71 seconds. Normal CLI baseline: all eight PASSED; no simulation containers/networks remained. Checkpoint 8b1ca31. |
| G1 | In progress | Private repository created; pinned image/dependency implementation, strict report validation, cleanup and Actions workflow added. Actual workflow results pending. |
| G2 | Not started | Operator state/control implementation and verification pending. |
| G3 | Not started | Sustained detection and false-positive corpus pending. |
| G4 | Not started | Capture/replay and fake shadow comparison pending. |
| G5 | Not started | Full qualification pending. |

## Baseline environment

- Local host: macOS arm64; Docker Desktop 4.76.0, engine 29.5.2 linux/arm64.
- Existing Python: 3.9.6; pytest 8.4.2.
- Commands: `python3 -m pytest -q -p no:cacheprovider` and
  `PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest -m integration -q -p no:cacheprovider`.
- Git was not initialized when work began. The user authorized choosing or creating
  a repository; use a private repository in the authenticated beyondamola account.
- Logs and virtualenvs must not be published. Preserve local historical evidence.

## Decisions

- CI provider: GitHub Actions; repository: https://github.com/beyondamola/patron (private).
- Use actual existing image index digests, verified with Docker registry manifest
  inspection, instead of upgrading images during the reliability pass.
- Future event envelope: schema version, event/run/incident IDs, resource name and
  container ID, UTC timestamp and monotonic offset, configuration fingerprint.
  Implement fields at the relevant gate, not a premature cross-project rewrite.
- Future resource identity: container ID plus display name; legacy unknown identity
  must retain suppression until explicit operator action.

## Requirement traceability

| Requirement | Current evidence | Status |
| --- | --- | --- |
| G0 baseline unit tests | 56 passed; 8 explicitly opt-in skipped | Verified locally |
| G0 baseline real scenarios | 8 passed in actual Docker suite | Verified locally |
| CI-1 immutable multiarch images | scenarios/images.py; both index manifests include Linux amd64/arm64; fresh Python 3.9 virtualenv dependency install succeeded | Local implementation verified; execution with pins pending |
| CI-2 actual Linux CI | No workflow run yet | Missing |
| OPS-1 through OPS-4 | Existing state implementation inspected | Pending |
| DET-1 through DET-5 | Current single-sample behavior documented | Pending |
| REP-1 through REP-7 | Current audit lacks full observation stream | Pending |

This record will be updated with test names, commit IDs, CI run URLs, and artifact
locations as implementation advances. Historical VERIFICATION.md is not rewritten.

## G1 implementation checks

- `python3 -m pytest -q -p no:cacheprovider`: 65 passed, 8 skipped.
- `tests/test_ci.py`: rejects failed/skipped/missing reports, tests exact cleanup
  filters plus ownership reinspection, requires immutable digests, tests redaction.
- Unit autouse fixture blocks real subprocess and socket connections.
- Integration fixture avoids Docker calls during test collection. Strict CI mode
  fails rather than skips when Docker or opt-in configuration is unavailable.
- Pinned GitHub action commits were resolved through the GitHub API, not guessed.
- Approval-service interruption delayed external checks; access subsequently
  resumed. No workaround was used to bypass the rejected operation.
