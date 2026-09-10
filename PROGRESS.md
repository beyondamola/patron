# Reliability roadmap execution

The attached roadmap and LONG_TERM_PLAN.md remain the acceptance contract.
No gate is complete solely because its local tests pass.

## Gates

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| G0 | Verified | Unit baseline: 56 passed, 8 skipped. Real Docker suite: 8 passed, 56 deselected, 48.71 seconds. Normal CLI baseline: all eight PASSED; no simulation containers/networks remained. Checkpoint 8b1ca31. |
| G1 | Verified | Commit 557f88f passed three independent full workflows on Linux amd64/arm64. See G1_VERIFICATION.md. |
| G2 | In progress | Generation-scoped state, operator inbox/CLI, live/offline real-process test implemented. Full regression/CI qualification in progress. |
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
| CI-1 immutable multiarch images | scenarios/images.py; manifests and actual Linux amd64/arm64 execution; fresh virtualenv install | Verified |
| CI-2 actual Linux CI | Runs 34498811932, 34499033848, 34499045400 succeeded independently at 557f88f | Verified |
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
- Pinned local Docker suite: 8 passed, 65 deselected, 51.56 seconds. Strict report
  validation and run-scoped cleanup completed successfully.
- First actual CI run: https://github.com/beyondamola/patron/actions/runs/34498459240
  failed because the cleanup validator rejected periods in the workflow run ID.
  Both Linux amd64/arm64 scenario suites passed; this is still a failed workflow.
  Added an exact-format regression test, fixed validation, and retained the failure.
- Persisted normalized pre/post/final Docker state artifacts and moved final
  scenario narration after result persistence. Added tests for evidence and
  result-write failure. Updated action pins after actual Node deprecation warnings.
- Final G1 unit suite: 70 passed, 8 skipped. Normal CLI run-all: all eight PASSED.
- Strict missing-Docker experiment: 8 setup errors, exit 1, zero skips as required.
- Three independent full CI successes: 34498811932, 34499033848, 34499045400.
  All use commit 557f88f; the latter two were separate dispatches, not retries.
- Downloaded successful run artifacts under artifacts/ci-qualification-1 and
  validated both eight-case XML reports, 16 correct results, and 48 state packets.
- Local post-run checks found no simulation containers/networks or remaining
  Python harness/scenario processes. No unrelated resources were removed.

## Next gate

G2 implementation is next: versioned incident state and container identity,
single-writer ownership, atomic operator request inbox, live/offline CLI, and
crash-consistent request/audit delivery. Existing resolved incidents are removed
from active state, so list/show must combine state with audit history. Acknowledge
must not change status or retries; rearm must preserve the old terminal incident
and create a linked new incident only if a later collection still detects failure.

## G2 storage foundation

- Added harness/storage.py: same-directory temporary files, fsync before atomic
  replacement, directory fsync, kernel flock ownership with nested same-owner
  support. Stale lock-file contents do not represent ownership.
- Registry writes schema_version=1 with monotonic revisions. Legacy files are
  backed up byte-for-byte to .v0.bak only on the first write. Reading is not migration.
- Unknown schemas, malformed state, stale writers, and conflicting backups fail
  closed without deleting state. Terminal suppression survives migration.
- run/watch acquire ownership before collection; watch retains it until shutdown.
  A second runtime cannot inspect or execute through this state path.
- Explicit --state-path now takes precedence over PATRON_STATE_PATH and defaults.
- Added incident container_id/predecessor_id/acknowledgment fields as optional
  backward-compatible data fields; generation-aware operator behavior is pending.
- tests/test_storage.py covers ownership, stale lock files, atomic replacement
  failure, fsync failure, backup preservation, schema rejection, path precedence,
  and rejection before collection. Full G2 is not claimed complete.
- Verification: 85 unit tests passed, 8 integration tests skipped by default.
  Live Docker regression suite: 8 passed in 52.83 seconds (82 unit tests deselected
  at invocation). Evidence: artifacts/raw/g2-storage.xml. Run-scoped cleanup passed.

## G2 operator control implementation

- Added harness/control.py and incidents list/show/acknowledge/rearm CLI commands.
  Live requests queue atomically; offline requests use the same mutation code.
  Request IDs, expected revisions, actor/reason, dry-run, and bounded waits are supported.
- Acknowledge changes metadata only. Rearm retains terminal history and links the
  next incident, without directly executing Docker actions. Healthy cycles do nothing.
- State contains applied results plus a pending audit outbox. Pending audit never
  returns success. Recovery tests cover failure before logging and after audit fsync;
  stable event IDs prevent duplicate delivery after restart.
- Current result cache is bounded to 256 entries; older results remain queryable
  from audit events. Completed inbox files are removed only after durable delivery.
- Runtime audit snapshots include full incident metadata and state-path provenance.
  Operator readers merge active state with scoped audit history, including resolved
  incidents. Legacy unscoped records are restricted to known resources for custom state.
- Audit appends now hold a file lock and fail closed on incomplete final records.
- Unit suite: 100 passed, 8 opt-in skipped. Real Docker regression: 8 passed in
  59.91 seconds (94 unit cases deselected at invocation), artifacts/raw/g2-control.xml.
- Still required before G2 completion: generation-aware suppression/rearm review,
  real live/offline process workflows, broader concurrent request/crash tests,
  state control-envelope validation, docs review, and full G2 CI qualification.

## G2 qualification follow-up

- Added observed/resolved generation identity, generation-scoped cooldown, and
  replacement handling. Unknown legacy identity retains conservative suppression.
- Fixed live dry-run requiring a writer lock and duplicate pending submission
  comparing regenerated timestamps instead of immutable operator intent.
- Validated durable request/result and audit-outbox envelopes on load; malformed
  control state fails closed. process_pending/flush hold state ownership explicitly.
- Unit suite reached 110 passed, 9 integration cases skipped by default.
- Real operator process test passed locally in 9.44 seconds: live acknowledgment,
  live rearm, offline rearm, linked incidents, duplicate request result, writer
  exclusion, graceful shutdown, and owned container cleanup. Concurrent CLI
  submissions were subsequently added and remain to be run with final qualification.
- CI now runs a separate exact-case operator report alongside the unchanged
  eight-scenario integration report; unit lanes deselect both integration markers.
