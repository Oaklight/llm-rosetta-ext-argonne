# Contributing

1. Copy the closest existing folder under `packages/`, rename it to your id, and edit `plugin.yaml`.
2. Keep it self-contained (see `AGENTS.md`). Add tests under `tests/`.
3. `python scripts/check_layout.py`, `llm-rosetta ext check packages/<id>`, then run your package's tests against current llm-rosetta core.
4. Open a pull request that touches only your folder.

Maturity ladder: `experimental` (new) → `beta` (tests and one live verification) → `stable` (candidate for core).
Releases: a maintainer runs the *Release* workflow with a tag; it publishes every wheel and an `index.json` as one GitHub release (see `HANDOVER.md`, *Cutting a release*). Users install with `llm-rosetta ext install <id>`.
