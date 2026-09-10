# Patron Reliability Roadmap

Status: proposed implementation specification; no roadmap work is claimed complete.

Purpose: serve as the goal and acceptance contract for a long-horizon engineering task covering four workstreams:

1. Repeatable Docker integration testing in CI with pinned images.
2. Incident inspection, acknowledgment, and explicit rearming.
3. Sustained-load detection and false-positive regression testing.
4. Deterministic replay, followed by a separately authorized planner shadow evaluation.

This is a milestone-based plan, not a calendar commitment. Finish and verify each gate before advancing. Do not replace missing evidence with estimates of completion.

## 1. Starting Point

The baseline is recorded in `VERIFICATION.md`, dated 2026-09-09. That report documents 56 passing unit tests, eight passing real Docker integration tests, and a subsequent successful normal `scenarios run-all` execution on macOS arm64. These are historical results, not proof that a future checkout still passes. Re-run the baseline at implementation start.

| Scenario | Expected classification | Expected outcome |
| --- | --- | --- |
| stopped | CONTAINER_STOPPED | restart_container, RESOLVED |
| unhealthy | CONTAINER_UNHEALTHY | restart_container, RESOLVED |
| restart_loop | CONTAINER_RESTART_LOOP | escalate, ESCALATED |
| oom_killed | CONTAINER_OOM_KILLED | escalate, ESCALATED |
| high_cpu | CONTAINER_HIGH_CPU | escalate, ESCALATED |
| disk_full | CONTAINER_DISK_FULL | escalate, ESCALATED |
| bad_config | CONTAINER_BAD_CONFIG | escalate, ESCALATED |
| dependency_down | CONTAINER_DEPENDENCY_DOWN | escalate, ESCALATED |

Preserve the Collector -> Trigger -> Context -> Planner -> Policy -> Executor -> Verifier -> Audit boundaries. Patron observes infrastructure; the lab modifies its own infrastructure and reads evidence. The lab must never manufacture runtime incidents or change runtime state to make a test pass.

Known limitations motivating this plan:

- Real Docker verification has not established Linux CI portability.
- Images use tags rather than immutable digests.
- Terminal incidents remain suppressed without an operator CLI.
- State replacement is atomic, but concurrent state writers are unsupported.
- CPU detection uses a single sample; configuration and dependency evidence use MVP heuristics.
- Existing audit records are incident snapshots, not a complete replayable observation stream.
- Unknown runtime failure onset is correctly reported as unknown, not a fabricated detection latency.

## 2. Scope and Guardrails

Required scope is the four workstreams below, through an offline shadow-evaluation contract. Calling real model providers is a subsequent, explicit approval gate, not a prerequisite for completing this plan.

Do not add Kubernetes, Ansible, new failure scenario types, a web UI, a database, distributed workers, autonomous model execution, production chaos testing, or additional destructive remediation actions.

Keep these invariants throughout:

- Only `restart_container` and `escalate` are executable decisions. Policy remains authoritative.
- Escalation is containment of automated actions, not evidence of infrastructure recovery.
- Verifier conclusions come from deterministic observations or the actual incident transition.
- Unknown metrics remain unknown. Collection failures cannot resolve incidents.
- Resource tests use bounded CPU, memory, processes, time, and disk space.
- Cleanup checks ownership and run identity; never use broad Docker prune commands.
- Default unit tests remain Docker-free, network-free, fast, and non-destructive.
- Preserve existing audit history. Version new formats and support documented legacy reads.
- Do not introduce a service or dependency where a small standard-library module suffices.

## 3. Execution Order and Gates

| Gate | Deliverable | Depends on | Completion evidence |
| --- | --- | --- | --- |
| G0 | Reproduced baseline and implementation inventory | None | Test output, environment, resource cleanup |
| G1 | Pinned, reproducible CI integration pipeline | G0 | Successful unit and eight-scenario Docker jobs |
| G2 | Safe operator incident workflow | G1 | Live/offline command tests, restart and race tests |
| G3 | Windowed detection and negative-case corpus | G2 | Deterministic predicate tests and all eight live scenarios |
| G4 | Versioned capture and deterministic replay | G3 | Repeatable reports, regression diffs, no-I/O safety tests |
| G5 | Final end-to-end qualification and handoff | G1-G4 | Acceptance matrix, documented limitations, artifact links |

Design the minimal event envelope and resource identity at G0 so later work does not create incompatible formats. Implement only fields required by each gate. Planning later interfaces is not permission for unrelated refactoring.

### G0 work packages

- [ ] Inventory runtime, scenario, test, and CLI behavior against this document.
- [ ] Re-run unit tests, opt-in Docker integration tests, and normal `run-all`.
- [ ] Record Python, Docker, host architecture, image identities, durations, and cleanup results.
- [ ] Establish a clean implementation checkpoint without reverting user changes.
- [ ] Determine the repository and CI destination. If no remote is configured, request the user's destination; do not invent one or publish code automatically.
- [ ] Create a progress record with work-package status, evidence, decisions, and blockers.

## 4. Workstream One: Docker CI and Immutable Fixtures

### Objective

Make a passing build mean that Patron actually processed all eight Docker failures, not merely that mocks passed or Docker was installed.

### Implementation

**CI-1: Reproducible environment.** Declare the supported Python version range and pin development/test dependencies. Choose versions after checking compatibility with the existing code. Centralize scenario image references in one small module or manifest. Resolve actual multi-architecture image digests for nginx and Alpine, record how they were obtained, and verify both intended Linux architectures. Never invent a digest. Updating a pin requires the same integration gates as changing a scenario.

**CI-2: Separate test lanes.** Add a fast unit lane and a Docker integration lane using the repository's chosen CI provider. Use an isolated Linux runner with Docker, not a developer's daemon. Explicitly enable `PATRON_RUN_DOCKER_INTEGRATION=1` for integration. Fail the integration job if Docker is unavailable or any of the eight required cases is skipped. Keep local integration opt-in and local unavailability messages clear.

**CI-3: Bounded execution.** Pre-pull pinned images with a separate timeout so image download time is not confused with remediation latency. Initially allow 120 seconds per scenario and 20 minutes per integration job; adjust only from recorded runner evidence. Keep scenario polling bounded. Resource prefixes and labels must identify the CI run and scenario UUID, including dependency networks and secondary containers.

**CI-4: Evidence and cleanup.** Retain test reports, scenario results, Patron output, audit records, configuration, image digests, and normalized failure/final states. Redact sensitive log content before upload. Start with 14-day artifact retention where the provider supports it. Always run cleanup, including on job failure; only select the current job's resources. A cleanup failure fails the job. Preserve evidence even when cleanup fails.

**CI-5: Flake handling.** Do not convert a failing first attempt into a green build through hidden retries. Preserve and report the first failure. Diagnostic reruns may collect evidence but cannot replace the original result. Distinguish setup/download failures, injection failures, missing incidents, incorrect policy, timeout, and cleanup failure.

### Tests and acceptance

- [ ] A fresh runner installs declared dependencies without relying on a local virtualenv.
- [ ] Unit tests do not invoke Docker or external network services.
- [ ] Integration executes eight cases with zero skips and verifies classification, policy, final state, graceful shutdown, and resource cleanup.
- [ ] A deliberately unavailable Docker daemon fails the integration lane clearly.
- [ ] An intentionally broken expected outcome makes the job fail.
- [ ] Two isolated runs do not share names, state files, or cleanup ownership.
- [ ] Failed tests still retain diagnostic artifacts and attempt cleanup.
- [ ] Three consecutive integration executions pass without automatic retries.
- [ ] Linux CI and a macOS arm64 local run are documented separately; neither is claimed to prove every Docker version.

Expected touchpoints: `scenarios/docker_utils.py`, image configuration, `tests/scenarios/test_integration.py`, dependency declarations, CI configuration, README.

## 5. Workstream Two: Operator Incident Control

### Objective

Allow an operator to understand and deliberately release persistent suppression without editing JSON or accidentally restarting a container.

### Proposed CLI contract

```bash
python -m harness incidents list --state-path logs/incident_state.json
python -m harness incidents show <incident-id> --json
python -m harness incidents acknowledge <incident-id> --reason "Investigation started"
python -m harness incidents rearm <incident-id> --reason "Configuration corrected"
```

All subcommands accept an explicit state path. Resolution order is CLI flag, `PATRON_STATE_PATH`, then the documented default. Show the resolved path in human-readable output so operators do not confuse managed lab state with a normal runtime. Support `--json` for scripts and `--dry-run` for mutations. No confirmation prompt is necessary when the user explicitly issues a mutation with an incident ID and nonempty reason.

### State semantics

| Operation | Required behavior |
| --- | --- |
| list/show | Read-only; show target, container ID if known, type, status, attempts, suppression, timestamps, acknowledgment, and evidence references |
| acknowledge | Add operator attribution, reason, and timestamp; do not resolve, execute, rearm, or reset attempts |
| rearm | Accept only the currently suppressed terminal incident; release that incident's suppression for the next collection cycle |
| next unhealthy cycle | Create a new incident ID linked to the rearmed predecessor; use normal policy and retry rules |
| next healthy cycle | Create no incident and execute nothing |
| repeat request | Return its existing result when the request ID repeats; do not apply twice |

Rearming does not rewrite the historical incident to OPEN. Preserve its final state and all audit history. Initially allow rearming ESCALATED and FAILED only; reject OPEN, RUNNING, stale IDs, and RESOLVED incidents. Ordinary resolved cooldown remains intact. Rearming removes the terminal suppression and associated cooldown only for the addressed resource generation and incident.

An acknowledgment is metadata, not a sixth lifecycle status. Attribution is a local operator label, not an authentication claim. Recording a reason must not grant additional policy permissions.

### Safe state ownership

**OPS-1: Version and identity.** Add a versioned state envelope and stable resource identity incorporating Docker container ID. Keep display names. Migrate legacy name-only records conservatively: do not silently release existing suppression when identity is unknown. Preserve a backup before migration. Keep resolved history queryable from audit records rather than growing an unbounded state history.

**OPS-2: Single writer.** Introduce a state-path ownership lock held by the runtime. A second runtime using that path fails clearly. Do not let the CLI overwrite a running process's cached registry. Use a small atomic file-based control inbox adjacent to the state file; the runtime processes requests between remediation iterations. Each request includes request ID, incident ID, expected state revision, operation, reason, and timestamp.

**OPS-3: Live and offline operations.** A live CLI waits a bounded time for a persisted request result. A timeout reports pending, not success; `show` can inspect the request status. If no runtime owns the path, the CLI acquires the same ownership lock and applies the same validated operation offline. Lock ownership must not be inferred solely from an old PID file. Never hold up or interrupt an in-progress Docker action to apply an operator request.

**OPS-4: Crash consistency.** Persist applied request IDs and results with the state transition. Give audit events stable event IDs so interrupted delivery can be retried without ambiguous duplicate effects. Distinguish committed state from pending audit delivery; a command must not report full success while required logging is missing. Test crashes before and after each persistence boundary. Use atomic replacement and bounded retention of completed control files.

### Tests and acceptance

- [ ] Read commands work against legacy and current state, including resolved audit-only incidents.
- [ ] Acknowledgment never changes lifecycle status, attempts, or Docker state.
- [ ] Rearming a persistent failure produces exactly one new incident on the next evaluation.
- [ ] Restarting the runtime preserves suppression, acknowledgment, and processed requests.
- [ ] A stale request cannot release suppression on a newer incident.
- [ ] Concurrent acknowledgments, duplicate requests, shutdown, and interrupted writes lose no accepted update.
- [ ] Offline and live commands have identical validation and semantics.
- [ ] Corrupt state or unsupported schema fails closed with actionable errors; no automatic state deletion.
- [ ] Managed lab state remains separate and unrelated incidents are untouched.
- [ ] The eight existing scenarios still pass without using operator commands to force a result.

Expected touchpoints: `harness/incident.py`, `harness/main.py`, runtime cycle boundaries, audit event reader/writer, focused state/control modules, operator tests.

## 6. Workstream Three: Evidence Quality and False Positives

### Objective

Detect sustained problems while rejecting brief or stale signals. Make every trigger decision explainable from timestamped observations and explicit configuration.

### Detection contract

**DET-1: Configuration.** Add a small validated configuration model for thresholds, window duration, minimum samples, maximum sample gap, and optional measurement paths/dependencies. Print effective settings in trace output and audit their fingerprint. Preserve configurable restart-loop threshold 3 and disk threshold 90 percent initially. Reject negative, nonfinite, or contradictory settings at startup.

**DET-2: Sustained CPU.** Replace a single-sample alarm with a time-and-sample window. Initial default: at least three consecutive valid CPU samples at or above 80 percent spanning at least 10 seconds, with no gap over 15 seconds. Use monotonic time, not wall-clock timestamps, for elapsed windows. The default 10-second polling interval therefore requires at least three samples spanning 20 seconds. Document this expected detection delay.

Recovery evidence for a CPU alarm requires at least two valid samples at or below 60 percent spanning at least 5 seconds. This is hysteresis for evidence, not automatic release of an ESCALATED incident. The operator still controls terminal rearming. Define Docker CPU percent in terms of one logical CPU, and expose quota information rather than silently changing the denominator.

**DET-3: Unknowns and generations.** Missing CPU readings, counter resets, out-of-order samples, and excessive sampling gaps break an unconfirmed sustained sequence. They do not count as healthy observations and do not resolve an incident. Recreating a same-name container resets metric history using container ID. Persist only the incident identity needed for suppression; rebuild sample windows after runtime restart rather than treating downtime as measured load.

**DET-4: Specific evidence.** Bound configuration error evidence by timestamp and the current container start, so an old error cannot permanently classify a recovered process. Dependency-down requires positive dependency evidence, not merely a failed inspect request. Missing healthchecks remain `none`. Disk measurement uses an explicit bounded configured path and argv-based execution, not interpolated shell strings. Unsupported probes yield unknown plus an explanation.

**DET-5: Priority and trace.** Retain OOM, restart loop, bad config, dependency down, disk, CPU, unhealthy, stopped priority. Trace every evaluated predicate with observed values, threshold/window, sample count, coverage duration, rejection reason, and winning priority. Keep stateful window evaluation behind trigger/registry interfaces, not incident-specific branches in `runtime.py`.

The lab's high-CPU scenario must confirm the metric independently and allow enough time for the configured sustained window. Pass the same explicit detector configuration to managed Patron and record it in results. Do not bypass the detector or inject synthetic metrics into a live run.

### Negative-case corpus

Build unit/replay fixtures, not additional destructive scenario types:

- Healthy running containers with and without a healthcheck.
- CPU bursts shorter than the window and values just below, exactly at, and above thresholds.
- Missing, NaN, stale, duplicate, and out-of-order samples.
- Same-name container replacement and runtime restart during a partial window.
- Historical config errors followed by a new healthy start.
- Dependency inspect failure versus a confirmed stopped dependency.
- Restart count below/at threshold and simultaneous generic symptoms.
- Disk probe unavailable, normal occupancy, and threshold boundary.

Label expected decisions before measuring results. Report false positives and false negatives per incident type with denominators; do not market accuracy from eight positive scenarios alone.

### Tests and acceptance

- [ ] Window tests use an injected clock and perform no real sleeps.
- [ ] No negative corpus fixture produces an unexpected incident or restart.
- [ ] Every positive fixture triggers within its configured window plus one collection interval, excluding separately bounded collection duration.
- [ ] Unknown observations never count toward success or recovery.
- [ ] Priority tests prove specific causes beat generic stopped/unhealthy symptoms.
- [ ] Same-name recreation does not inherit metric windows from the old container.
- [ ] All eight real scenarios pass with the sustained detector enabled.
- [ ] Trace output is sufficient to reconstruct why the detector accepted or rejected.

Expected touchpoints: collector normalization, trigger registry/classes, context packet, configuration, scenario configuration propagation, deterministic fixture tests.

## 7. Workstream Four: Deterministic Replay and Shadow Readiness

### Objective

Re-evaluate recorded evidence without Docker mutations, external network calls, real-time sleeps, or dependence on a live environment. Use this to test rule changes before considering alternative planners.

### Capture format

**REP-1: Versioned observations.** Add an opt-in normalized observation stream separate from incident audit and scenario results. Capture healthy cycles and collection errors as well as incidents. Each envelope includes schema version, run ID, sequence, UTC time, monotonic offset, resource name/container ID, collector/configuration versions, normalized snapshot, and probe availability/errors.

Bound and redact logs at capture time. Do not serialize raw inspect dumps, environment variables, credentials, or arbitrary filesystem content. Version redaction behavior. Store scenario provenance and known injection time separately from runtime measurements; missing onset stays null.

**REP-2: Causal events.** Record planner input/output, policy decision, requested action, executor result, verification observations, operator control events, and final transitions with references to observation and incident IDs. Verification observations must be captured separately from normal polling: a verifier may perform additional reads. Store initial state and effective configuration so cooldown, retries, and suppression are reproducible.

Continue to read existing incident JSONL as historical evidence, but do not promise full deterministic replay from records that lack observations. Reject unsupported replay inputs with a specific missing-evidence explanation.

### Replay engine and CLI

```bash
python -m harness replay validate <capture-path>
python -m harness replay run <capture-path> --output <report-path>
python -m harness replay compare <capture-path> --baseline-config <path> --candidate-config <path>
```

These are proposed interfaces to implement, not currently available commands.

**REP-3: Isolated execution.** Supply a recorded collector, deterministic clock/ID source, pure planner/policy, and recording-only executor. Replay must have no live Docker adapter fallback. Simulated waiting advances the recorded clock. Pass temporary state/audit sinks explicitly so replay cannot read or overwrite live incident state. Deny subprocess and network access in replay tests; any attempted access fails the test.

**REP-4: Two honest modes.** In exact replay, require the recorded actions and inputs to match and reproduce transitions using recorded executor/verifier responses. In comparison mode, compare trigger, planner, and policy outputs against identical observations. If a candidate chooses a different action, mark downstream recovery and lifecycle outcome counterfactual/unknown. Recorded recovery after a restart is not proof that escalation or a different action would have recovered the container.

**REP-5: Reports.** Include per-type classification agreement, policy denials, action differences, malformed plans, missed/extra incidents, attempts, final-state agreement where causally valid, and known detection delay. Separate recorded runtime stage latency from replay computation time. Use machine-readable JSON and a concise CLI summary. Repeated runs must produce identical semantic output; isolate generated report timestamps from comparison content.

### Corpus and shadow boundary

**REP-6: Regression corpus.** Check in small sanitized fixtures covering the eight incident types and Workstream Three's negative cases. Include retries, cooldown, escalation suppression, rearm, collection failure, and crash/restart continuity. Document fixture origins and expected outcomes. Keep large raw lab output out of source control and reference retained artifacts instead.

**REP-7: Shadow contract.** Define a candidate planner interface that receives the same context schema and returns a bounded structured recommendation. Implement a deterministic fake candidate to exercise comparison and malformed-output handling. Candidate output never reaches the live executor, changes incident state, or overrides policy. Produce an evaluation template covering classification context, schema validity, policy admissibility, disagreement, latency, and unavailable outcome evidence.

Do not add provider SDKs, secrets, billable calls, or real GPT/Claude/local-model evaluation under this plan. Before such a follow-on, require explicit authorization, a fixed sanitized corpus, provider/data-sharing approval, cost/time caps, and an execution-disabled design review. Good shadow scores never automatically authorize live actions.

### Tests and acceptance

- [ ] Capture validation detects missing sequences, unsupported schemas, invalid types, and missing initial state.
- [ ] An incomplete final JSONL write is reported as incomplete, not silently treated as a fully valid capture.
- [ ] Exact replay reproduces the expected eight classifications and causally supported terminal outcomes.
- [ ] Retry, cooldown, sustained windows, operator events, and restart continuity replay deterministically.
- [ ] Three runs of each fixture have identical semantic reports.
- [ ] Replay tests prove zero Docker, subprocess, network, and real sleep calls.
- [ ] Candidate rule changes produce readable diffs and a nonzero regression exit code when expectations fail.
- [ ] A different candidate action cannot inherit a recorded successful recovery claim.
- [ ] Fake shadow candidates cannot reach execution or mutate production state.

Expected touchpoints: normalized observation recording, audit envelopes, dependency injection for clocks/IDs, replay package/CLI, fixture corpus, report serializer.

## 8. Cross-Cutting Verification and Failure Handling

Use a traceability table in the implementation progress document: requirement ID, changed files, test names, command, result, and evidence path. A passing unit test does not substitute for a Docker scenario or an observed CI run.

At each gate, run:

```bash
python -m pytest
PATRON_RUN_DOCKER_INTEGRATION=1 python -m pytest -m integration
python -m scenarios list
python -m scenarios run-all --verbose
```

Also run the workstream-specific commands and failure-path tests. Record exact commands and environment. Verify no job-owned containers, networks, volumes, or Patron subprocesses remain. Do not remove unrelated or deliberately retained developer resources to make cleanup checks green.

Maintain explicit error categories: setup, collection, invalid input, state conflict, policy denial, execution, verification, timeout, audit persistence, and cleanup. Preserve the primary error when cleanup also fails. Never print PASSED before required correlation, final-state validation, logging, and cleanup have completed.

Compatibility requirements:

- Existing `run`, `watch`, `inspect-docker`, and scenario commands remain usable.
- Existing scenario result consumers tolerate additive versioned fields.
- Audit readers distinguish incident snapshots from operator/capture event types.
- Migration tests retain legacy incident IDs, timestamps, final status, and suppression.
- Dry-run never performs Docker mutation; acknowledgment/rearm dry-run never changes state.

## 9. Risks and Decision Rules

| Risk | Required response |
| --- | --- |
| CI destination or permission unavailable | Complete local workflow/tests; report G1 externally blocked, never claim a CI success |
| CPU variability on shared runners | Inspect measured windows/quota and preserve failure evidence; do not silently lower thresholds |
| State races or interrupted control requests | Keep a single writer, revision checks, idempotent requests, and crash tests |
| Legacy state lacks container identity | Preserve suppression conservatively and require explicit operator action |
| Capture leaks sensitive logs | Bound/redact at source; review fixtures before committing or uploading |
| Replay lacks causal evidence | Report unknown or reject exact replay, never fabricate outcomes |
| Migration or audit write fails | Fail closed, preserve original files, and provide recovery instructions |
| Scope grows into a control plane | Defer UI, multi-target orchestration, databases, and provider integrations |

Prefer an explicit documented limitation to an unsafe workaround. Ask for user input only when an external destination, credential, spending decision, destructive action, or material policy change is necessary. Continue independent work while a gate is blocked, but do not mark that gate complete.

## 10. Final Qualification and Deliverables

G5 requires all of the following:

- [ ] G0-G4 have linked evidence and no unresolved correctness/safety blockers.
- [ ] All eight existing scenarios pass in the pinned Linux CI environment and the documented local environment.
- [ ] Operator list/show/acknowledge/rearm work live and offline without manual state edits or unintended Docker actions.
- [ ] Sustained detection rejects the committed negative corpus and passes the positive corpus.
- [ ] Exact replay is deterministic, isolated, and honest about unavailable outcomes.
- [ ] Rule comparison and fake shadow evaluation cannot execute infrastructure actions.
- [ ] Tests cover interruption, cleanup, malformed data, missing metrics, state conflict, and migration.
- [ ] README documents installation, pinned images, tests, operator commands, thresholds, captures, replay, and recovery from interrupted work.
- [ ] A new verification report distinguishes unit, real Docker, actual CI, and offline replay evidence.
- [ ] Final handoff lists remaining limitations and the explicit approval gate for real planner evaluation.

Expected artifacts: implementation code, focused tests, CI configuration, image/dependency pins, state/event schema documentation, sanitized replay fixtures, operator runbook, progress/decision log, and final verification report. Do not overwrite the historical verification report to make old evidence look current.

## 11. Ready-to-Use Long-Horizon Goal

> Implement Patron's four-workstream reliability roadmap in LONG_TERM_PLAN.md: reproducible pinned Docker CI, safe incident inspection/acknowledgment/rearming, sustained evidence-based detection with false-positive regression coverage, and isolated deterministic replay with a non-executing fake shadow-planner comparison. Start by reproducing the existing eight-scenario baseline. Preserve deterministic policy and verification, resource isolation, and the current runtime/lab boundary. Work through G0-G5, recording decisions, tests, artifacts, and blockers as you go. Fix regressions before advancing and never substitute mocked success for required Docker or CI evidence. Do not add real model providers or new remediation actions. The task is complete only when the final qualification checklist is verified, documentation is updated, and a new evidence-backed verification report is delivered.
