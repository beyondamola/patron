# G2 verification: operator incident control

Implementation commit: `6f0498c`. Date: 2026-09-10.
This verifies G2, not the complete roadmap. G3-G5 remain open.

## Verified behavior

- Incident list/show merges current state with audit-only history, with state-path
  provenance. Explicit paths override the environment and default path.
- Acknowledge records actor, reason, and timestamp without changing status,
  attempts, policy, or Docker state.
- Rearm accepts only the currently suppressed ESCALATED/FAILED incident. History
  remains terminal; a subsequent failure creates a new linked incident. A healthy
  collection does not create or execute anything.
- Known container generations have distinct suppression and cooldown. Unknown
  legacy identity remains conservatively suppressed until explicit operator action.
- Kernel file locking gives the runtime exclusive ownership. A second runtime
  fails before collection. Offline mutations take the same ownership lock.
- Concurrent producers publish independent atomic request files without overwriting
  an existing ID. The runtime applies requests between cycles. Stale revisions
  receive durable rejection results; accepted changes are not silently lost.
- State transitions and pending audit events are committed together. Interrupted
  delivery remains pending; repeat delivery checks stable event IDs. Duplicate
  requests remain idempotent after restart. The bounded result cache falls back
  to historical audit events for old results.
- Schema validation, migration backups, revision conflicts, dry-run, bounded waits,
  incomplete audit tails, and failed persistence have explicit failure paths.

## Evidence

| Check | Result |
| --- | --- |
| Default unit tests | 115 passed; eight scenario and one operator integration test skipped |
| Local real operator workflow after final fix | 1 passed in 11.85 seconds |
| Local final eight-scenario suite | 8 passed in 51.53 seconds |
| Normal CLI run-all during G2 qualification | All eight PASSED |
| scenarios list with actual daemon access | All eight registered and supported |
| Linux amd64 and arm64 CI | Unit, eight scenarios, real operator workflow, cleanup, and artifacts all passed |
| Local cleanup | No simulation containers/networks or Python harness/scenario processes remained |

Successful CI: https://github.com/beyondamola/patron/actions/runs/34536159885

The downloaded reports under `artifacts/g2-qualified` were checked using the
same strict exact-case validators: two eight-scenario reports and two operator
reports, with no failures or skips. They include state, runtime, and operator
output. Local reports include `artifacts/raw/g2-refresh-suite.xml` and
`artifacts/raw/g2-oom-refresh.xml`. Generated artifacts remain ignored by Git.

## Requirement mapping

| Contract | Tests / evidence |
| --- | --- |
| OPS-1 schema, identity, legacy migration | test_storage.py migration/backup/schema tests; test_control.py generation/cooldown tests |
| Read current and resolved history | test_offline_cli_applies_and_shows_state; test_resolved_audit_only_incident_can_be_acknowledged |
| Acknowledge leaves status/actions unchanged | test_acknowledgment_preserves_status_and_attempts; real OOM workflow preserves exited/OOM state |
| Rearm creates one linked incident | test_rearm_opens_one_linked_incident_and_preserves_history; real workflow checks exactly one successor |
| Healthy cycle after rearm does nothing | test_rearm_healthy_resource_does_not_create_incident |
| OPS-2 ownership and revision safety | test_runtime_checks_ownership_before_collection; test_runtime_checks_revision_before_collection; real second-process rejection |
| Stale requests do not release newer suppression | test_stale_request_rejected; test_old_generation_does_not_suppress_replacement |
| OPS-3 live/offline parity and bounded waits | test_live_owner_receives_pending_request; test_real_operator_workflow; live dry-run and pending-resubmit tests |
| Concurrent requests have explicit outcomes | concurrent producer tests; test_two_queued_requests_have_explicit_durable_outcomes; real parallel CLI commands |
| OPS-4 interrupted persistence/delivery | atomic replacement/fsync tests; test_audit_failure_leaves_pending_and_recovers; test_audit_write_then_crash_does_not_duplicate_event |
| Duplicate requests survive restart | test_duplicate_request_is_idempotent_across_restart; real duplicate request comparison |
| Corrupt state fails closed | test_corrupt_control_state_fails_without_modification; unknown schema tests |
| Isolation | test_operator_history_is_scoped_to_state_path; per-run state and owned-resource cleanup |
| No scenario regression | Eight real scenarios on local Docker and both CI architectures |

## Failures retained and corrected

The first G2 qualifications were not clean successes:

- Concurrent CLI submission reproduced a shared queue-lock rejection locally and
  in CI. Commit a230518 changed submission to atomic no-overwrite publication.
- CI exposed delayed OOM metadata: a generic stopped observation caused a restart,
  then resource-only cooldown hid the more specific OOM incident. Retained runtime
  logs established that sequence. Commit 6f0498c refreshes terminal Docker state
  after slower enrichment probes and scopes resolved cooldown to identical types.
  OOM qualification still requires all operator incidents to be ESCALATED with
  zero remediation attempts, so a hidden restart cannot satisfy the test.

Failed runs 34535483959 and 34535690136 remain in GitHub history. They were not
converted into successes through automatic retries, changed expected outcomes,
or weakened resource thresholds.

## Boundaries

This is a local POSIX file-based control mechanism, not authenticated remote
administration. Actor strings are attribution, not verified identities. Acknowledged
incidents remain subject to policy. Incomplete audit tails require preservation
and repair, not deletion. Pending requests may wait until the next cycle, and
conflicting revisions require explicit resubmission with a new request ID.

The collector refresh reduces the reproduced terminal-state race; it is not a
transactional Docker snapshot. Sustained evidence handling and negative-case
coverage are the next gate. No model-provider or new remediation action was added.
