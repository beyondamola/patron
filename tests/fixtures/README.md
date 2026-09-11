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
