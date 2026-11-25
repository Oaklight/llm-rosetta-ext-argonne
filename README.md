# llm-rosetta-ext-argonne

[llm-rosetta](https://github.com/Oaklight/llm-rosetta) extensions for Argonne National Laboratory services. Each extension is one self-contained folder under `packages/`, with its own name, version and tests.

> Draft layout. Nothing here is published yet, and core loads this format only on the extensions branch (see `HANDOVER.md`, *Open items*).

## Extensions

| Id | What it talks to | Shims | Maturity |
|---|---|---|---|
| [`argo`](packages/argo) | Argo, `https://apps.inside.anl.gov/argoapi` (reachable only inside the Argonne network, or through the SSH tunnel) | `argo--chat_completions`, `argo--messages`, `argo--open_responses`; also the `argo-tunnel` command | experimental |
| [`alcf`](packages/alcf) | ALCF Inference Service, `https://inference-api.alcf.anl.gov/resource_server/...` (Globus sign-in) | `alcf_metis--chat_completions`, `alcf_minerva--chat_completions`, `alcf_sophia--chat_completions` | experimental |
| [`asksage`](packages/asksage) | AskSage, `https://api.asksage.ai/server/...` (the ANL deployment uses `api.asksage.anl.gov`) | `asksage--chat_completions`, `asksage--open_responses`, `asksage--messages`, `asksage--google_generate`, `asksage--embeddings` | experimental |

Each folder's `README.md` documents its shims, credentials and caveats. `HANDOVER.md` is the maintainer's guide for this repository.

## Install

Install one extension from a release tag (`<id>/v<version>`):

```bash
pip install "git+https://github.com/<owner>/llm-rosetta-ext-argonne@argo/v0.3.0#subdirectory=packages/argo"
pip install "git+https://github.com/<owner>/llm-rosetta-ext-argonne@alcf/v0.4.0#subdirectory=packages/alcf"
pip install "git+https://github.com/<owner>/llm-rosetta-ext-argonne@asksage/v0.4.0#subdirectory=packages/asksage"
```

Or install a built wheel with core's installer, which needs no pip:

```bash
llm-rosetta ext install <wheel>
```

`<owner>` is a placeholder until the repository is published.

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
python -m llm_rosetta ext check packages/<id>
python -m pytest packages/<id>/tests
```
