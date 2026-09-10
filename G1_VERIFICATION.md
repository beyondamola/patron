# G1 verification: pinned Docker CI

Date: 2026-09-10. Implementation commit: `557f88fca9c18572054f3fdb183d68e09dc05098`.
This report establishes G1 only, not completion of the reliability roadmap.

## Repository and environment

- Created https://github.com/beyondamola/patron as a private repository following
  explicit user authorization. Baseline checkpoint: `8b1ca31`.
- No local logs, virtualenv, credentials, caches, or generated artifacts were
  committed. Historical VERIFICATION.md remains unchanged.
- GitHub Actions unit jobs install pinned dependencies on Python 3.9 and 3.12.
- Real Docker jobs run on `ubuntu-24.04` amd64 and `ubuntu-24.04-arm` arm64.
- Local verification used macOS arm64, Python 3.9.6, Docker engine 29.5.2.
- Image index digests and their provenance are in scenarios/images.py and README.
  Both platform manifests were inspected and both architectures executed tests.

## Evidence

| Check | Observed outcome |
| --- | --- |
| Original unit baseline | 56 passed, 8 opt-in skipped |
| Original real Docker suite | 8 passed, 48.71 seconds |
| Original normal CLI run-all | All eight PASSED |
| Fresh virtualenv dependency installation | Succeeded with requirements-dev.txt |
| Final G1 unit suite | 70 passed, 8 opt-in skipped |
| Local immutable-image integration | 8 passed, 51.56 seconds; strict XML validation passed |
| Normal CLI after evidence changes | All eight PASSED |
| Intentionally nonexistent Docker socket in strict mode | Exit 1; 8 setup errors, no skips |
| Post-local-run cleanup checks | No simulation containers/networks or remaining harness/scenario processes |

### Actual CI runs

1. https://github.com/beyondamola/patron/actions/runs/34498459240: FAILED. Both
   eight-case scenario suites passed, but cleanup rejected a period in its own
   workflow-generated run ID. The failure is retained, not counted as a success.
2. https://github.com/beyondamola/patron/actions/runs/34498811932: PASSED.
3. https://github.com/beyondamola/patron/actions/runs/34499033848: PASSED.
4. https://github.com/beyondamola/patron/actions/runs/34499045400: PASSED.

The last three are independent executions of the same corrected commit, each
with two unit and two real Docker jobs. No automatic retry replaced a failure.
The two dispatch runs used independent labels/state/resources and overlapped
without cleanup interference.

Downloaded run 34498811932 artifacts were inspected locally:

- Both integration XML files contain exactly eight cases, zero failures/skips.
- All 16 scenario results report PASSED with correct classification, policy,
  and final status.
- 48 normalized pre-injection, post-injection, and final state packets exist.
- Each scenario has retained Patron output and an independent state file.
- Environment metadata contains Docker/Python information and immutable images.

Local downloaded evidence is under `artifacts/ci-qualification-1`; first-failure
evidence is under `artifacts/ci-first-run`. Hosted sanitized artifacts expire
after 14 days; local copies are ignored by Git. Workflow result URLs remain the
primary hosted execution references.

## Acceptance mapping

| Requirement | Evidence |
| --- | --- |
| CI-1 reproducibility | Fresh install; immutable image indexes; both architecture jobs |
| CI-2 separate fail-closed lanes | Workflow plus strict Docker experiment; exact eight-case XML validator |
| CI-3 bounded and isolated execution | 120s observation timeout; 180s image pull timeout; 20min jobs; run/scenario labels |
| CI-4 retained evidence and cleanup | Uploaded state/results/output/environment; always-run cleanup; ownership regression tests |
| CI-5 no hidden flake retries | First failure retained; three separate corrected-commit successes |
| Incorrect/missing results fail | test_report_rejects_unsuccessful_case and test_report_requires_all_eight |
| No unrelated cleanup | test_cleanup_rechecks_ownership, test_cleanup_filters_exact_run, empty-ID guard |
| Missing Docker fails CI | test_unavailable_docker_fails_preflight plus real CLI nonexistent-socket experiment |
| Failure artifacts survive | test_artifacts_preserve_failed_run_and_redact; actual failed-run artifact download |
| No premature result narration | test_result_not_announced_before_persistence |

## Remaining limitations

- G2 operator controls, G3 sustained detection, G4 replay, and G5 full handoff are
  still pending. This milestone does not change those acceptance requirements.
- Credential redaction covers common patterns, not arbitrary unknown secrets.
  The lab must not contain real credentials; fixtures remain synthetic.
- The pinned artifact action emits a Node runtime deprecation warning but executes
  successfully. This is maintenance work, not evidence of a failed verification.
- Scenario observation limits are phase-specific; the CI job adds an outer hard
  wall-clock bound. Host cancellation ultimately relies on runner isolation.
- Linux CI and this local Docker installation are verified, not every supported
  Docker engine or operating-system version.
