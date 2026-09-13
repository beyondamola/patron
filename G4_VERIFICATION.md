# G4 Verification: Capture, Replay, and Fake Shadow

Date: 2026-09-13. Status: verified, including the OOM correction and final code CI.
Qualified code checkpoint: c1cc647. See G5_VERIFICATION.md for final handoff.
Earlier checkpoints and failed runs below are retained as historical evidence.

## Evidence Inventory

| Evidence | Verified result |
| --- | --- |
| Local unit suite at f8f5ce7 | 298 passed, 9 opt-in skipped; 6.73s |
| Local all-eight Docker at f8f5ce7 | 8 passed, 80.02s; artifacts/raw/g4-history-integration.xml; replay/provenance and owned cleanup asserted |
| Committed synthetic corpus | 33 captures, three identical replays each; generator plus manifest byte-identical |
| Local all-eight Docker at 545a6ac | 8 passed, 67.27s; artifacts/raw/g4-provenance-integration.xml |
| Normal run-all at 545a6ac | 8 PASSED; artifacts/raw/g4-provenance-run-all.log; capture/provenance/cleanup reviewed in PROGRESS.md |
| CI at 545a6ac | Run 34673684287 successful; downloaded artifacts/g4-provenance-qualified |
| CI unit reports | Exactly 290 cases on Python 3.9 and 3.12, no failed/error/skipped cases |
| CI Docker reports | Exactly 8 scenarios plus 1 operator case on each Linux architecture; no failures/errors/skips |
| CI replay artifacts | All 16 retained replay reports match and include correlated lab timing |
| CI at f8f5ce7 | Run 34715607993 failed the amd64 operator test: an ambiguous exit-137 snapshot caused an unintended stopped-container restart before OOM escalation |

CI links:
- https://github.com/beyondamola/patron/actions/runs/34673684287
- https://github.com/beyondamola/patron/actions/runs/34715607993

## Requirement Mapping

| Requirement | Implementation and evidence |
| --- | --- |
| REP-1 normalized versioned evidence | capture.py explicit snapshot fields, bounded/redacted logs, config/version/initial-state header; test_capture.py |
| REP-2 causal sequence | runtime stage hooks, separate verifier observations, operator events; test_capture_validation.py references/order/type rejection |
| Historical control prerequisites | control_history contains scoped audit-only incidents and prior request results; test_audit_only_acknowledgment_and_old_request_replay |
| REP-3 isolation | Explicit recorded adapters and resolved temporary state/audit root; tests forbid live Docker constructors, subprocess, socket, sleep and runtime clocks |
| REP-4 exact replay | Trigger/context/planner/policy/transition comparison with recorded executor/verifier responses; all-eight synthetic and real capture tests |
| REP-4 counterfactual comparison | comparison.py; changed candidate action leaves downstream outcome unknown; no candidate executor or lifecycle |
| REP-5 metrics | replay_metrics.py, replay_provenance.py; test_replay_reports.py and test_replay_provenance.py cover denominators, timing separation, unknowns and CLI exit status |
| REP-6 corpus | tests/fixtures/replay/manifest.json, tests/test_replay_corpus.py; retries, cooldown, suppression, rearm, collection failure, restart continuity and all detector labels |
| REP-7 fake-only evaluation | shadow.py validates bounded recommendations on copied context; test_shadow.py; SHADOW_EVALUATION.md authorization contract |

Validation rejects sequence gaps, unsupported schemas, missing initial state,
malformed snapshots, cross-cycle/incident references, unapproved actions, missing
independent verification observations, malformed historical control evidence,
partial final writes, and missing run closure. Structural validation does not
attest that a captured observation is true or guarantee exact replay eligibility.

## Scope of the Claims

- Repeated exact reports reproduce recorded decisions and lifecycle state.
  Executor/verifier responses are replay inputs, not new Docker recovery tests.
- Semantic comparison excludes storage paths, wall timestamps, and stage latency.
  Coverage duration alone permits one microsecond of origin-conversion tolerance;
  thresholds, counts, decisions and state remain exact.
- Missing onset is null. Optional lab JSONL provides separately correlated timing
  based on aligned UTC clocks. Restart-loop setup onset may precede capture.
- A collector exception with no observation is diagnostic evidence only and is
  explicitly rejected for exact replay. Normalized collection-error observations
  replay without being counted as healthy recovery.
- Historical controls need captured historical evidence. New headers include it
  with bounded size; older captures cannot recover inputs that were never saved.
- Comparisons use fixed observations and cannot prove a candidate's final status.
  All candidate outcomes remain unknown; divergence invalidates downstream
  recorded outcome attribution. Computation time is not isolated model latency.
- Synthetic corpus agreement is regression evidence, not a production accuracy
  estimate. Redaction is pattern-based, not comprehensive sensitive-data detection.
- No real provider SDKs, credentials, billable calls, or model execution were added.
  Future real evaluation requires the separate explicit approval gate.

## Correction History and Final Qualification

The original failed-run artifacts are preserved under artifacts/g4-history-failed.
The correction withholds generic restart on exit 137 without positive OOM evidence;
it does not infer OOM from SIGKILL. All-eight integration now checks complete scoped
incident history, not merely the eventual matching incident, so an earlier wrong
classification or forbidden restart also fails qualification.

Follow-up run 34715967546 exposed missing OOM metadata for the entire injection
confirmation period, not merely a short delay. The runtime correctly withheld
generic restart, and the lab reported INJECTION_FAILED. Its artifacts remain in
artifacts/g4-oom-guard-failed and the failed-job log is
artifacts/raw/g4-oom-guard-ci-failure.log. A supervised child-allocation fixture is
was subsequently qualified; OOM proof and expected policy were not weakened.

On 2026-09-13 the supervised fixture passed local focused OOM qualification
(17.25s) and all eight scenarios plus the real operator workflow (9 cases,
101.08s). Strict XML verification found no failures/errors/skips. Evidence:
artifacts/raw/g5-supervised-full.xml. Unit result: 301 passed, 9 opt-in skipped.
This local evidence was followed by three independent successful workflows at
4265487: 34741568850, 34741772883, and 34741791860. Downloaded reports show exactly
eight scenarios plus one operator case on each Linux architecture, zero skips,
and 16 matching scenario/replay reports per workflow.

Final code c1cc647 also passed workflow 34742002479: 304 unit cases on Python 3.9
and 3.12, and all eight scenarios plus operator qualification on both Linux
architectures, with zero skipped cases. Artifacts are retained under
artifacts/g5-final-qualified. Local final code passed 304 unit tests and nine
real Docker/operator cases in 99.64s. G4 requirements mapping above is complete;
the operational handoff and consolidated limits are in G5_VERIFICATION.md.
