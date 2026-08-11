"""Regression tests for the Nightly Audit execution contract."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NIGHTLY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly.yml"


def _job_block(workflow: str, name: str, next_name: str | None = None) -> str:
    start = workflow.index(f"  {name}:\n")
    if next_name is None:
        return workflow[start:]
    end = workflow.index(f"  {next_name}:\n", start)
    return workflow[start:end]


def test_full_regressions_cannot_be_masked_by_laurel_configuration() -> None:
    workflow = NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    full_regressions = _job_block(workflow, "full-regressions", "laurel-evaluation")

    assert "continue-on-error" not in full_regressions
    assert "OLLAMA" not in full_regressions
    assert "python -m pytest -m ''" in full_regressions
    assert "--junitxml=full-regressions-junit.xml" in full_regressions
    assert "if: always()" in full_regressions


def test_laurel_evaluation_is_optional_and_separate() -> None:
    workflow = NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    laurel = _job_block(workflow, "laurel-evaluation")

    assert "continue-on-error: true" in laurel
    assert "OLLAMA_HOST: ${{ secrets.OLLAMA_BASE_URL }}" in laurel
    assert "if: ${{ env.OLLAMA_HOST != '' }}" in laurel


def test_failing_pytest_exit_is_independent_of_ollama_configuration(tmp_path: Path) -> None:
    failing_test = tmp_path / "test_failure_sentinel.py"
    failing_test.write_text("def test_failure_sentinel():\n    assert False\n", encoding="utf-8")

    for ollama_host in (None, "http://127.0.0.1:11434"):
        env = os.environ.copy()
        if ollama_host is None:
            env.pop("OLLAMA_HOST", None)
        else:
            env["OLLAMA_HOST"] = ollama_host

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "", "-q", str(failing_test)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert "1 failed" in result.stdout
