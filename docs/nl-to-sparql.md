# Natural Language to SPARQL

This document explains the current Laurel natural-language pipeline in `pokemontology`, why it is structured this way, and what has been explicitly deferred.

## Current Approach

The repository now supports two local-model entry points through:

- [`pokemontology/chat.py`](/home/phthalo/pokemontology/pokemontology/chat.py)
- [`pokemontology/cli.py`](/home/phthalo/pokemontology/pokemontology/cli.py)
- [`pokemontology/laurel.py`](/home/phthalo/pokemontology/pokemontology/laurel.py)

The design is intentionally split into stages:

1. Translation: a local LLM converts a natural-language question into SPARQL.
2. Validation: generated SPARQL is checked for read-only safety.
3. Execution: the existing rdflib query path executes SPARQL against one or more Turtle sources.
4. Answering: Laurel can summarize query results back into short natural-language output.

This keeps query execution local and read-only while isolating the less reliable translation step behind validation.

## CLI Flow

There are now two user-facing commands:

Translation only:

```bash
.venv/bin/python -m pokemontology ask "Is Charizard a Fire type?"
```

Full Laurel flow:

```bash
.venv/bin/python -m pokemontology laurel "Is Charizard a Fire type?" build/ontology.ttl
```

`ask` does the following:

1. Builds a prompt from a compact schema summary and the user question.
2. Sends that prompt to a local Ollama endpoint.
3. Extracts plain SPARQL from the model output.
4. Validates that the output is read-only.
5. Prints only the generated SPARQL.

`laurel` does the following:

1. Runs the same translation and validation path as `ask`.
2. Executes the generated SPARQL through the rdflib query path.
3. Summarizes the result rows or boolean answer back into short natural-language output.

`laurel --json` includes the question, generated SPARQL, raw query result payload, and synthesized answer in one response.

## Local Model Choice

The default local model is:

```text
qwen2.5:1.5b
```

This was chosen because it is lightweight enough to run on typical CPU-only hardware, while still being a reasonably capable instruction-following model.

The local endpoint defaults to:

```text
http://127.0.0.1:11434/api/generate
```

The default timeout is intentionally generous because CPU-only cold starts can be slow.

## Prompt Structure

The prompt in `pokemontology.chat` does not embed the full ontology. Instead, it uses a compact schema summary containing:

- Core prefixes
- A few important classes such as `pkm:Species`, `pkm:Variant`, `pkm:Ruleset`, `pkm:BattleParticipant`, `pkm:Move`, and `pkm:Type`
- Notes about contextual assignment patterns
- A small number of few-shot examples
- Output constraints requiring SPARQL-only responses

This keeps token use down and reduces the chance that a small local model gets lost in ontology detail.

## Safety Constraints

The model output is never executed directly. It is first cleaned and validated.

Current safeguards:

- Fenced code blocks are stripped if the model returns Markdown.
- The special error token `ERROR: unrelated_request` is treated as a rejected request.
- Queries must resolve to a read-only SPARQL form.
- Any output containing `INSERT`, `DELETE`, `DROP`, `CLEAR`, `LOAD`, `CREATE`, `COPY`, `MOVE`, or `ADD` is rejected.
- The query must start, after optional `PREFIX` or `BASE` declarations, with one of:
  - `SELECT`
  - `ASK`
  - `DESCRIBE`
  - `CONSTRUCT`

This is a guardrail, not a proof of correctness. A syntactically valid read-only query can still be semantically wrong.

## Why Not a Dedicated NL-to-SPARQL Model

Dedicated text-to-SPARQL models do exist, but they are not the default here for two reasons:

1. Most available models are tuned for DBpedia, Wikidata, LC-QuAD, or QALD-style schemas rather than Pokemontology.
2. The smaller dedicated models are old or weakly documented, while stronger recent models are often much larger than the local footprint we want.

For this ontology, a small instruction-following local model with a schema-aware prompt is a safer starting point than a benchmark-specific text-to-SPARQL checkpoint.

## Deferred Work

The following has been explicitly deferred for now:

- Training or fine-tuning a Pokemontology-specific NL-to-SPARQL model
- Adding a second answer-generation model beyond deterministic result summarization
- Building a public proxy with rate limiting and abuse controls
- Expanding the schema summary automatically from ontology modules
- Adding confidence scoring or query repair loops

## Likely Next Step

If the current local-model approach proves useful, the next serious improvement would be a small fine-tuned model trained on Pokemontology-specific natural-language and SPARQL pairs.

The most realistic lightweight path would be:

1. Create a curated dataset of Pokemontology question/query examples.
2. Fine-tune a small seq2seq model such as Flan-T5.
3. Keep the same validation and read-only execution layer.

That would preserve the current safety boundary while reducing prompt dependence and ontology mismatch.
