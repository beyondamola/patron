# Patron

Patron is a tiny Python MVP for an AI-assisted infrastructure remediation harness.

It runs a local Docker remediation loop:

```text
Collector -> Trigger -> Context Manager -> Rule Planner -> Policy Engine -> Executor -> Verifier -> Audit Logger
```

It also includes a separate deterministic failure-simulation package. Scenarios modify Docker state; Patron observes Docker normally. The scenario package does not call Patron trigger, planner, policy, executor, or verifier internals.

## Setup

```bash
cd patron
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pytest
```

## Patron Runtime

Run one remediation cycle:

```bash
python -m harness run
python -m harness run --dry-run
python -m harness run --verbose
python -m harness run --trace
```

Run the long-running daemon:

```bash
python -m harness watch
python -m harness watch --interval 2 --verbose
```

Ctrl+C requests graceful shutdown. Patron finishes the current loop iteration, flushes logs, persists incident state, prints a shutdown message, and exits.

## Triggers

Triggers are registered objects with:

```text
incident_type
evaluate()
build_metadata()
```

Built-in incident types:

```text
CONTAINER_STOPPED
CONTAINER_UNHEALTHY
CONTAINER_RESTART_LOOP
CONTAINER_OOM_KILLED
CONTAINER_HIGH_CPU
CONTAINER_DISK_FULL
CONTAINER_BAD_CONFIG
CONTAINER_DEPENDENCY_DOWN
```

New trigger implementations can be registered without changing `harness/runtime.py`.

Classification rules:

```text
CONTAINER_STOPPED       running = false
CONTAINER_UNHEALTHY     running = true and health = unhealthy
CONTAINER_RESTART_LOOP  restart_count >= 3
```

`CONTAINER_RESTART_LOOP` is evaluated before stopped/unhealthy triggers and is escalated by default. Restart loops usually indicate a bad image, missing dependency, or crash-looping application, so Patron does not blindly restart them.

## Rule Planner And Policy

The current planner is deterministic. No external LLM is used.

Planner decisions:

```text
CONTAINER_STOPPED       restart_container
CONTAINER_UNHEALTHY     restart_container
CONTAINER_RESTART_LOOP  escalate
```

Allowlisted actions:

```text
restart_container
escalate
```

Unknown actions are denied and never executed.

Policy also prevents a planner from restarting escalation-only incident types. Escalation verification checks the resulting incident state, rather than trusting a planner recommendation.

## Verification

Verification is deterministic and incident-aware:

```text
CONTAINER_STOPPED       container is running
CONTAINER_UNHEALTHY     container is running and health is healthy
CONTAINER_RESTART_LOOP  incident is escalated
```

## Metrics

Patron audit records include metrics for future planner comparisons:

```text
incident_type
detection_latency_seconds
planning_latency_seconds
execution_latency_seconds
verification_latency_seconds
attempts
final_status
```

Runtime `collection_trigger_latency_seconds` measures collection and trigger evaluation. Runtime `detection_latency_seconds` is null because the runtime does not know when an external failure was injected. Lab result latencies measure injection to the matching audit record/outcome. Audit records are lifecycle snapshots, so retries can produce multiple records for the same incident id.

## Failure Scenarios

List scenarios:

```bash
python -m scenarios list
```

Run one scenario:

```bash
python -m scenarios run stopped --verbose
python -m scenarios run unhealthy --verbose
python -m scenarios run restart_loop --verbose
python -m scenarios run oom_killed --verbose
python -m scenarios run high_cpu --verbose
python -m scenarios run disk_full --verbose
python -m scenarios run bad_config --verbose
python -m scenarios run dependency_down --verbose
```

Run all scenarios:

```bash
python -m scenarios run-all --verbose
python -m scenarios run-all --verbose --stop-on-failure
```

Clean up simulation-created Docker resources:

```bash
python -m scenarios cleanup --verbose
```

Scenario coverage:

```text
stopped          CONTAINER_STOPPED          restart_container -> RESOLVED
unhealthy        CONTAINER_UNHEALTHY        restart_container -> RESOLVED
restart_loop     CONTAINER_RESTART_LOOP     escalate          -> ESCALATED
oom_killed       CONTAINER_OOM_KILLED       escalate          -> ESCALATED
high_cpu         CONTAINER_HIGH_CPU         escalate          -> ESCALATED
disk_full        CONTAINER_DISK_FULL        escalate          -> ESCALATED
bad_config       CONTAINER_BAD_CONFIG       escalate          -> ESCALATED
dependency_down  CONTAINER_DEPENDENCY_DOWN  escalate          -> ESCALATED
```

Resource scenario safety:

```text
oom_killed  uses a strict Docker memory limit
high_cpu    capped at one CPU and 64 MiB, burner stops after 90 seconds
disk_full   fills a bounded tmpfs path inside the container
```

No scenario uses broad Docker cleanup or touches non-simulation containers.

Scenarios are self-contained. They create their own containers, launch Patron in managed mode by default, inject the failure, observe Patron's response, write results, shut Patron down, and clean up simulation-owned resources.

Managed mode stores Patron subprocess output in:

```text
logs/scenarios/<scenario-id>/patron.log
```

Each managed subprocess uses its own `logs/scenarios/<scenario-id>/incident_state.json`. Repeated runs therefore have independent retry/cooldown state even when they use the same target name. Incident audits remain in `logs/incidents.jsonl`. The dependency service uses nginx; Alpine's BusyBox build does not provide an HTTP server applet.

Use external Patron mode only when you want to run Patron yourself:

```bash
python -m scenarios run unhealthy --external-patron --verbose
```

The scenario prints the exact `python -m harness watch --target ...` command to run.

## External Two-Terminal Workflow

Terminal 1:

```bash
source .venv/bin/activate
python -m harness watch --target patron-sim-unhealthy --interval 1 --verbose --trace
```

Terminal 2:

```bash
source .venv/bin/activate
python -m scenarios list
python -m scenarios run unhealthy --external-patron --verbose --trace
```

Expected stopped-container flow:

1. Scenario creates `patron-sim-stopped` and confirms it is running.
2. Scenario stops the container.
3. Scenario confirms Docker reports it as exited.
4. Patron detects `CONTAINER_STOPPED`.
5. Patron plans and executes `restart_container`.
6. Patron verifies recovery.
7. Scenario independently observes the container running again.
8. Patron writes `logs/incidents.jsonl`.
9. Scenario writes `logs/scenario_results.jsonl`.

## Scenario Resources

Scenario-created containers carry labels:

```text
patron.simulation=true
patron.scenario=<scenario_name>
patron.scenario_id=<uuid>
patron.managed=true
```

Cleanup only removes containers with `patron.simulation=true`. It does not run broad Docker cleanup commands and does not remove unrelated images, networks, volumes, or user containers.

Labels are only for simulator ownership, cleanup, debugging, and result correlation. Patron does not require labels to observe or remediate a container.

Scenario defaults:

```text
stopped       -> patron-sim-stopped
unhealthy     -> patron-sim-unhealthy
restart_loop  -> patron-sim-restart-loop
oom_killed    -> patron-sim-oom-killed
high_cpu      -> patron-sim-high-cpu
disk_full     -> patron-sim-disk-full
bad_config    -> patron-sim-bad-config
dependency_down -> patron-sim-dependency-app
```

Before creating a target, a scenario checks for an existing container with the same name. Simulation-owned containers are safely replaced. Non-simulation containers are never overwritten; choose another target with `--target`.

`--keep-resources` preserves scenario containers for debugging.

## Debugging Docker Truth

Use Patron's collector view to inspect the exact fields triggers can see:

```bash
python -m harness inspect-docker --target patron-sim-unhealthy
```

Run Patron and scenarios against the same explicit target:

```bash
python -m harness watch --target patron-sim-unhealthy --interval 1 --verbose --trace
python -m scenarios run unhealthy --target patron-sim-unhealthy --external-patron --verbose --trace
python -m scenarios run restart_loop --target patron-sim-restart-loop --external-patron --verbose --trace
```

Docker health status only exists when a container has a healthcheck configured. If `has_healthcheck=false`, Patron reports `health_status=none`, and `CONTAINER_UNHEALTHY` cannot fire.

Restart-loop detection requires `restart_count >= 3` in the collector output. The restart-loop scenario waits for Docker's restart count to cross that threshold before it claims injection succeeded.

If Patron and a scenario use different container names, detection will fail. Compare the scenario's verbose pre/post state with `inspect-docker` output to verify the same container id and labels.

## Results And Logs

Patron incident audit records:

```text
logs/incidents.jsonl
```

Patron persisted incident state:

```text
logs/incident_state.json
```

Scenario result records:

```text
logs/scenario_results.jsonl
```

Scenario result statuses:

```text
PASSED
FAILED
TIMED_OUT
SETUP_FAILED
INJECTION_FAILED
CLEANUP_FAILED
```

## Cooldown

Patron suppresses recently resolved incidents for 60 seconds. Re-running a scenario too quickly may prevent Patron from evaluating the trigger.

Managed scenarios use a fresh state file for every run. External mode still respects the external runtime's cooldown. `--reset-simulation-state` is a compatibility flag; it never edits external state. Escalated/failed incidents remain suppressed in persisted runtime state until operator intervention. Use a separate `PATRON_STATE_PATH` when starting an independent runtime.

## Manual Recovery

If a scenario is interrupted:

```bash
python -m scenarios cleanup --verbose
```

For a restart-loop container that was not cleaned up:

```bash
docker update --restart no patron-sim-restart-loop
docker rm -f patron-sim-restart-loop
```

For the stopped demo container:

```bash
docker start patron-sim-stopped
```

## Tests

Install the pinned test environment with `python -m pip install -r requirements-dev.txt`.
Python 3.9 through 3.12 is the initial compatibility target; CI tests 3.9 and 3.12.

Default tests are fast and mock Docker interactions where practical:

```bash
python -m pytest
```

Docker integration tests are opt-in:

```bash
PATRON_RUN_DOCKER_INTEGRATION=1 python -m pytest -m integration
```

These tests create all eight actual Docker environments, verify classification, policy and final status, and assert container cleanup plus graceful Patron shutdown. They are sequential and require Docker Desktop/the local Docker daemon. Default tests skip them.

### Continuous Integration

The private repository is `beyondamola/patron`. GitHub Actions runs separate unit
jobs and real Docker jobs on Linux amd64 and arm64. Docker jobs explicitly enable
strict mode: missing Docker, missing scenarios, failures, or skipped cases fail
the job. There are no automatic retries. Image downloads have their own preflight
timeout; each scenario has a 120-second observation timeout and the job has a
20-minute limit.

All scenarios use immutable OCI image indexes from `scenarios/images.py`. Both
indexes were resolved from the locally verified images and inspected with
`docker buildx imagetools inspect` on 2026-09-10:

| Image | Index digest | Verified manifest platforms |
| --- | --- | --- |
| nginx (1.31.1) | `sha256:5aca99593157f4ae539a5dec1092a0ad8762f8e2eb1789085a13a0f5622369f6` | linux/amd64, linux/arm64 |
| Alpine (3.20.10) | `sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` | linux/amd64, linux/arm64 |

Manifest availability does not itself prove execution on both platforms. See
`PROGRESS.md` for actual workflow evidence. Pin updates require the full unit and
Docker suites; do not replace digests with floating tags.

CI adds `patron.ci_run_id` to all resources. Its final cleanup filters and
rechecks that exact ID plus `patron.simulation=true`, including dependency
containers, networks, and volumes. It never cleans another run's resources.
Workflow artifacts retain sanitized test reports, scenario results, runtime
output, and environment/image information for 14 days. Logs are bounded and
common credential patterns are redacted; do not put real credentials into lab
containers. Local logs are ignored by Git and are not uploaded by a local test.

`LONG_TERM_PLAN.md` is the implementation contract; `PROGRESS.md` tracks gates.

## Current Boundaries

Runtime state ownership: `run` and `watch` accept `--state-path`. An explicit path
overrides `PATRON_STATE_PATH`, otherwise the default is `logs/incident_state.json`.
Only one runtime may own a state path; a second process fails before collection.
The `.lock` file may remain after shutdown; ownership is a kernel lock, not the
file's presence. Do not delete or replace it while Patron is running.

State writes use schema version 1 and revision checks. On first write of a legacy
state file, Patron preserves a byte-for-byte `.v0.bak` backup. Unknown/corrupt
schemas and stale revisions fail closed. Back up state before manual maintenance
and stop its runtime first; do not delete incident history to bypass suppression.
Operator commands:

```bash
python -m harness incidents list --state-path logs/incident_state.json
python -m harness incidents show INCIDENT_ID --json
python -m harness incidents acknowledge INCIDENT_ID --reason "Investigating"
python -m harness incidents rearm INCIDENT_ID --reason "Cause corrected" --dry-run
python -m harness incidents rearm INCIDENT_ID --reason "Cause corrected"
```

All commands accept `--state-path` and `--json`. Mutations also accept `--actor`,
`--request-id`, `--dry-run`, and `--wait` (0-300 seconds, default 5). Acknowledge
adds metadata without changing status or attempts. Rearm only releases the current
ESCALATED/FAILED incident's suppression; it does not restart Docker. A subsequent
failure creates a new linked incident. A healthy cycle creates nothing.

A live runtime processes atomic requests in `<state-path>.requests` between
cycles. Offline commands take the same state lock and apply the same validation.
Pending and pending-audit responses exit nonzero; they do not mean success.
Inspect a request with `incidents show INCIDENT_ID --request-id REQUEST_ID`.
Reuse the same request ID and operation to retrieve its result without applying
it twice. A stale state revision is rejected and requires a new request after
inspection. Keep request IDs with operator records.

Operator changes and pending audit events are committed together. If audit logging
fails, no new automated action is allowed through that cycle; pending delivery is
retried before later collection. An incomplete audit tail is preserved and blocks
append rather than being silently discarded. Stop the owning runtime, preserve a
copy of the damaged log, and repair the incomplete final record before resuming.
Do not delete state or history to bypass this error.

Suppression and resolved cooldown distinguish known Docker container IDs. A new
container with the same name does not inherit the old generation's suppression.
Legacy incidents without a known container ID remain suppressed until explicitly
rearmed. Rearming an already-observed replacement's predecessor is rejected; it
cannot release the replacement's suppression. Acknowledgment is a local operator
label and reason, not authentication or a change in policy authority.

The separate opt-in real-process qualification runs live and offline operator
commands against a simulation-owned OOM container, including concurrent requests,
duplicate IDs, restart persistence, and state ownership rejection:

```bash
PATRON_RUN_DOCKER_INTEGRATION=1 python -m pytest -m operator_integration
```

It is also required in both CI Docker jobs, independently of the exact eight-case
scenario report. Default tests skip both types of integration tests.

This remains a local, single-target MVP. Resource statistics are sampled once per cycle; CPU detection does not yet require sustained load. Disk inspection uses `df` inside the container (unavailable tools produce an unknown metric). `patron.disk_path` and `patron.dependency` are optional measurement hints, not ownership requirements; default disk monitoring uses `/tmp`. Log classification uses bounded recent text patterns rather than application-specific parsers. Memory usage is currently unavailable/null. Only the lab's known unhealthy startup behavior is proven to recover on restart.

## Non-Goals

This project does not include Kubernetes, Ansible, web UI, database, cloud deployment, authentication, billing, multi-agent orchestration, random chaos testing, production-target support, or unrestricted shell-command execution.
# Detector Configuration

## Experimental Capture

`python -m harness run --capture logs/captures/run.jsonl` and
`python -m harness watch --capture logs/captures/watch.jsonl` opt into a separate
normalized JSONL stream. Use a new path for every run; existing files are never
overwritten. Captures include initial state, healthy/error observations, trigger
decisions, context/plans/policy, action requests/results, individual verifier
reads, operator requests, cycle state, and a clean shutdown marker. Dry runs
record skipped actions. A capture write failure stops the current execution path.

`python -m scenarios run unhealthy --capture --verbose` stores the managed
runtime capture at `logs/scenarios/<scenario-id>/capture.jsonl`. The same option
is available for `run-all`. Scenario result/injection timestamps remain separate
from runtime observations; unknown runtime onset is not filled from the lab.

Raw inspect, environment variables, and arbitrary Docker labels are omitted.
Log capture is bounded and applies credential-pattern redaction, but this is not
a guarantee that arbitrary application text contains no sensitive information.
Treat captures as local diagnostic data and review before sharing. Capture
validation is available with `python -m harness replay validate <capture-path>`.
It checks state/observation types, sequence and incident references, cycle/action
ordering, required verifier observations, and clean closure. Validation does not
execute Docker or alter the input. Initial exact replay is available through
`python -m harness replay run <capture-path> --output <new-report-path>`.
It recomputes trigger/context/rule-planner/policy and lifecycle decisions using
recorded execution/verification responses, with temporary state and audit sinks.
The report compares behavioral state, not storage paths, wall-clock timestamps,
or stage latency; recorded latency is reported separately. Window coverage is
compared at microsecond precision after monotonic-origin conversion.

Use a fresh capture: older captures lacking runtime mode cannot reproduce the
watch shutdown persistence step and are rejected with a missing-evidence error.
Recorded operator requests are replayed through the normal control inbox in
the temporary directory. Focused tests cover acknowledgment/rearm, retries,
suppression, cooldown boundaries, and initial-state restart continuity.
This is still G4 work in progress: the checked-in replay corpus, counterfactual
comparisons, fake shadow evaluation, and full live/CI replay qualification remain
pending. Unsupported event sequences fail rather than claim a matching replay.

Offline comparison is available:

```bash
python -m harness replay compare capture.jsonl \
  --baseline-config baseline.json --candidate-config candidate.json \
  --fake-candidate mirror --output comparison.json
```

Fake modes are `mirror`, `escalate`, and `malformed`. Reports contain per-type
sample denominators, classification/action/policy differences, and malformed
recommendations. Differences return a nonzero exit code. Outputs must be new
files. No executor or live incident registry is used. After a changed decision,
downstream outcome evidence is `counterfactual_unknown`; candidate final status
is never inferred from a recorded restart. Changed measurement paths,
dependencies, or log-evidence TTL require a new capture and cannot reuse old
measurements. See `SHADOW_EVALUATION.md` for scope and the separate approval gate
for any future real planner evaluation.

`harness run`, `harness watch`, `harness inspect-docker`, `scenarios run`, and
`scenarios run-all` accept `--config path/to/detectors.json`. Omitted settings
use validated defaults. For example:

```json
{
  "cpu_threshold": 80,
  "cpu_window_seconds": 10,
  "cpu_min_samples": 3,
  "cpu_max_gap_seconds": 15,
  "cpu_recovery_threshold": 60,
  "cpu_recovery_seconds": 5,
  "cpu_recovery_samples": 2,
  "restart_loop_threshold": 3,
  "disk_threshold": 90
}
```

CPU detection requires consecutive valid samples meeting both the count and
duration requirements. At the default ten-second polling interval, three
samples span at least twenty seconds, plus collection time. A one-shot `run`
does not establish a sustained CPU window. Missing readings, stale samples,
excessive gaps, and replacement containers reset unconfirmed evidence. CPU
percent uses Docker's one-logical-CPU denominator, not total host utilization.
Recovery hysteresis does not rearm an escalated incident.

The polling interval must be below `cpu_max_gap_seconds`, leaving room for
collection duration. For `--interval 30`, explicitly configure a larger gap.
Slow collection can still break the window; trace output reports its coverage
and sample count. Invalid or nonfinite settings fail at startup.

Managed scenarios write their exact settings to
`logs/scenarios/<scenario-id>/detectors.json` and pass that file to Patron.
External mode prints a command referencing the same file. Audit and scenario
results include the effective settings and a SHA-256 configuration fingerprint.

Collector log evidence is limited to the current container start and the last
`log_evidence_seconds` (default 60). Only timestamped Docker log entries count;
old, undated, and future entries are discarded. Missing or invalid start times
produce no log evidence. CPU quota/period and NanoCpus are exposed separately.
`probe_errors` explains unavailable logs, CPU, disk, or dependency observations.
Failed dependency inspection is unknown, not evidence of a stopped dependency.
Optional `disk_path` (absolute path) and `dependency` settings override discovery
labels. Labels remain optional for collection. Disk probes use literal argv,
and unavailable probes remain null rather than zero utilization.

Run `python -m ci.detector_corpus` for the labeled synthetic detector regression
report in `artifacts/raw/detector-corpus.json`. It includes per-type positive and
negative sample counts, false positives/negatives, and full predicate traces.
These fixtures test classification and planner/policy recommendations only;
they are not infrastructure recovery evidence or estimates of field accuracy.
