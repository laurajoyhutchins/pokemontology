"""End-to-end smoke tests for the CLI and web Laurel flows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.support import REPO
from tests.support.laurel import write_super_effective_fixture


PYTHON = REPO / ".venv" / "bin" / "python"
SCHEMA_INDEX = REPO / "docs" / "schema-index.json"
SUPER_EFFECTIVE_QUERY = REPO / "queries" / "super_effective_moves.sparql"


def _sitecustomize_dir(tmp_path: Path) -> Path:
    hook_dir = tmp_path / "python-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import os
            from pathlib import Path

            query_file = os.environ.get("POKEMONTOLOGY_TEST_GENERATED_QUERY_FILE")
            if query_file:
                query_text = Path(query_file).read_text(encoding="utf-8")

                def _fake_generate_sparql(*args, **kwargs):
                    return query_text

                import pokemontology.chat
                import pokemontology.cli
                import pokemontology.laurel_eval

                pokemontology.chat.generate_sparql = _fake_generate_sparql
                pokemontology.cli.generate_sparql = _fake_generate_sparql
                pokemontology.laurel_eval.generate_sparql = _fake_generate_sparql
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return hook_dir


def _python_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    hook_dir = _sitecustomize_dir(tmp_path)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{hook_dir}{os.pathsep}{existing}" if existing else str(hook_dir)
    )
    env["POKEMONTOLOGY_TEST_GENERATED_QUERY_FILE"] = str(SUPER_EFFECTIVE_QUERY)
    return env


def test_cli_laurel_command_end_to_end_json(
    built_ontology_path: str, tmp_path: Path
) -> None:
    fixture_path = tmp_path / "super-effective-fixture.ttl"
    write_super_effective_fixture(fixture_path)

    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pokemontology",
            "laurel",
            "Which of my moves are effective against Bulbasaur?",
            built_ontology_path,
            str(fixture_path),
            "--json",
        ],
        cwd=REPO,
        env=_python_env(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["answer"].startswith("Laurel found 1 matching row:")
    assert payload["result"]["rows"][0]["myMoveLabel"] == "Ember"
    assert "pkm:actor" in payload["sparql"]


def test_cli_ask_command_end_to_end_outputs_sparql(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pokemontology",
            "ask",
            "Which of my moves are effective against Bulbasaur?",
        ],
        cwd=REPO,
        env=_python_env(tmp_path),
        check=True,
        capture_output=True,
        text=True,
    )

    assert "SELECT ?myMoveLabel ?moveTypeName ?opponentLabel" in completed.stdout
    assert "pkm:actor" in completed.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for web E2E")
def test_web_worker_pipeline_end_to_end() -> None:
    script = textwrap.dedent(
        f"""
        import fs from "node:fs";
        import path from "node:path";
        import {{ pathToFileURL }} from "node:url";

        const repo = {json.dumps(str(REPO))};
        const schemaPack = JSON.parse(fs.readFileSync(path.join(repo, "docs", "schema-index.json"), "utf8"));

        const llmMessages = [];
        globalThis.self = {{
          postMessage(message) {{
            llmMessages.push(message);
          }},
        }};
        await import(pathToFileURL(path.join(repo, "docs", "workers", "llm-worker.js")).href + "?e2e=llm");
        await globalThis.self.onmessage({{
          data: {{
            question: "Which of my moves are effective against Charizard?",
            matches: [],
            schemaPack,
            webgpuAvailable: false,
          }},
        }});
        const generation = llmMessages.at(-1);

        const queryMessages = [];
        globalThis.self = {{
          postMessage(message) {{
            queryMessages.push(message);
          }},
        }};
        await import(pathToFileURL(path.join(repo, "docs", "workers", "query-worker.js")).href + "?e2e=query");
        await globalThis.self.onmessage({{
          data: {{
            sparql: generation.sparql,
            schemaPack,
          }},
        }});
        const validation = queryMessages.at(-1);

        console.log(JSON.stringify({{ generation, validation }}));
        """
    )

    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["generation"]["backend"] in {
        "CPU fallback synthesizer",
        "deterministic fallback synthesizer",
    }
    assert "pkm:actor" in payload["generation"]["sparql"]
    assert payload["validation"]["ok"] is True
    assert "PREFIX pkm:" in payload["validation"]["normalized"]
