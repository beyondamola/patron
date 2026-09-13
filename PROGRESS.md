# Reliability roadmap execution

The attached roadmap and LONG_TERM_PLAN.md remain the acceptance contract.
No gate is complete solely because its local tests pass.

## Gates

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| G0 | Verified | Unit baseline: 56 passed, 8 skipped. Real Docker suite: 8 passed, 56 deselected, 48.71 seconds. Normal CLI baseline: all eight PASSED; no simulation containers/networks remained. Checkpoint 8b1ca31. |
| G1 | Verified | Commit 557f88f passed three independent full workflows on Linux amd64/arm64. See G1_VERIFICATION.md. |
| G2 | Verified | Commit 6f0498c passed Linux amd64/arm64 CI including real operator processes; local 115 unit tests and eight scenarios passed. See G2_VERIFICATION.md. |
| G3 | Verified | Sustained detection, 26-case/53-sample corpus, all-eight local/CI scenarios; see G3_VERIFICATION.md. |
| G4 | Verified | Capture/replay, historical controls, 33-fixture corpus, honest comparison/fake shadow and provenance; final code c1cc647 passes local and Linux CI. See G4_VERIFICATION.md. |
| G5 | Verified | c1cc647: 304 unit tests, nine local Docker/operator cases, all-eight normal CLI, Linux amd64/arm64 CI and repeated offline replay. See G5_VERIFICATION.md for full evidence, limits, and handoff. |

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
| OPS-1 through OPS-4 | State/control tests, real operator workflow, CI 34536159885, G2_VERIFICATION.md | Verified |
| DET-1 through DET-5 | G3_VERIFICATION.md maps config, sustained windows, unknowns, specific evidence, priority, and live scenarios | Verified |
| REP-1/REP-2 | capture.py, capture_validation.py, runtime.py; test_capture.py, test_capture_validation.py, all-eight live capture | Verified; G4_VERIFICATION.md |
| REP-3/REP-4 | replay.py, comparison.py; test_replay.py, test_comparison.py; three identical replays per fixture under no-I/O guards | Verified; G4_VERIFICATION.md |
| REP-5 | replay_metrics.py, replay_provenance.py, main.py; test_replay_reports.py, test_replay_provenance.py | Local tests and retained real captures verified |
| REP-6 | tests/fixtures/replay/manifest.json; test_replay_corpus.py; 33 captures, three runs each | Verified |
| REP-7 | shadow.py, test_shadow.py, SHADOW_EVALUATION.md | Fake-only boundary verified; no provider calls |

The entries below are historical checkpoints; later qualification supersedes
their pending statuses without erasing their failures. See G5_VERIFICATION.md
for final acceptance. Historical VERIFICATION.md is not rewritten.

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

## G2 failures discovered by qualification

- Real concurrent CLI submissions failed because the shared nonblocking queue
  lock rejected one producer. Diagnostic stderr identified queue.lock, not the
  runtime state lock. Replaced queue locking with atomic no-overwrite hard-link
  publication of individually fsynced request files. Sixteen concurrent producer
  tests and duplicate-ID publication tests pass; real concurrent workflow passed
  in 11.54 seconds. Commit a230518.
- CI runs 34535483959 and 34535690136 failed operator qualification. Their normal
  eight-scenario suites passed, but retained logs exposed a separate OOM race:
  generic STOPPED was observed and restarted before OOMKilled became visible;
  resource-only cooldown then suppressed the later OOM classification.
- Added terminal-state refresh by immutable container ID after enrichment and
  incident-type-scoped resolved cooldown. The test still requires every OOM
  operator incident to be ESCALATED, so a hidden restart cannot make it pass.
  Commit 6f0498c. Current unit suite: 115 passed, 9 opt-in skipped. Real operator
  workflow: 1 passed in 11.85 seconds, artifacts/raw/g2-oom-refresh.xml.
- Normal CLI run-all before the OOM refresh: all eight PASSED. Final refresh CI
  run 34536159885 remains in progress; G2 is not yet marked complete.
- Failed-run artifacts were retained under artifacts/g2-failed-amd64; no failures
  were replaced with automatic retries or lower thresholds.
- Final G2 CI: https://github.com/beyondamola/patron/actions/runs/34536159885
  succeeded on commit 6f0498c. Downloaded artifacts/g2-qualified and validated
  both exact eight-case reports plus both exact operator-process reports.
- Final local refreshed suite: 8 passed in 51.53 seconds; no simulation containers,
  networks, or remaining Python Patron processes were found afterward.
- G2 is verified. G3 sustained detection/configuration/negative corpus is next;
  G4 replay and G5 final qualification remain unimplemented.

## G3 implementation checkpoint (2026-09-11)

- DET-1/2/3/5 partial: added validated DetectorConfig, stable fingerprint, CLI
  --config for run/watch/inspect and scenario run/run-all, managed child config
  files, audit/result settings, and explicit registry priority/selection traces.
- CPU now requires >=3 high samples spanning >=10 seconds; maximum gap is 15
  seconds. Recovery evidence requires >=2 readings <=60 spanning >=5 seconds.
  Tests cover missing/nonfinite values, bursts, duplicate/out-of-order/stale
  timestamps, gaps, counter resets, container replacement, and fresh runtime
  windows. Hysteresis does not modify terminal incident suppression.
- All registered triggers evaluate each observation even when a higher-priority
  predicate wins, so stateful windows do not freeze behind another predicate.
- Poll intervals at or above the maximum sample gap are rejected before watch.
  Collection time also counts toward the gap; slow probes break windows rather
  than manufacturing continuous evidence.
- Unit command: python3 -m pytest -q -> 149 passed, 9 opt-in skipped, 0.88s.
- Real Docker command: PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest
  -m integration -k high_cpu -q --junitxml=artifacts/raw/g3-cpu-initial.xml
  -> 1 passed, 157 deselected, 21.14s. Test asserts classification, escalation,
  policy, shutdown, and scenario-owned resource cleanup. This is a focused live
  result, not full G3 qualification or a new CI result.
- Remaining G3: timestamp/start-bounded logs, dependency/probe unknown semantics,
  quota reporting, labeled corpus with denominators, full eight-scenario and
  operator regression runs, normal run-all, and Linux CI evidence.

## G3 evidence-quality checkpoint (2026-09-11)

- DET-4: Docker logs are timestamped, restricted to the current StartedAt and a
  configurable 60-second TTL, independently filtered, sorted, and bounded to
  twenty 1000-character messages. Unknown starts yield unknown log evidence.
  Added Python 3.9 normalization for Docker nanosecond timestamps after a unit
  test exposed the incompatibility; undated stderr is not accepted as evidence.
- Failed or malformed dependency inspect now returns unknown, not down/missing.
  Down requires a typed Running=false observation, or separately collected
  recent dependency-error logs. CPU/disk malformed and nonfinite metrics stay
  null. Disk paths are bounded absolute argv values, never shell interpolation.
- Normalized snapshots and planner context expose CpuQuota, CpuPeriod, NanoCpus,
  StartedAt, and per-probe error explanations. Enrichment targets immutable
  container ID; terminal refresh discards logs if StartedAt changed meanwhile.
- DET-3: failed collection now reaches trigger evaluation before the runtime
  returns a collection error, breaking pending windows without resolving any
  incident. Added a runtime-level regression test for that boundary.
- Unit result: python3 -m pytest -q -> 177 passed, 9 opt-in skipped, 1.20s.
- Real Docker result: PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest
  -m integration -q --junitxml=artifacts/raw/g3-evidence-suite.xml -> all 8 passed,
  177 deselected, 66.07s. This includes sustained CPU and current-start log
  filtering in real containers. These tests verify independent classification,
  policy, final status, graceful child shutdown, and scenario-owned cleanup.
- G3 is still incomplete: labeled corpus/denominator report, operator regression,
  normal CLI run-all, and Linux qualification are required. G4/G5 remain open.

## G3 corpus and qualification checkpoint (2026-09-11)

- Added 26 explicitly labeled synthetic cases / 53 observation decisions in
  tests/fixtures/detectors.json. Corpus covers all eight types, priority,
  CPU boundaries/bursts/missing/NaN/stale/duplicates/out-of-order/gaps,
  generation replacement and runtime restart, absent health checks, normalized
  filtered config evidence, unknown dependencies, and disk boundaries.
- python3 -m ci.detector_corpus reports zero false positives and false negatives
  per type. CPU has 2 positive/51 negative samples; each other type has 1
  positive/52 negative samples. These are synthetic sample-level denominators,
  not independent real incidents or estimates of deployment accuracy.
- Evaluator calls only trigger/context/rule-planner/policy logic, not executor
  or live collector. Unit I/O guard remains active. Deliberately wrong labels
  produce regressions. CI now retains the full denominator/trace report.
- Unit suite: 179 passed, 9 opt-in skipped, 0.71s.
- Live operator test: 1 passed, 187 deselected, 12.31s; report
  artifacts/raw/g3-operator.xml.
- Normal python3 -m scenarios run-all --verbose: all eight PASSED, approximately
  63 seconds (06:10:13-06:11:16 UTC). Scenarios list reports all eight supported
  when run with Docker access; the filesystem sandbox alone cannot reach Docker.
- Pushed 13dc0f4, including prior detector commits. CI qualification run:
  https://github.com/beyondamola/patron/actions/runs/34568818075
  Unit Python 3.9/3.12 lanes passed; Docker lanes were still running at the last
  check. Resume this existing run, do not dispatch a replacement.
- G3 remains open pending CI artifacts and requirement-by-requirement review.
  G4 capture/replay and G5 final qualification are not implemented.
- Subsequent check: run 34568818075 completed successfully in all four jobs.
  Downloaded artifacts/g3-qualified; validated exactly eight integration cases
  and one operator case on each Linux architecture, with no failures/skips.
  Both unit artifacts contain the 53-sample corpus report with no regressions.
  Requirement-by-requirement G3 review and a consolidated report remain next.
- Completed that review in G3_VERIFICATION.md. G3 is verified against 13dc0f4;
  G4 begins with explicit clock/ID dependencies, followed by versioned capture,
  isolated exact replay, causal comparison, and fake shadow evaluation.

## G4 dependency groundwork (2026-09-11)

- Added Clock protocol/SystemClock, optional registry ID factory, clock-aware
  incident creation/touch/cooldown, runtime stage timing and window-clock wiring,
  operator application timestamps, and explicit runtime planner/executor seams.
  Defaults retain local live behavior; no replay CLI or capture claim yet.
- Added tests/test_runtime_clock.py: recorded IDs/timestamps, exact cooldown
  boundary, deterministic stage durations and final transition with global
  monotonic/perf_counter/sleep functions forbidden. Existing Docker/network
  guard remains active. Registry state and audit use explicit temporary paths.
- Unit result after groundwork: 181 passed, 9 opt-in skipped, 0.91s.
- G4 remaining: capture schema/validation/redaction, observation and causal hooks
  (including verifier reads), explicit replay adapters, exact and counterfactual
  comparison modes, lifecycle fixtures, fake shadow contract, and qualification.
- G3 report qualifies the pre-groundwork commit 13dc0f4. These G4 changes have
  unit evidence only so far; do not relabel earlier Docker/CI runs as testing them.

## G4 capture primitives and verifier reads (2026-09-11)

- Added optional verifier observation callbacks, clock injection, and explicit
  health-wait control. Tests record all starting/unhealthy/healthy reads at
  deterministic offsets, bound unhealthy waiting to eight simulated seconds,
  reject observation sink failures, and prove escalation invents no Docker read.
- Added harness/capture.py primitives: private exclusive JSONL creation, fsynced
  events, schema/run/sequence/time envelope, explicit normalized snapshot fields,
  relative sample timestamps, bounded/redacted logs, omitted raw inspect/env
  fields and arbitrary labels. Reader rejects schema/sequence/run discontinuity,
  nonfinite offsets, missing initial-state envelope, partial final write, absent
  run_end, and config fingerprint mismatch.
- These are primitives, not a finished capture or replay feature. Runtime causal
  hooks, initial-state semantic validation, event/reference validation, full
  payload schemas, CLI integration, replay adapters, and shadow comparison still
  remain. No current CLI command is claimed to generate complete captures.
- Added tests/test_capture.py and tests/test_verifier_observations.py. Full unit
  suite result recorded at this checkpoint: 195 passed, 9 opt-in skipped.

## G4 runtime capture wiring (2026-09-11)

- Opt-in --capture on run/watch and lab run/run-all now writes the observation
  stream, initial registry envelope, runtime settings, cycle boundaries, trigger
  traces, context, plan/policy, requested/executed actions, individual default
  verifier reads, verification results, terminal state, and queued operator
  requests before/after application. State export is detached and read-only.
- CLI/watch close streams in finally; successful completion emits run_end and
  interrupted capture does not. Write failures before action_requested prevent
  executor invocation. Capture files cannot equal the state or incident audit.
- Unit result: 201 passed, 9 opt-in skipped, 0.77s. New runtime tests cover
  healthy/error cycles, successful restart references, dry-run skipped stages,
  write failure, path separation, and queued operator acknowledgment events.
- Real Docker: python3 -m scenarios run unhealthy --capture --verbose PASSED,
  including cleanup. Scenario b3521f87-bb35-4871-8d05-72aaa73a23b9; capture at
  logs/scenarios/b3521f87-bb35-4871-8d05-72aaa73a23b9/capture.jsonl was read back.
  It contains 4 main observations (healthy, healthy, unhealthy, healthy), separate
  verifier reads (starting, healthy), one action, and a clean run_end.
- Still incomplete: full event/payload/reference and initial-state validation,
  causal replay, counterfactual comparisons, replay fixtures, fake shadow, and
  full G4/G5 qualification. Structural read-back is not exact replay evidence.

## G4 semantic validation checkpoint (2026-09-11)

- Added replay validate CLI and pure capture_validation module: validates state
  envelope and incident/control records, normalized observation field types,
  target identity, cycle ordering, control pairs, observation/incident references,
  action authorization/order, outcome presence, and independent verifier reads.
  Successful escalation requires the recorded actual ESCALATED transition state.
- Reader now rejects duplicate JSON keys, boolean schema versions, and overflow
  nonfinite numbers as well as partial writes and sequence errors. It continues
  to distinguish structural read from semantic validation.
- Unit suite: 216 passed, 9 opt-in skipped, 0.87s. New corruption cases exercise
  typed state/metrics, wrong targets/references, missing outcomes, and policy
  denial before an attempted action. Validation CLI is tested read-only.
- Validated the real b3521f87-bb35-4871-8d05-72aaa73a23b9 unhealthy capture:
  4 cycles, 1 action, 2 verifier observations. This proves capture validation,
  not replayed lifecycle agreement. Next: exact replay using explicit recorded
  adapters, then counterfactual comparison, corpus/shadow, and qualification.

## G4 first exact replay (2026-09-11)

- Added replay run CLI using existing PatronRuntime with recorded collector,
  deterministic event clock/incident IDs, pure RulePlanner, recording-only
  executor and recorded verifier responses. State/audit locations are explicitly
  redirected to a TemporaryDirectory. Event payload/reference mismatches abort.
- Captures now record mode=cycles/watch. Testing the older real capture exposed
  its missing shutdown-persistence metadata; exact replay now rejects that old
  format clearly. Fresh watch replay reproduces its final registry persist.
- Semantic agreement excludes wall-clock timestamps, filesystem paths, and
  performance metrics. Recorded metrics are separate report data. Coverage
  comparisons round to microseconds to avoid cancellation from removing the
  large monotonic origin. Behavioral predicates/states remain exact comparisons.
- Unit suite: 218 passed, 9 opt-in skipped. Replay tests forbid live adapter
  construction, subprocess/network, real sleep and monotonic/perf-counter calls;
  three reports are identical, source files unchanged, and a changed plan fails.
- Fresh real unhealthy run with --capture PASSED including cleanup; scenario
  9302b516-728c-4cb9-9627-1657c0e1567b. Its capture replay matched 4 cycles and
  1 action; report artifacts/raw/g4-first-replay.json. Three subsequent offline
  replays produced identical semantic reports.
- Still incomplete: operator/control replay, retries/rearm/restart corpus,
  all-eight exact replay qualification, comparison report coverage, fake shadow,
  and G4/G5 full validation. Initial replay support is not the whole goal.

## G4 operator and lifecycle replay coverage (2026-09-11)

- Recorded control requests are materialized only in replay's temporary inbox.
  The existing runtime/control implementation validates and applies them; replay
  compares before/after events and resulting state rather than installing the
  recorded outcome directly. No live incident state is modified.
- Added tests for acknowledgment then rearm, three failed restarts followed by
  suppression, restart with an initially OPEN persisted incident, collection
  failure, exact cooldown boundary (59 vs 60 seconds), and all eight incident
  types through fresh captures. All-eight tests compare three replay reports.
- The first CPU fixture reused one frozen snapshot object and therefore recorded
  cached trigger evidence. Corrected the fixture to emit fresh timestamped
  observations at 0/5/10 seconds, matching collector semantics. No detector
  thresholds or expected sustained-load behavior were weakened.
- Unit result: 231 passed, 9 opt-in skipped, 1.32s. This is synthetic capture and
  replay evidence, not new live eight-scenario or CI qualification.
- Remaining G4: committed sanitized replay files/origin metadata, comparison
  reports and non-executing fake shadow contract, negative/restart corpus, full
  all-eight live capture/replay and CI verification. G5 remains open.

## G4 comparison and fake shadow checkpoint (2026-09-11)

- Added comparison.py fixed-observation detector/planner/policy comparison and
  shadow.py bounded candidate protocol with mirror/escalate/malformed fakes.
  Candidate context is deep-copied; malformed schema is denied, and allowlist
  policy uses the original context. No executor/state runtime is used by compare.
- Reports include per-type classification denominators, missed/extra observations,
  action/policy differences, malformed counts, recorded attempts/final statuses,
  and explicit counterfactual_unknown after any candidate divergence. Candidate
  lifecycle final status remains null, never inherited from recorded recovery.
- Measurement path/dependency/log-TTL changes are rejected because the required
  new measurements were not captured. Threshold/window comparisons remain valid
  fixed-observation experiments, not candidate recovery simulations.
- CLI replay compare writes a new JSON report and exits nonzero on differences.
  Real unhealthy capture 9302b516-728c-4cb9-9627-1657c0e1567b: mirror had 0
  regressions (exit 0); fake escalation had 1 (exit 1). Reports are
  artifacts/raw/g4-comparison-mirror.json and g4-comparison-escalate.json.
- Unit result: 238 passed, 9 opt-in skipped, 1.39s. Tests cover isolation,
  deterministic reports, malformed/confidence bounds, context mutation, policy
  denial, unknown counterfactual outcomes, and unsupported measurement changes.
- Added SHADOW_EVALUATION.md template and real-provider authorization gate.
  G4 remains incomplete: committed replay corpus, richer metrics/timing reports,
  all-eight live capture/replay CI, and full acceptance review remain required.

## G4 corpus and real replay qualification (2026-09-11)

- Integration now enables capture for all eight scenarios, verifies existing
  recovery/escalation and cleanup assertions, then replays each capture three
  times and requires identical reports and expected type/final status. Reports
  are retained beside captures for CI artifacts.
- First real run: 7 passed, restart_loop replay failed on duration evidence
  rounding at a microsecond boundary (3.296255499... vs 3.296255500...). Original
  artifacts/raw/g4-capture-replay.xml and scenario
  f14b95c0-3d41-4ba6-b004-9728bc0722d5 are preserved. Docker classification and
  escalation succeeded; the replay checker, not remediation, failed.
- Replaced decimal rounding with explicit absolute tolerance <=1 microsecond
  for coverage_seconds/recovery_coverage_seconds only. Added tests proving exact
  decision and threshold checks remain unchanged. The original failed capture
  replays successfully with the fix.
- New post-fix real run: all 8 passed in 60.03s, no skips. Evidence:
  artifacts/raw/g4-capture-replay-fixed.xml. No automatic test retry hid the
  initial failure; this was a separate run after a documented code change.
- Added 33 committed synthetic capture fixtures and manifest under
  tests/fixtures/replay. Generator ci/replay_fixtures.py uses the runtime with
  explicit fake infrastructure/clock/IDs, validates labels, sanitizes paths,
  and verifies replay. Fresh regeneration was byte-identical for all 33 files.
- Default corpus tests replay every file three times with Docker constructors,
  subprocess, network, real sleeps and clocks forbidden. Full unit suite:
  272 passed, 9 opt-in skipped, 0.99s.
- G4 still needs richer metrics/timing reports, actual Linux CI qualification
  of capture/replay, and a final requirement review. G5 remains open.

## G4 report metrics and Linux artifact review (2026-09-11)

- Verified GitHub Actions run 34671599363 at commit 57435aa completed successfully:
  https://github.com/beyondamola/patron/actions/runs/34671599363.
  Downloaded evidence to artifacts/g4-qualified. On each Linux architecture,
  validated exactly eight scenario cases and one operator case with no failures,
  errors, or skips; inspected all eight retained replay reports.
- Replayed all 16 downloaded Linux captures three times using the current code.
  Each produced identical semantic reports, all eight expected classifications
  were present on each architecture, and exact replay matched recorded outcomes.
  This is offline revalidation of actual CI captures, not another live Docker run.
- REP-5: harness/replay_metrics.py now reports per-type classification and
  terminal-state agreement with denominators after successful exact matching.
  Suppressed observations do not inflate the number of terminal outcomes.
  These are reproducibility counts, explicitly not ground-truth accuracy.
- Comparison adds action/policy totals, recorded runtime metrics, and explicit
  null candidate final-state agreement with an unknown-outcome denominator.
  Unknown detection onset stays null. CLI computation timing is nonsemantic
  report_metadata; core APIs remain clock-free and deterministic.
- Tests: tests/test_replay_reports.py checks retry/suppression denominators,
  different CLI timing with identical semantic results, and a changed disk
  threshold yielding a readable missed incident and exit status 1 without a
  candidate recovery claim. Existing corpus tests still replay each fixture
  three times under live-I/O prohibitions.
- Initial metrics implementation used the wrong policy payload key and failed
  27 replay tests. Corrected it to the existing policy event schema, without
  modifying captures or expected behavior. Final command python3 -m pytest -q:
  275 passed, 9 opt-in skipped, 10.84s.
- Updated README and SHADOW_EVALUATION.md to distinguish completed corpus/CI
  evidence from open final review. G4 still needs its requirement-by-requirement
  review, including provenance/known-onset reporting and incomplete causal
  evidence behavior. G5 final qualification and handoff are not complete.

## G4 lab provenance and local workflow qualification (2026-09-12 UTC)

- Added optional `--scenario-results` to replay run/compare. The pure reader in
  harness/replay_provenance.py correlates incident ID, target, type, and effective
  configuration. Unknown onset stays null; lab-known UTC injection-to-creation
  delay is separate from captured runtime stage latency and candidate outcomes.
  Duplicate/mismatched/oversized/incomplete results fail without overwriting inputs.
- Existing CI evidence revealed restart_loop injection precedes capture startup.
  The reader now explicitly marks this valid lab-known onset instead of rejecting
  it or fabricating a later injection time. All 16 retained Linux captures from
  run 34671599363 correlate with their scenario-local result.jsonl files.
- Added an exact replay preflight for exception-only collection cycles: preserve
  the diagnostic capture, reject exact replay with missing collector observation.
  Normalized failed-collection snapshots continue to replay. No synthetic healthy
  observation or exception outcome is substituted.
- Added STATE_AND_CAPTURE_FORMATS.md and README provenance commands. Corrected
  the progress overview's stale G3/G4 entries; historical checkpoints stay intact.
- `python3 -m pytest -q`: 290 passed, 9 opt-in skipped, 2.35s. New tests cover
  known/unknown/pre-capture onset, correlation mismatches, ambiguous inputs,
  output alias protection, candidate outcome isolation, and collector exceptions.
- `PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest -m integration
  --junitxml=artifacts/raw/g4-provenance-integration.xml -q`: all 8 passed,
  290 deselected, 67.27s. Each includes three identical exact replays and lab
  provenance checks, graceful shutdown evidence, and resource cleanup assertions.
- `python3 -m scenarios list` with Docker access: all eight supported. Sandboxed
  listing correctly reported Docker unavailable because of daemon permissions;
  that was not used to claim the live environment was unavailable.
- `python3 -m scenarios run-all --verbose --capture`: all eight PASSED. Retained
  log artifacts/raw/g4-provenance-run-all.log, approximately 04:38-04:40 UTC.
  Replayed each normal CLI capture three times and correlated global lab results.
  Each retained Patron log contains shutdown complete. Separate read-only Docker
  queries found no containers/networks/volumes for these eight scenario UUIDs;
  `pgrep -fl 'python.* -u -m harness watch'` found no matching managed processes.
- Normal CLI IDs: stopped 36bc5b1c-f7c8-4ace-9603-74dd6e6ba970;
  unhealthy 3a083faa-fed2-4fda-b09f-22f5a1613f11;
  restart_loop 4a3750cd-4453-40b9-8aef-f764352c2aa4;
  oom_killed 8f19eb1d-36c1-4ed9-b947-c85389716a3b;
  high_cpu 795a36cd-31be-4db5-98a4-31ded3f1bee3;
  disk_full be1318bf-c6d3-4d3a-86de-95e9a3407b9f;
  bad_config efd3e44c-7fa5-4f73-8999-4ad815516bdf;
  dependency_down 949820e6-8358-41e4-a3d5-e553c5fa11bf.
- G4 final causal-evidence review/current-revision CI and G5 acceptance/handoff
  remain open. These new local results do not replace the separate Linux CI gate.

## G4 historical-control replay correction (2026-09-12)

- Review found that initial state alone omitted audit-only resolved incidents
  and request results aged out of the state cache. Added minimal, state-scoped
  control_history to new capture headers and seed it only into replay's temporary
  audit file. Current incidents are not duplicated; raw audit logs are not copied.
  History is bounded to 1000 entries and existing 1MB capture-record limits.
- The regression test acknowledges an audit-only resolved incident, repeats an
  old request retained only in audit, then applies a fresh acknowledgment. Three
  replays match and leave original files unchanged under live-I/O prohibitions.
  Additional tests reject malformed history and prove unrelated-state exclusion.
- This test also found a macOS temporary-directory alias mismatch. Replay now
  resolves its temporary root before assigning state/audit evidence paths, so
  state-scoped audit lookup works consistently. The initial fixture was corrected
  to start a fresh runtime with advancing observations, as the real CLI does;
  enabling capture mid-window is not a supported runtime workflow.
- Full local command python3 -m pytest -q: 298 passed, 9 opt-in skipped, 6.73s.
- Existing CI run 34673684287 for 545a6ac was observed with both unit lanes passed
  and both Docker jobs in progress. The later status request was denied by the
  automatic approval service because of its usage limit. Its final result is
  unverified; no duplicate CI run or alternate access route was used.
- Current historical-control changes still require Docker/CI requalification.
  G4/G5 remain open, with no claim that older CI evidence proves these changes.

### Historical-control qualification follow-up

- Approval access resumed. Run 34673684287 is successful; downloaded artifacts
  to artifacts/g4-provenance-qualified and inspected the exact 290 unit cases
  per Python version, 8 scenario + 1 operator cases per Linux architecture,
  and 16 matching replay/provenance reports. None of these cases were skipped.
- Pushed f8f5ce7; its CI run is 34715607993. No duplicate workflow was started.
- Current local Docker: all 8 passed, 299 deselected, 80.02s. Evidence:
  artifacts/raw/g4-history-integration.xml. Tests include capture/replay,
  historical-header compatibility, lab provenance and resource cleanup.
- The 33 checked-in captures and manifest still regenerate byte-identically.
  Added G4_VERIFICATION.md with evidence/requirements mapping and explicit limits.
  Current-revision CI artifact review and G5 handoff remain required.

### CI OOM race found and corrected

- Run 34715607993 failed the Linux amd64 operator workflow; this was not a
  historical-control replay failure. Original evidence is preserved under
  artifacts/g4-history-failed. The final operator assertion correctly found an
  unexpected RESOLVED CONTAINER_STOPPED incident in an OOM-only environment.
- Audit incident c6c9b54b-10b9-4faa-8a95-4a4113732ef9 records an unintended restart
  at 19:58:12 UTC. Trace showed exit_code=137 and oom_killed=false, followed by
  positive OOM evidence at 19:58:14. The existing immediate inspect confirmation
  was insufficient to eliminate Docker's delayed OOM metadata window.
- ContainerStoppedTrigger now withholds generic restart for nonrunning exit 137
  without positive OOM evidence. It does not classify SIGKILL itself as OOM.
  Trace explains the uncertainty; subsequent positive OOM evidence escalates.
  Persistent unknown SIGKILL causes require operator investigation, documented
  in README. No detector threshold was lowered and no new action was added.
- tests/test_oom_transition.py proves no action/healthy result on the ambiguous
  observation, followed by exactly one escalation when OOM evidence arrives.
  All-eight integration now inspects the entire state-scoped audit history for
  wrong classifications and any restart in escalation-only scenarios.
- Local unit: 300 passed, 9 opt-in skipped, 5.68s. Real operator test after the
  correction: 1 passed, 308 deselected, 13.80s; evidence
  artifacts/raw/g4-oom-guard-operator.xml. New all-eight/CI qualification remains
  required; the original failed workflow is not replaced or retried to green.

## OOM fixture observability correction (2026-09-13)

- Run 34715967546 failed OOM injection confirmation on amd64's scenario lane
  and arm64's operator lane: Docker remained exited/137/OOMKilled=false for the
  entire 20-second confirmation window. The new safety guard withheld restart;
  the lab correctly did not infer OOM from exit code. Evidence is retained in
  artifacts/g4-oom-guard-failed and artifacts/raw/g4-oom-guard-ci-failure.log.
- Prior local all-eight safety-guard suite passed: 8 cases, 68.84s, evidence
  artifacts/raw/g4-oom-guard-integration.xml. Normal run-all also passed all eight
  in artifacts/raw/g5-run-all.log. These local successes did not override CI.
- Supervised OOM allocation now leaves a low-memory PID 1 alive for five seconds
  after its high-memory child exits. Strict 32MiB memory/swap limits remain;
  one CPU and 32-process caps are explicit. Docker OOMKilled=true remains the
  mandatory injection predicate, with no state mutation or fabricated metrics.
- Local focused live case passed: 1 case, 17.25s, evidence
  artifacts/raw/g5-supervised-oom.xml. Scenario
  df685cb7-1140-43df-b1e8-2f91dbf283be captured OOMKilled=true while its supervisor
  was running and exactly one requested action: escalate. Owned cleanup passed.
- Unit suite: 301 passed, 9 opt-in skipped, 11.52s. New fixture test checks the
  supervisor command, required ownership labels, and all resource caps.
- The first live attempt was denied by approval-service usage limits; it did not
  run. Access later resumed and the focused result above is the actual execution.
- Added OPERATOR_RUNBOOK.md and corrected README's stale single-sample CPU claim.
  Full local/CI qualification of the supervised fixture is still pending.

- Combined supervised-fixture qualification completed: 9 passed, 301 deselected,
  101.08s. Command: PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest
  -m 'integration or operator_integration' --junitxml=artifacts/raw/g5-supervised-full.xml -q.
  Strict XML validation confirms exactly eight scenarios plus one operator case,
  zero failures/errors/skips. Scenario checks include full incident history,
  no hidden restart in escalation-only cases, exact replay, provenance, and cleanup.
  Linux CI remains required before concluding the fixture correction is qualified.

## G5 final qualification (2026-09-13)

- Corrected fixture revision 4265487 passed three independent full workflows:
  34741568850, 34741772883, 34741791860. Downloaded XML independently confirms
  301 units on Python 3.9/3.12 and eight scenarios plus one operator case on each
  Linux architecture, zero failures/errors/skips. All 16 scenario/replay reports
  per workflow match. Original OOM failures remain failed and retained.
- Final failure-path review found injection exceptions before InjectionResult
  could be mislabeled SETUP_FAILED. Revision c1cc647 tracks execution phase and
  tests setup/injection/observation errors while preserving a primary error when
  cleanup also fails. No runtime action or successful scenario behavior changed.
- Final local units: 304 passed, nine opt-in skipped, 10.927s; evidence
  artifacts/raw/g5-final-unit.xml. Initial Docker command omitted the opt-in and
  skipped nine cases, retained as artifacts/raw/g5-final-docker.xml, not a pass.
  Explicitly enabled qualification passed nine cases, zero failures/errors/skips,
  99.64s; artifacts/raw/g5-final-docker-enabled.xml.
- c1cc647 CI run 34742002479 passed all four jobs: 304 units on each supported
  Python lane; eight Docker scenarios plus operator on amd64 and arm64, zero
  skips. Downloaded artifacts/g5-final-qualified reviewed for counts, correct
  scenario fields and replay matches. All 16 captures independently replayed
  three times and reproduced retained reports including lab provenance.
- Normal final CLI run-all --verbose --capture passed all eight at
  06:11:51-06:13:06 UTC. IDs and outcomes are in G5_VERIFICATION.md and the local
  scenario JSONL. All eight captures replayed three times, provenance matched,
  shutdown completion appeared in all logs. Read-only scenario-ID Docker queries
  found no owned containers/networks/volumes. Authorized process query found no
  managed watch processes. No unrelated resources were deleted.
- scenarios list shows all eight supported. Detector corpus remains 26 cases,
  53 observations, zero false positives/negatives; these are synthetic accuracy
  checks, not a production accuracy estimate.
- G4 report finalized; G5_VERIFICATION.md supplies the acceptance matrix,
  environment split, exact evidence, original failures and limitations.
  OPERATOR_RUNBOOK.md, STATE_AND_CAPTURE_FORMATS.md, README.md and
  SHADOW_EVALUATION.md provide the handoff. G0-G5 are verified. Real providers
  and any expansion of remediation authority remain separately authorized work.
