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

Default tests are fast and mock Docker interactions where practical:

```bash
python -m pytest
```

Docker integration tests are opt-in:

```bash
PATRON_RUN_DOCKER_INTEGRATION=1 python -m pytest -m integration
```

These tests create all eight actual Docker environments, verify classification, policy and final status, and assert container cleanup plus graceful Patron shutdown. They are sequential and require Docker Desktop/the local Docker daemon. Default tests skip them.

## Current Boundaries

This remains a local, single-target MVP. Resource statistics are sampled once per cycle; CPU detection does not yet require sustained load. Disk inspection uses `df` inside the container (unavailable tools produce an unknown metric). `patron.disk_path` and `patron.dependency` are optional measurement hints, not ownership requirements; default disk monitoring uses `/tmp`. Log classification uses bounded recent text patterns rather than application-specific parsers. Memory usage is currently unavailable/null. Only the lab's known unhealthy startup behavior is proven to recover on restart.

## Non-Goals

This project does not include Kubernetes, Ansible, web UI, database, cloud deployment, authentication, billing, multi-agent orchestration, random chaos testing, production-target support, or unrestricted shell-command execution.
