# Offline Shadow Evaluation Contract

Status: deterministic fake candidates only. No provider SDKs, credentials,
network calls, model downloads, or paid evaluation are authorized by this plan.

## Reproducible Evaluation Record

Record these fields for each evaluation:

| Field | Required evidence |
| --- | --- |
| Corpus identity | Reviewed capture paths and content hashes; provenance and label origin |
| Configuration | Captured, baseline, and candidate detector fingerprints |
| Candidate identity | Fake mode or separately approved immutable implementation version |
| Context | Identical normalized schema; reviewed bounded/redacted logs |
| Schema validity | Count valid/malformed recommendations and bounded failure descriptions |
| Policy admissibility | Allowed/denied counts and reasons; policy is not candidate-controlled |
| Disagreement | Classification, decision, policy, and recommendation differences per observation |
| Denominators | Per-type baseline/candidate positives, total samples, missed/extra labels |
| Outcome evidence | Recorded reference only, or counterfactual unknown after divergence |
| Timing | Recorded runtime latency separately from candidate evaluation computation time |
| Limitations | Missing measurements, unknown onset, sample dependence, unsupported probe changes |

Current comparison reports cover fixed-observation recommendations. They do not
simulate a candidate runtime's retries or prove a candidate final lifecycle state.
`candidate_final_status` stays null. A different action cannot inherit the
recorded executor/verifier result. Downstream observations remain fixed recorded
data even when a different action might have changed reality.

The fake candidate modes are mirror, escalate, and malformed. Only known fake
modes are selectable through the CLI; no arbitrary module loading is supported.
Each call receives a deep copy of context. Its structured recommendation must
contain exactly decision, reason, and confidence within documented code limits.
Schema acceptance does not imply policy approval. Candidate output is never
passed to an executor or applied to live incident state.

## Separate Approval Gate for Real Planners

Before any real provider or local model evaluation, require explicit user
authorization, a fixed sanitized corpus, provider/data-sharing approval, finite
cost and wall-time caps, and review of the execution-disabled boundary. Compare
schema validity, policy admissibility, disagreements, and latency rather than
claiming recovery from a recommendation. Good scores never authorize live actions.

The committed 33-file synthetic corpus and all-eight live capture/replay checks
are available. CLI `report_metadata.computation_seconds` measures the complete
validation/comparison operation, not isolated candidate inference. Recorded
runtime metrics remain separate. Candidate-specific inference timing is not
measured by the pure offline API; do not present total comparison time as model
latency. Final G4 requirements review and G5 qualification remain open.
This document is not authorization to make provider calls.
