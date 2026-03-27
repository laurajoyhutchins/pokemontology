# Dev Artifacts

Save local-only developer outputs here.

Recommended uses:
- Laurel evaluation reports with raw SPARQL, result payloads, answers, and timings
- ad hoc benchmark logs
- temporary debugging snapshots that should stay out of git

This directory is git-ignored except for this README.

Example:

```bash
.venv/bin/python -m pokemontology evaluate-laurel \
  --mode pipeline \
  --schema-index docs/schema-index.json \
  --execution-timeout 15 \
  --save-report dev-artifacts/laurel/eval.json \
  build/ontology.ttl build/pokeapi.ttl
```
