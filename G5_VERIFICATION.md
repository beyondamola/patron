# Patron Reliability Qualification

Date: 2026-09-13. Code checkpoint: c1cc647.
Status: G0-G5 verified for the documented local Docker scope.
This report is separate from the historical VERIFICATION.md baseline.

## Delivered Scope

All four workstreams in LONG_TERM_PLAN.md are implemented: pinned Docker CI,
single-writer operator incident control, sustained evidence-based detection,
and isolated capture/replay with fixed-observation fake planner comparison.
The private repository is https://github.com/beyondamola/patron, using GitHub
Actions. The user authorized choosing/creating this destination.

No real model provider, new remediation action, database, UI, Kubernetes, or
Ansible integration was introduced. Policy still allows only restart_container
and escalate. The runtime observes Docker; scenarios own their test environments.

## Qualification Evidence

| Environment / command | Result and retained evidence |
| --- | --- |
| macOS arm64, Python 3.9.6, Docker Desktop 4.76.0 / engine 29.5.2 | Local environment; not a claim about every Docker version |
| Linux Ubuntu 24.04 amd64 and arm64, Python 3.12.14, Docker 28.0.4 | Actual GitHub runners; environment.json retained per job |
| `python3 -m pytest -q --junitxml=artifacts/raw/g5-final-unit.xml` at c1cc647 contents | 304 passed, 9 explicitly opt-in skipped, 10.927s; skips are Docker cases, not unit gaps |
| Real local Docker/operator at 4265487 | 9 passed, zero failures/errors/skips, 101.08s; artifacts/raw/g5-supervised-full.xml |
| `PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest -m 'integration or operator_integration' --junitxml=artifacts/raw/g5-final-docker-enabled.xml -q` at c1cc647 | 9 passed, zero failures/errors/skips, 99.64s |
| Normal `python3 -m scenarios run-all --verbose --capture` at 4265487 | All eight PASSED; artifacts/raw/g5-supervised-run-all.log |
| Same normal CLI command at c1cc647 | All eight PASSED, 06:11:51-06:13:06 UTC; logs/scenario_results.jsonl and per-scenario evidence IDs below |
| Detector corpus | 26 labeled cases / 53 observations; zero false positives and false negatives; artifacts/raw/detector-corpus.json |
| Synthetic replay corpus | 33 versioned captures, each replayed three times with identical semantic reports; byte-identical fixture regeneration |
| Three independent workflows at 4265487 | All four jobs successful per run, with zero integration skips; links below |
| Final code CI c1cc647 | Run 34742002479 successful: 304 units on Python 3.9/3.12; eight scenarios plus operator case on each Linux architecture; zero failures/errors/skips; artifacts/g5-final-qualified |

Three consecutive independent successful workflows on the corrected fixture:

- https://github.com/beyondamola/patron/actions/runs/34741568850
- https://github.com/beyondamola/patron/actions/runs/34741772883
- https://github.com/beyondamola/patron/actions/runs/34741791860

Each executed 301 unit cases on both Python 3.9 and 3.12, eight real scenarios
and one real operator-process case on each Linux architecture. Downloaded XML
was independently checked for exact case counts and zero failures/errors/skips.
All 16 retained scenario/replay reports per workflow matched their expectations.
These are distinct runs, not retries hiding a first failure. The later c1cc647
change corrects exception-phase reporting and adds three unit cases. Its own
successful qualification is https://github.com/beyondamola/patron/actions/runs/34742002479.
Final-code XML and all 16 matching scenario/replay reports were checked separately.

## Scenario Acceptance Matrix

| Scenario | Required classification | Decision | Required status |
| --- | --- | --- | --- |
| stopped | CONTAINER_STOPPED | restart_container | RESOLVED |
| unhealthy | CONTAINER_UNHEALTHY | restart_container | RESOLVED |
| restart_loop | CONTAINER_RESTART_LOOP | escalate | ESCALATED |
| oom_killed | CONTAINER_OOM_KILLED | escalate | ESCALATED |
| high_cpu | CONTAINER_HIGH_CPU | escalate | ESCALATED |
| disk_full | CONTAINER_DISK_FULL | escalate | ESCALATED |
| bad_config | CONTAINER_BAD_CONFIG | escalate | ESCALATED |
| dependency_down | CONTAINER_DEPENDENCY_DOWN | escalate | ESCALATED |

All rows passed the final local normal CLI and all four workflows above. Live tests
assert baseline, independently observed injection, correlated incident type,
policy and final status, complete scoped incident history, graceful managed
shutdown, and owned resource cleanup. Escalation-only histories must contain no
hidden restart. Each real capture is replayed three times and lab timing is
correlated separately from runtime onset. A final matching incident alone cannot
hide an earlier incorrect classification/action.

Final c1cc647 normal-run scenario IDs, in matrix order:

```text
cdd61526-5f5a-4a8a-825d-544732768acf
be242e17-df23-48dc-95fb-2c35f7672108
7902af51-1695-4386-a05a-11ae94aca10c
ab91e565-c1d7-4d09-8b22-c5b4118497f3
0400d7f6-3659-4632-8b70-655fdfade0b5
2196739d-68fa-457b-8436-fffcdde13dfc
0880c417-84ea-48e2-b624-daa006e1df3f
a5ede374-ba03-448f-ab71-cc1aad04a2f8
```

Each ID has logs/scenarios/<id> evidence. Independent post-run Docker queries
found no containers, networks, or volumes with those scenario IDs. The managed
watch-process query found none. Unrelated resources were not removed.
All eight final local captures and all 16 final Linux captures were independently
replayed three times, with equal semantic reports and checked lab provenance.
All eight local Patron logs contain the graceful shutdown completion message.

## Requirement Traceability

| Gate / contract | Evidence and implementation |
| --- | --- |
| G0 baseline | PROGRESS.md initial 56-unit/eight-Docker/normal-CLI checkpoint; historical VERIFICATION.md preserved |
| CI-1 through CI-5 | G1_VERIFICATION.md; immutable multiarch image index pins, pinned dependencies/actions, isolated jobs, strict counts, scoped cleanup and failure artifacts |
| OPS-1 through OPS-4 | G2_VERIFICATION.md; incident/control/storage modules; test_control.py, test_storage.py, test_operator_process.py |
| DET-1 through DET-5 | G3_VERIFICATION.md; configuration, collector, prioritized registry, sustained CPU window/hysteresis, bounded current log/dependency evidence; labeled corpus |
| REP-1 through REP-7 | G4_VERIFICATION.md; versioned capture, causal validation, isolated exact replay, honest comparison, metrics/provenance, 33 fixtures and fake-only shadow contract |
| Final error-path review | test_runner.py setup/injection/observation exceptions preserve primary error through cleanup failure; unknown SIGKILL transition tests |
| Operational handoff | README.md, OPERATOR_RUNBOOK.md, STATE_AND_CAPTURE_FORMATS.md, SHADOW_EVALUATION.md |

Operator tests cover live/offline list/show/acknowledge/rearm, immutable resource
identity, migration backup, revision conflict, a second writer, repeated request
IDs, concurrent producers, pending results, restart continuity, and durable audit
delivery after interruption. Acknowledgment never changes suppression; rearm
never directly changes Docker. Dry-run does not mutate state or infrastructure.

Replay tests prohibit Docker, subprocess, sockets, real sleep and live clocks.
They reject malformed/unsupported/incomplete evidence, reproduce retries,
cooldown, suppression and historical operator events, and prove semantic
repeatability. Fake candidate changes are policy-checked without execution or
live-state mutation, with unknown counterfactual final outcomes.

## Failures Preserved, Not Retried Away

- Run 34715607993 found an unintended generic stopped-container restart before
  OOM escalation. Docker briefly exposed exit 137 without OOMKilled. The runtime
  now withholds generic restart for this ambiguous observation and waits for
  positive OOM evidence. It does not infer OOM from SIGKILL. Evidence:
  artifacts/g4-history-failed; test_oom_transition.py.
- Run 34715967546 exposed OOMKilled=false for the whole confirmation window on
  two jobs. Injection correctly failed and no generic restart ran. Evidence:
  artifacts/g4-oom-guard-failed. The lab now supervises a bounded allocating child
  with a small PID 1 that survives five seconds after child exit, allowing the
  Docker OOM event to be observed. Memory/swap remain 32MiB, CPU one, PIDs 32.
  OOMKilled=true is still mandatory. This addresses observed fixture behavior;
  it does not establish a universal Docker daemon root cause or guarantee.
- An initial real replay exposed monotonic-origin rounding below one microsecond.
  Only coverage-duration comparison gained an absolute one-microsecond tolerance;
  thresholds, classifications, actions and lifecycle states remain exact.
- Final local Docker invocation without the opt-in flag skipped all nine cases.
  artifacts/raw/g5-final-docker.xml records that invocation; it is not Docker
  qualification. The explicitly enabled run is recorded separately.

The original failed workflow runs remain failed. G1_VERIFICATION.md also retains
the deliberately unavailable-daemon and incorrect-outcome failure-path evidence.

## Limits and Follow-On Approval

- This is a single-target local Docker runtime, not a production control plane.
  Operator attribution is not authentication. Locks protect a shared state path,
  not competing runtimes deliberately configured with different state files.
- Escalation is containment, not infrastructure recovery. Persistent ambiguous
  exit 137 requires manual investigation; missing measurements never prove health.
- Sustained CPU evidence depends on valid sampling cadence and one-logical-CPU
  Docker utilization. The labeled synthetic corpus is not a field accuracy study.
- Config-error patterns and dependency evidence remain bounded heuristics. New
  workloads need reviewed evidence and regression cases, not broader blind restarts.
- Capture redaction is pattern-based, not comprehensive secret detection. Review
  evidence before sharing. Headers/control history and event sizes are bounded;
  excess or incomplete evidence fails closed rather than silently truncating causality.
- Replay uses recorded execution and verification responses. Changed-action
  comparisons cannot inherit recorded recovery. Unknown onset remains null unless
  separately correlated lab timestamps exist. Computation time is not model latency.
- Local macOS/Docker 29.5.2 and Linux/Docker 28.0.4 results are separate evidence,
  not universal portability claims. CI artifacts expire after 14 days; reviewed
  local downloads are ignored by Git and historical reports retain run links.

Real planner evaluation is a separate authorization gate: approved sanitized
corpus, explicit provider/data-sharing decision, finite cost/time caps, and an
execution-disabled design review. No credential or provider call is required to
complete this roadmap. Successful shadow scores never authorize live actions.

## Gate Closure

G0-G4 requirement mappings and historical evidence are linked above. Final code
c1cc647 passed unit, real local Docker/operator, normal CLI, Linux CI on both
architectures, and offline replay checks. Documentation now covers installation,
pins, commands, detector thresholds, state/capture formats, operator recovery,
and the explicit future-provider approval boundary. No unresolved correctness
or safety blocker remains within this tested scope; the limits above remain
operational constraints rather than promises of production readiness.
