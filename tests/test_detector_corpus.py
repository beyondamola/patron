import json
from pathlib import Path

from ci.detector_corpus import evaluate


def test_labeled_corpus_has_no_unexpected_classification_or_action():
    corpus = json.loads((Path(__file__).parent / "fixtures/detectors.json").read_text())
    report = evaluate(corpus)
    assert report["failures"] == []
    assert report["case_count"] == 26
    for counts in report["per_incident_type"].values():
        assert counts["positive_samples"] > 0
        assert counts["negative_samples"] > 0
        assert counts["false_positives"] == counts["false_negatives"] == 0
        assert counts["positive_samples"] + counts["negative_samples"] == report["sample_count"]
    assert evaluate(corpus) == report


def test_incorrect_label_is_reported_as_a_regression():
    report = evaluate({"schema_version": 1, "cases": [{"name": "deliberately-wrong",
        "samples": [{"time": 0, "expected": "CONTAINER_STOPPED"}]}]})
    assert len(report["failures"]) == 1
    assert report["per_incident_type"]["CONTAINER_STOPPED"]["false_negatives"] == 1
