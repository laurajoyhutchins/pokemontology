`queries/bundled/` contains tracked SPARQL queries used by the build, docs metadata, tests, and examples.

`queries/scratch/` is for local experiments and ad hoc fixtures. Files there are ignored by git, except for the directory README.

Top-level files under `queries/` are treated as scratch work and are ignored. If a query should be consumed by the codebase, put it in `queries/bundled/`.
