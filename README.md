# llm-rosetta-ext-argonne

[llm-rosetta](https://github.com/Oaklight/llm-rosetta) extensions for Argonne National Laboratory services. Each extension is one self-contained folder under `packages/`, with its own name, version and tests.

> Nothing here is published yet: no release has been cut, and core loads this format only on the extensions branch (see `HANDOVER.md`, *Open items*).

## Extensions

| Id | What it talks to | Shims | Maturity |
|---|---|---|---|
| [`argo`](packages/argo) | Argo, `https://apps.inside.anl.gov/argoapi` (reachable only inside the Argonne network, or through the SSH tunnel) | `argo--chat_completions`, `argo--messages`, `argo--open_responses`; also the `llm-rosetta argo tunnel` command | experimental |
| [`alcf`](packages/alcf) | ALCF Inference Service, `https://inference-api.alcf.anl.gov/resource_server/...` (Globus sign-in) | `alcf_metis--chat_completions`, `alcf_minerva--chat_completions`, `alcf_sophia--chat_completions` | experimental |
| [`asksage`](packages/asksage) | AskSage, `https://api.asksage.ai/server/...` (the ANL deployment uses `api.asksage.anl.gov`) | `asksage--chat_completions`, `asksage--open_responses`, `asksage--messages`, `asksage--google_generate`, `asksage--embeddings` | experimental |

Each folder's `README.md` documents its shims, credentials and caveats. `HANDOVER.md` is the maintainer's guide for this repository.

## Install

```bash
llm-rosetta ext install argo          # newest compatible version, by id
llm-rosetta ext install alcf --version 0.4.0
llm-rosetta ext update                # every installed extension
```

An id is looked up in this repository's latest release (`index.json`, written by the *Release* workflow: each wheel with its sha256, `Requires-Python` and what it needs from core, plus what a listing shows: name, maturity, tags, shims, logo and the commit it was built from. Every field is generated from `plugin.yaml`, the vendor `provider.yaml`, the wheel and git; nothing in the index is written by hand). The index lives at `https://github.com/<owner>/llm-rosetta-ext-argonne/releases/latest/download/index.json`; give it to the installer with `--index` or `$LLM_ROSETTA_EXTENSION_INDEX`:

```bash
export LLM_ROSETTA_EXTENSION_INDEX=https://github.com/<owner>/llm-rosetta-ext-argonne/releases/latest/download/index.json
```

A single wheel installs without the index (`llm-rosetta ext install <wheel-or-url> [--sha256 <digest>]`), and the standard-library installer needs no pip, so it works in the Nuitka binary. `<owner>` is a placeholder until the repository is published.


## Layout

```
README.md  HANDOVER.md  AGENTS.md  CONTRIBUTING.md
skills/                  guidance for coding agents (new-extension, review-extension)
scripts/                 repo-level checks; argo-tunnel.py is the generated single-file copy of the tunnel
.github/workflows/       CI
packages/
  <id>/                  one extension
    pyproject.toml       own name and version; pip installs it
    plugin.yaml          id, version, maturity, requires, provides
    README.md
    __init__.py          the folder is the package (imported as llm_rosetta_ext.<id>)
    provider.yaml        vendor manifest; shim lanes below it
    auth.py              credential exchange
    tests/
```

An extension is a `packages/<id>/` folder that holds `plugin.yaml`. Extensions never import each other. The history of the three former repositories (`llm-rosetta-shim-argo`, `-alcf`, `-asksage`) is kept: use `git log --follow <file>`.

## Checks

Run from the repository root, with an llm-rosetta core that has `llm_rosetta.extensions` on `PYTHONPATH` or installed:

```bash
python scripts/check_layout.py
python scripts/check_wheels.py
python scripts/build_index.py --relative --out /tmp/dist   # the index builds and parses
python -m llm_rosetta ext check packages/<id>
python -m pytest packages/<id>/tests
```
