# G3 Verification: Sustained Detection and Evidence Quality

Date: 2026-09-11. Qualified implementation: `13dc0f4` and its ancestors.
G3 is verified within the documented Docker/Python environments. This is not
completion of G4 capture/replay or G5 final qualification.

## Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Docker-free unit suite | 179 passed, 9 opt-in skipped | `python3 -m pytest -q`, 0.71s |
| Synthetic detector corpus | 26 cases, 53 samples, no unexpected classifications/actions | `artifacts/raw/detector-corpus.json` |
| Local Docker integration | All 8 passed, no skips | `artifacts/raw/g3-evidence-suite.xml`, 66.07s |
| Real operator processes | 1 passed, no skips | `artifacts/raw/g3-operator.xml`, 12.31s |
| Normal CLI run-all | All 8 PASSED | `logs/scenario_results.jsonl`, 06:10:13-06:11:16 UTC |
| Scenario availability | All 8 supported with daemon access | `python3 -m scenarios list` |
| Linux AMD64 and ARM64 | Exactly 8 scenario tests and 1 operator test each, no failures/skips | `artifacts/g3-qualified/docker-*/raw/` |
| Linux Python 3.9 and 3.12 | Unit and corpus lanes passed | `artifacts/g3-qualified/unit-*/raw/` |

Actual CI run: https://github.com/beyondamola/patron/actions/runs/34568818075
Downloaded XML reports were checked with `ci.checks.validate_report`, not inferred
from job color. Both downloaded corpus reports contain 53 samples and no failures.
Local environment remains macOS arm64, Python 3.9.6, Docker Desktop engine 29.5.2;
CI uses pinned image digests and Ubuntu 24.04 runners. This does not establish
support for every Docker version or resource quota.

## Requirement Mapping

| Requirement | Implementation | Tests / evidence |
| --- | --- | --- |
| DET-1 validated effective config | `harness/config.py`, CLI, registry, managed child configuration | Invalid values, fingerprint round-trip, interval validation, managed exact-file tests |
| DET-2 sustained CPU and recovery hysteresis | `harness/triggers/high_cpu.py` | `test_sustained_cpu.py`: count AND duration, threshold boundaries, valid recovery |
| DET-3 missing samples and generations | Snapshot timestamp, trigger watermark/windows, runtime error path | Missing/NaN/stale/duplicate/out-of-order/gap/counter reset/replacement/restart tests |
| DET-4 current evidence only | `harness/collector.py` | `test_probe_evidence.py`: timestamp TTL/start filtering, nanosecond compatibility, dependency unknowns, literal disk argv |
| DET-5 priority and trace | Registry evaluates all predicates; reports priority, selection, probe errors; CPU reports coverage/count/config | Priority tests and corpus; live trace evidence in CI artifacts |
| Independent lab metric confirmation | Shared config passed to managed child; CPU scenario independently reads stats | All eight real scenarios, including high_cpu escalation |
| No unexpected negative-case action | Labeled synthetic observations evaluated through trigger/context/planner/policy | `test_detector_corpus.py`; intentional incorrect label produces regression |
| No sleeps in window tests | Injected clock, explicit snapshot timestamps | `test_sustained_cpu.py`, corpus evaluator |
| Unknowns not recovery | Invalid observations reset incomplete windows; CPU latch is not terminal rearm | Hysteresis and failed-collection runtime regression |

Every positive corpus observation matches its explicit expected timing. CPU at
five-second sampling triggers at ten seconds; default ten-second sampling
requires three samples spanning twenty seconds, plus collection time. Probe
delays count toward maximum gaps; no interpolation fills missing evidence.

## Interpretation and Limits

- Per-type false positives and false negatives are zero in this corpus. CPU has
  2 positive/51 negative samples; each other type has 1 positive/52 negative
  samples. These are hand-labeled regression samples, not independent incidents
  or estimates of real-world accuracy.
- Historical-config corpus input represents already-filtered normalized evidence;
  separate collector tests verify the actual timestamp/start filtering.
- CPU uses Docker's one-logical-CPU scale. Quotas are exposed, not used to change
  the denominator. Sustained detection is unavailable from one isolated run cycle.
- Unsupported probes stay unknown with explanations. Dependency inspection
  failure alone is not down; recent connection-failure logs can supply separate
  positive evidence under the bounded MVP pattern rules.
- Escalation is containment, not infrastructure recovery. CPU hysteresis never
  releases terminal suppression; operator rearm remains explicit.
- Integration tests assert graceful managed shutdown and scenario-owned resource
  cleanup. Post-run labeled container/network listings were empty. A separate
  local process-list scan was unavailable inside the sandbox, not claimed passed.
- Full causal capture, exact replay, shadow comparison, and final handoff remain
  G4/G5 work. The corpus evaluator is not a substitute for those requirements.
