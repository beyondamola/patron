# State, Audit, Capture, and Report Formats

These are local diagnostic formats, not authenticated messages or a remote API.
Do not edit live state, merge captures, or use replay output as permission to
execute an action. The deterministic policy remains authoritative.

## State Version 1

The authoritative reader/writer is `harness/incident.py`. The state file contains:

| Field | Meaning |
| --- | --- |
| schema_version | Integer 1; unsupported versions fail closed |
| revision | Nonnegative revision advanced by a committed persistence operation |
| incidents | Resource-name keyed current incidents, including terminal suppression |
| resolved_at | Per-resource cooldown timestamps |
| observed_generations | Resource name to observed immutable Docker container ID |
| resolved_generations | Container generation associated with each cooldown |
| resolved_incident_types | Incident type associated with each cooldown |
| control_results | Durable operator requests and their results |
| outbox | Committed operator events awaiting durable audit delivery |
| audit_path | Audit destination associated with this state |

Incident fields include identity, resource name/type, incident type, lifecycle
status, attempt count, timestamps, action and verification evidence, container
generation, acknowledgments, and rearm/predecessor metadata. The implementation's
`Incident.from_dict` is the validation contract; an acknowledgment is not a status.

Runtime and offline control mutations share the same state-path ownership lock.
The runtime processes an adjacent atomic control inbox between cycles. A request
contains request_id (canonical UUID), incident_id, expected_revision, operation,
reason, actor, and timestamp. Stable request IDs make repeated delivery idempotent.
State replacement is atomic and fsynced; audit delivery is a separate durable
step. A pending outbox is not fully delivered success.

Legacy version 0 is read conservatively. Before first migration write, original
bytes are retained in `<state-path>.v0.bak`; a conflicting existing backup stops
migration. Missing generation identity does not silently release suppression.
Do not delete state or its backup to work around a validation error.

## Audit and Scenario Results

Incident audit JSONL contains incident snapshots and may also contain runtime
errors and `operator_control` records. Operator records use schema_version 1,
event_id equal to the request UUID, state_path, request, and result. Readers must
check event kind rather than assume every line is an incident snapshot.

Historical incident snapshots remain readable, including resolved incidents no
longer in active state. They are not complete replay inputs: they do not contain
every healthy observation, verifier read, or initial state.

Scenario results are a separate JSONL stream. Injection time is lab knowledge,
not a value injected into the Patron context or runtime metrics. Integration
tests retain `logs/scenarios/<id>/result.jsonl`; normal lab commands use
`logs/scenario_results.jsonl`. Both can be supplied explicitly to replay reporting.

## Capture Version 1

Opt-in `--capture` exclusively creates a new file with mode 0600. Every event is
flushed and fsynced. Each line is one JSON object with these envelope fields:

| Field | Meaning |
| --- | --- |
| schema_version | Integer 1 |
| run_id | Stable capture-run identity |
| sequence | Contiguous integer starting at 0 |
| event | One of the event kinds below |
| utc_time | Timezone-aware timestamp |
| monotonic_offset | Elapsed offset from capture origin |
| observation_id | Parent polling-observation sequence, or null |
| incident_id | Causal incident identity, or null |
| payload | Event-specific object |

`run_start` stores effective detector configuration and its fingerprint,
collector_version 1, redaction_version 1, initial state, and runtime settings
(target, dry_run, cooldown_seconds, mode). Exact replay requires mode `watch` or
`cycles` so shutdown persistence can be reproduced. Older captures lacking mode
need to be recaptured; they are not silently assigned a mode.

A normal cycle records `cycle_start`, zero or more paired `control` events,
`observation`, `trigger`, and `cycle_end`. An incident can additionally record
`transition`, `context`, `plan`, `policy`, `action_requested`, `execution`,
`verification_observation`, `verification`, and its final `transition`.
`cycle_end` contains the result and resulting state. `run_end` closes the capture
with final state. A missing final newline or run_end is incomplete evidence.

Normalized observations use the explicit field list in `harness/capture.py`.
They include resource name/ID, existence, runtime/health/exit/restart state,
OOM, memory and CPU metrics/quota, disk occupancy, dependency evidence, bounded
recent logs, parsed error patterns, ports/network mode, start timestamp,
observation offset, and probe errors. No raw inspect object, environment map, or
arbitrary Docker labels is copied. Unknown values remain null or documented
`none` health status, not successful measurements.

Verification reads are distinct from polling observations and refer to their
parent observation and incident. Exact replay recomputes trigger/context/planner/
policy/lifecycle behavior but consumes recorded executor and verifier responses;
it does not claim to rerun the infrastructure action or remeasure recovery.

Limits: 1MB per record; 20 recent log lines of at most 1,000 characters each;
general strings at most 4,000 characters; lists/maps at most 1,000 entries;
nesting at most 12. Credential-pattern redaction is not comprehensive DLP.
Review diagnostic data before sharing. Redaction can make an input unsuitable
for exact replay; a mismatch must be investigated, not ignored.

Collection errors returned as normalized snapshots can replay. A collector
exception before any observation is retained as an error cycle for diagnosis,
but exact replay rejects it with `missing collector observation`. Structural
validation alone does not prove replay completeness or factual authenticity.

## Report Version 1

Exact reports include validation counts, cycle results, recorded stage metrics,
and per-type classification/final-state agreement with denominators. Agreement
means the recorded computation reproduced, not ground-truth accuracy. Behavioral
comparison excludes wall timestamps, storage paths, and stage latency. Only
window coverage durations allow an absolute one-microsecond conversion tolerance.

Comparison reports evaluate fixed observations, not a candidate lifecycle. They
include classification counts, missed/extra samples relative to the baseline,
plans, policy results, action differences, malformed plans, and recorded attempts.
Candidate final states and final-state agreement remain unknown. After divergence,
downstream outcome evidence is `counterfactual_unknown`. No candidate can inherit
a recovery caused by the recorded action.

CLI-only `report_metadata` contains elapsed computation time, excluding output
serialization. Exclude that object when checking semantic repeatability. Recorded
runtime stage latency remains separate; total comparison time is not isolated
candidate inference latency.

Optional `--scenario-results` adds `lab_provenance`. Correlation requires incident
ID, target, incident type, and configuration fingerprint. Duplicate matches,
unconfirmed injections, or reversed timestamps fail. Known detection delay is
computed from lab injection UTC to the captured incident's creation UTC, assuming
aligned clocks. Setup injection may precede capture and is explicitly marked.
Unknown onset remains null. This information never changes runtime measurements
or supplies candidate detection/recovery proof. Results input is bounded to 64MB
with complete JSONL records of at most 64KB.

## Recovery and Compatibility

Preserve corrupt or partial files for diagnosis. Never truncate audit history to
make a replay or mutation succeed. Use a new capture path after interruption.
To release terminal suppression, use the incident CLI with an explicit state
path and reason; do not modify JSON. See README's operator workflow for commands.
The checked-in fixture manifest documents synthetic origins and expected results;
large live captures remain in local or retained CI artifacts rather than Git.
