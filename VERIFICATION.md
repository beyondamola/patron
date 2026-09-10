# Patron verification: 2026-09-09

## Outcome

The eight built-in scenarios passed with a real local Docker daemon (Docker Desktop engine 29.5.2, macOS arm64). Both the new integration suite and a subsequent normal CLI run completed successfully. This verifies the intended local lab behavior, including actual failure injection, classification, approved response, final status, and cleanup.

Prior incremental reports cited green unit tests while live Docker validation was skipped. The former integration test only checked Docker availability. Those checks did not establish that the scenario workflows worked.

## Defects corrected

- The dependency scenario invoked `busybox httpd`, which is absent from the selected Alpine image. A live run reproduced the baseline failure. The service now uses nginx with matching health-check URLs.
- Audit lookup returned the first matching record, leaving observers stuck on an earlier OPEN record. Lookup now uses the latest complete matching record and tolerates an incomplete JSONL tail. Observers retain the latest outcome.
- Scenario success previously accepted recovery without verifying the final incident/policy/action. The runner now requires matching final status plus the approved, successful expected action. Policy correctness is calculated from policy/planner/executor evidence.
- Managed runs shared persisted state despite recreating same-name containers. Each run now passes a dedicated `PATRON_STATE_PATH` to its subprocess; no existing runtime state is cleared.
- Escalated incidents could reopen after a cooldown. Terminal incidents are now persisted and suppressed until operator intervention, including across runtime restarts. State replacement is atomic.
- Missing or failed Docker observations could falsely resolve an active incident. They now return collection errors without resolving it. Recovery from an active incident uses deterministic verification.
- Escalation verification previously returned success solely from a recommendation. Runtime now transitions the incident first and verification checks its ESCALATED state.
- Unhealthy recovery immediately checked Docker while its healthcheck could still be starting. Verification now allows a bounded health recovery window.
- OOM injection ran an allocating child through a synchronous exec command, which could fail before confirmation. The memory-limited container now starts an allocating PID 1 only after injection and confirms Docker OOMKilled state.
- The CPU burner is capped at one CPU, with 64 MiB and a process limit, and automatically stops after 90 seconds. Disk injection remains a bounded 15 MiB write to 16 MiB tmpfs.
- Dependency network replacement/cleanup lacked ownership checks. Both now verify simulation labels and per-run ownership for cleanup.
- Disk inspection interpolated a label into shell code. It now passes the path as an argument to `df`. Application stderr logs are included and bounded. Disabled healthchecks are handled correctly.
- Docker operations have timeouts, malformed planner decisions fail policy checks, escalation-only incidents cannot be restarted by policy, and invalid polling intervals are rejected.
- Runtime collection/trigger duration was misleadingly called detection latency. It now has its own metric; unknown failure onset remains null in runtime records. Lab latencies use known injection times.

## Tests executed

```bash
python3 -m pytest -q -p no:cacheprovider
# 56 passed, 8 skipped (explicitly opt-in Docker tests)

PATRON_RUN_DOCKER_INTEGRATION=1 python3 -m pytest -m integration -q -p no:cacheprovider
# 8 passed, 56 deselected; 47.42 seconds

python3 -u -m scenarios run-all --timeout 40
# Exit 0, all eight PASSED
```

The real integration tests use unique targets and assert classification, policy, final status, container cleanup, and a graceful shutdown message. The subsequent CLI run uses the ordinary default names, exercising repeated runs and fresh per-run state.

| Scenario | Actual final status | Result |
| --- | --- | --- |
| stopped | RESOLVED | PASSED |
| unhealthy | RESOLVED | PASSED |
| restart_loop | ESCALATED | PASSED |
| oom_killed | ESCALATED | PASSED |
| high_cpu | ESCALATED | PASSED |
| disk_full | ESCALATED | PASSED |
| bad_config | ESCALATED | PASSED |
| dependency_down | ESCALATED | PASSED |

The final CLI run's scenario ids, in table order:

```text
1a714461-7acb-45b0-b78d-b8e31b559afa
3b589f24-8ada-471c-97e6-7ef20e4cc0dc
258584dd-8e66-4d87-a5a4-e5a93a11e986
2cdae9a2-156e-4276-9c5e-37be45982b29
1bdc9c5e-9533-4c88-af37-194fcfebda87
30549262-2489-4656-8df8-202c23f79056
1c0eb266-6849-4504-97b1-5c2375fa385c
06392b44-de26-4641-9852-214c7bcf30da
```

Evidence is preserved in `logs/scenario_results.jsonl`, `logs/incidents.jsonl`, and `logs/scenarios/<scenario-id>/patron.log`. Earlier failed runs are retained as diagnostic history. Final Docker queries returned no simulation containers or networks; a process check found no remaining `harness`/`scenarios` subprocesses. Docker Desktop was started for verification and remains available.

## Practical limits

- Verified on this local Docker Desktop installation; Linux CI and other Docker versions were not exercised.
- Managed mode received live coverage. External mode still requires a correctly targeted user-managed runtime and may inherit its cooldown/state.
- CPU uses a single sample, disk inspection requires `df`, and config/dependency classification uses bounded log patterns and optional measurement hints. These are MVP heuristics.
- Memory usage remains null. Runtime failure onset is unknown, so runtime detection latency is null.
- Terminal incidents currently require operator intervention; there is no acknowledge/rearm command yet.
- Each runtime watches one target. Concurrent processes sharing one state file are not supported. Managed scenarios have independent state files.
- Escalation means correct containment of automated actions, not repair of the underlying failure. Only stopped/unhealthy lab environments are expected to recover automatically.

## Possible next steps, after verification

1. Put these real Docker tests in CI with pinned image versions and retained audit artifacts. This would prevent another sequence of unit-only success claims hiding broken workflows.
2. Add an operator CLI for incident list/show/acknowledge/rearm. This makes persistent escalation usable without manual state-file edits.
3. Improve evidence quality: sustained CPU windows, container-generation identity, configurable disk/dependency checks, and log-pattern expiry. Measure false positives with healthy control scenarios.
4. Build deterministic replay from captured collector packets. Compare rule changes against a stable regression corpus before considering alternative planners.
5. Once that baseline is established, evaluate an optional planner in shadow mode. Keep policy and deterministic verification authoritative, and compare recommendations before allowing execution.
