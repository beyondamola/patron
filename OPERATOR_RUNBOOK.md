# Patron Operator Runbook

This runbook is for the local single-target Docker runtime. Operator attribution
is not authentication. Escalation means automated actions stopped, not that the
container recovered. Neither acknowledgment nor rearming directly changes Docker.

## Select the Correct Runtime

Use an explicit state path for all commands. The normal default is
`logs/incident_state.json`; managed lab runs use
`logs/scenarios/<scenario-id>/incident_state.json`. State resolution is explicit
CLI flag, then PATRON_STATE_PATH, then the default. Do not operate on another
runtime's state because the container display name looks familiar.

```bash
python -m harness inspect-docker --target TARGET
python -m harness incidents list --state-path STATE_PATH
python -m harness incidents show INCIDENT_ID --state-path STATE_PATH --json
```

Check the resource/container ID, incident type, status, attempts, suppression,
acknowledgment, predecessor, and evidence path. A same-name replacement has a
different Docker ID. Missing legacy identity retains suppression conservatively.
List/show are read-only and include historical resolved incidents from audit.

## Acknowledge Investigation

```bash
python -m harness incidents acknowledge INCIDENT_ID --state-path STATE_PATH \
  --actor local-operator --reason "Investigating the recorded failure" --json
```

Acknowledgment records attribution, reason, and timestamp only. Status, attempts,
suppression, policy, and Docker state are unchanged. For scripted delivery,
supply a canonical UUID with `--request-id` and retain it alongside the result.
Repeating the same request retrieves its durable result without applying twice.
Never reuse an ID for a different operation, incident, actor, or reason.

## Rearm After Investigation

First correct or understand the underlying cause outside Patron. Inspect Docker
again. Only the currently suppressed ESCALATED or FAILED incident can be rearmed.
OPEN, RUNNING, RESOLVED, stale, already-rearmed, and mismatched-generation
incidents are rejected. Ordinary resolved cooldown is not an operator rearm.

```bash
python -m harness incidents rearm INCIDENT_ID --state-path STATE_PATH \
  --reason "Cause reviewed and corrected" --dry-run --json
python -m harness incidents rearm INCIDENT_ID --state-path STATE_PATH \
  --reason "Cause reviewed and corrected" --wait 10 --json
```

Dry-run writes no state. Applied rearm preserves the historical terminal incident
and releases its suppression. The next failing observation creates a new ID linked
to its predecessor and uses normal policy/retry limits. A healthy observation
creates no incident and executes nothing. Repeated automatic escalation is a
reason to investigate, not to repeatedly rearm without fixing the cause.

## Pending and Conflicting Requests

A live runtime owns the state lock and consumes atomic request files between
iterations. It finishes an in-progress action before processing requests.
Offline mutations use the same lock and validation. A second runtime using the
same state path fails before collection.

`--wait` is bounded (0-300 seconds, default 5). PENDING and PENDING_AUDIT are not
success and return nonzero. Do not create a new request simply because a wait
expired. Inspect the original request first:

```bash
python -m harness incidents show INCIDENT_ID --state-path STATE_PATH \
  --request-id REQUEST_ID --json
```

A stale-revision REJECTED result is durable. Inspect the current state and submit
a new deliberate request with a new ID if still appropriate. Concurrent
requests can validly conflict; no accepted result should be silently lost.

## Shutdown and Persistence Errors

Use Ctrl+C on the owning runtime and wait for `shutdown complete`. Do not delete
the `.lock` file while a runtime may hold it: file presence is not lock ownership.
The kernel releases ownership when the process exits.

For corrupt/unsupported state, migration conflicts, or an incomplete audit tail:

1. Stop the owning runtime; retain the original state, audit, request directory,
   and any `.v0.bak` migration backup.
2. Inspect the reported file and error without deleting or resetting history.
3. Repair only from validated evidence or a known-good backup under deliberate
   operator review. Do not invent the missing part of a truncated event.
4. Resume using the same state path. Pending audit delivery is retried before
   later collection; verify the original request's result.

The tool intentionally does not offer automatic destructive repair. If a damaged
record cannot be reconstructed reliably, retain the evidence and investigate
before enabling remediation. Capture files interrupted before clean closure are
diagnostic only; start a new capture rather than appending or pretending closure.

## Unknown Evidence

Missing healthchecks produce `none`. Unavailable CPU/disk/dependency probes stay
unknown and do not prove recovery. A nonrunning exit-137 observation with no OOM
flag is an ambiguous SIGKILL cause: generic restart is withheld. If Docker later
reports OOMKilled, Patron escalates the OOM incident. If the cause stays unknown,
investigate manually; do not treat silence from the trigger as recovery.

For a measurement/configuration change, use `inspect-docker` and `watch --trace`
against the same target. CPU needs count AND elapsed-duration evidence. At default
10-second polling, three samples span 20 seconds, plus collection time. CPU
recovery hysteresis does not release an escalated incident's suppression.

## Lab and Offline Evidence

```bash
python -m scenarios run-all --verbose --capture
python -m harness replay validate CAPTURE_PATH
python -m harness replay run CAPTURE_PATH --output NEW_REPORT_PATH
```

The lab owns and cleans only labeled simulation resources. `--keep-resources`
retains them for debugging; `python -m scenarios cleanup` removes simulation-owned
resources, so first check whether another lab run is using them. Never prune the
Docker daemon or remove unrelated resources as part of incident control.

Replay uses temporary state/audit sinks and recorded action/verifier responses.
It cannot perform infrastructure remediation. Candidate comparison and fake
shadow output cannot authorize actions or claim unobserved recovery. See
SHADOW_EVALUATION.md for the separate approval gate before any real model work.
