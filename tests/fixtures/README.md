# Detector Corpus

`detectors.json` is hand-authored synthetic normalized input, with expected
classifications specified per observation. It is not a Docker capture and
cannot establish remediation outcomes or real-world incident prevalence.

Each case starts a fresh trigger registry. Each sample starts from a healthy
running container named `fixture`, ID `original`, and applies its explicit
`state` overrides. State overrides are not inherited from the prior sample.
`time` is the sample timestamp; the injected evaluation clock never moves
backward. `observed_monotonic` can override sample time to represent stale
evidence. `restart_runtime` rebuilds the registry. `invalid_cpu: nan` represents
an invalid measurement without placing nonstandard NaN literals in JSON.

The old-config case describes already-filtered normalized collector evidence.
Actual filtering and dependency-inspect parsing are separately tested in
`test_probe_evidence.py`, rather than claiming that this corpus runs Docker.

Run `python -m ci.detector_corpus` from the repository root. The report is written
to `artifacts/raw/detector-corpus.json`; a mismatch exits nonzero. Per-type
denominators count observation decisions, not independent incidents. Every
nonmatching label is negative for that incident type, including cases where
another, higher-priority cause wins. The report also checks rule-planner and
policy outputs; it never imports or calls an executor. Full lifecycle replay
belongs to G4 and is not implemented by this evaluator.

## Recorded Replay Fixtures

`replay/manifest.json` lists 33 sanitized synthetic captures generated through
PatronRuntime, not invented executor transitions. Detector cases originate in
`detectors.json`; the separate lifecycle cases cover failed retries, cooldown,
terminal suppression, acknowledgment/rearm, collection errors, and persisted
OPEN-incident restart continuity. Each sample has an explicit expected label;
lifecycle cases also declare expected final statuses. The mocked infrastructure
and fixed clocks/IDs make these regression fixtures, not real Docker evidence.

Regenerate into a new empty directory with:

```bash
python -m ci.replay_fixtures --output /tmp/patron-replay-fixtures
```

The generator validates and replays every file, removes temporary filesystem
locations, and fixes run/incident IDs deterministically. The committed corpus
regenerates byte-identically. Review changes against the manifest before replacing
fixtures. Default tests replay every committed capture three times with live
Docker constructors, subprocess, network, real sleeps and clocks forbidden.
Large real Docker captures remain in ignored scenario logs and CI artifacts.
