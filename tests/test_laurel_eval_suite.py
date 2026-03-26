"""Regression checks for the Professor Laurel evaluation suite fixture."""

from __future__ import annotations

import json

from pokemontology._script_loader import repo_path


REPO = repo_path()
SUITE = REPO / "tests" / "fixtures" / "laurel_eval_suite.json"


def test_laurel_eval_suite_has_expected_tiers_and_adversarial_cases() -> None:
    payload = json.loads(SUITE.read_text(encoding="utf-8"))

    tiers = {tier["tier"]: tier["items"] for tier in payload["tiers"]}
    assert {"easy", "medium", "hard", "generation-specific"} <= set(tiers)
    assert len(tiers["easy"]) >= 4
    assert len(tiers["medium"]) >= 4
    assert len(tiers["hard"]) >= 4
    assert len(tiers["generation-specific"]) >= 8
    assert len(payload["adversarial"]) >= 5


def test_laurel_eval_suite_sources_and_answers_are_present() -> None:
    payload = json.loads(SUITE.read_text(encoding="utf-8"))

    for tier in payload["tiers"]:
        for item in tier["items"]:
            assert item["question"]
            assert item["expected_answer"]
            assert item["sources"]
            for source in item["sources"]:
                assert source["url"].startswith("https://")
