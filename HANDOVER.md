# Handover

For the people who maintain this repository after the original author. Everything below comes from the three former repositories (`llm-rosetta-shim-argo`, `llm-rosetta-shim-alcf`, `llm-rosetta-shim-asksage`) and from this repository's checks. Where something is not known, it says so.

## What each extension talks to

| Extension | Upstream | Credential |
|---|---|---|
| `argo` | `https://apps.inside.anl.gov/argoapi` (`/v1` for chat_completions and open_responses). The host resolves only inside the Argonne network. | The ANL account name, as the provider's `api_key` or `ARGO_API_KEY`. `auth.py` checks that the SOCKS `proxy` of the entry answers; it never starts the tunnel. |
| `alcf` | `https://inference-api.alcf.anl.gov/resource_server/{metis/api/v1, minerva/api/v1, sophia/vllm/v1}` | A Globus grant. First sign-in is interactive (`llm-rosetta credential login --provider "<name>"`, or **Sign in** in the admin panel). The grant lives in `~/.globus/app/<client-id>/inference_app/tokens.json`. |
| `asksage` | `https://api.asksage.ai/server/{openai/v1, anthropic, google/v1beta}`; the ANL deployment is `https://api.asksage.anl.gov/server/...` | An account key, swapped by `POST {host}/user/get-token-with-api-key` for a short-lived token. The account email is also required (provider field, `email` key, or `ASKSAGE_TOKEN_EMAIL`). |

`argo` also ships the `llm-rosetta argo tunnel` command: one SSH master connection to `homes.cels.anl.gov` through `logins.cels.anl.gov` (Duo MFA on `auth`) and a SOCKS5 forward on `127.0.0.1:10801`. It is standard-library only, and that must stay true: `scripts/argo-tunnel.py` is a generated copy that people run without installing anything. After a change to `packages/argo/tunnel.py`, run `python scripts/sync_argo_tunnel_script.py` (a test fails when the copy is stale). The command is reachable two ways: `llm-rosetta argo tunnel` (the extension's `commands.py` lists `tunnel` under `provides.commands` in `plugin.yaml`) and the standalone file. The old `argo-tunnel` console script and its dispatcher entry point were removed.

## Running the tests

```bash
conda activate llm-rosetta   # or any env with an llm-rosetta core that has llm_rosetta.extensions
python -m pytest -p no:cacheprovider packages/argo/tests packages/alcf/tests packages/asksage/tests
```

- `-p no:cacheprovider` keeps pytest from writing `.pytest_cache` inside the extension folder. A stray cache (or `build/`, `*.egg-info`) in a folder makes `scripts/check_wheels.py` fail, because the folder is the package.
- Each `tests/conftest.py` loads the folder in place as `llm_rosetta_ext.<id>` and gives a `register("<id>")` fixture that fills a clean shim registry.
- The `asksage` embeddings tests import `llm_rosetta_gateway`, so the gateway distribution must be importable.
- No test calls a live service. The tunnel tests use a fake ssh runner.

## Cutting a release

1. Change the version in three places and keep them equal: `packages/<id>/plugin.yaml` (`version`), `packages/<id>/pyproject.toml` (`version`) and `packages/<id>/__init__.py` (`__version__`).
2. Run the checks in `README.md` (*Checks*). All of them must pass.
3. Merge to `main`, then run the *Release* workflow (Actions, *Run workflow*) with a tag such as `r2026.11.25`. It rebuilds every wheel from a clean copy, merges the previous release's `index.json` (so older versions stay installable) and uploads the wheels and the new `index.json` as one GitHub release.
4. Users run `llm-rosetta ext install <id>` and `llm-rosetta ext update`; both read the latest release's `index.json` and check each wheel's sha256.

`.github/workflows/release.yml` has not been run: the first release is the first test of it. It installs core from TestPyPI while 0.14.0 is unpublished (the `CORE_SPEC` and `CORE_INDEX` variables at the top of both workflows); switch them to PyPI when 0.14.0 ships. `scripts/build_index.py --relative --out <dir>` builds the same wheels and index locally, which is also how to test a change to the builder. The old repositories published a shim archive to a `dist` branch from a `v<version>` tag; that mechanism is not carried over.

## Where the live-verification notes are

The notes sit in comments of the provider files and in the READMEs. The old READMEs recorded no dated verification of a whole extension, so every extension is `experimental` in `plugin.yaml`. An extension can move to `beta` after its README records one live verification (date, what was called) and its tests pass.

- `argo`: Anthropic thinking matrix probed 2026-09-28 (`llm/messages/provider.yaml`); Responses echo fields verified live 2026-10-12, issue #899 (`llm/open_responses/provider.yaml`); the `ControlPersist` and `ssh -O forward` behaviours marked "measured" in `tunnel.py` and the README.
- `alcf`: effort ladder of Sophia verified live 2026-10-13 with `openai/gpt-oss-120b`, issue #961 (`sophia/llm/provider.yaml`).
- `asksage`: messages path and raw-key behaviour measured 2026-11-06 against the ANL deployment (README); messages probe 2026-10-13 (`llm/messages/provider.yaml`); Responses verified live 2026-10-12, issue #899 (`llm/open_responses/provider.yaml`).

## Known caveats (from the old READMEs)

- `argo`: the pre-0.14 spellings `argo--openai_chat`, `argo--openai_responses` and `argo--anthropic` do not resolve. A request in flight when the SSH master exits fails; run `start` again, or `auth` if the master is gone. Never bind the forward to `0.0.0.0`: SOCKS5 here has no authentication. `logout` finds a lost master through `/proc`, which is Linux only. Socket paths have a hard length limit (about 100 bytes).
- `alcf`: ALCF enforces a high-assurance session policy. A grant that keeps renewing can still be refused once the interactive authentication is too old; sign in again. The old spellings `alcf--metis`, `alcf--minerva`, `alcf--sophia` do not resolve.
- `asksage`: `asksage--messages` targets `/server/anthropic`, which answered with an OpenAI `chat.completion` body on the ANL deployment (measured 2026-11-06); use `asksage--chat_completions` for an ANL provider. A legacy `embeddings_providers` entry cannot share the mint and is auto-disabled; declare the provider under `providers:`. The old spellings `asksage--openai_chat`, `asksage--openai_responses` and `asksage--anthropic` do not resolve.
- The logo URLs in the `provider.yaml` files still point to the old repositories' `assets/` (jsDelivr). The files are copied to each `packages/<id>/assets/`; the URLs were not changed.

## Open items

1. Core must load the extension format (`llm_rosetta.extensions` entry point, `plugin.yaml`). It is on core's extensions branch; the checks here ran against that branch.
2. `.github/workflows/ci.yml` only runs `check_layout.py`. It needs jobs that install that core and run `check_wheels.py` and each package's tests.
3. The old gateway catalogue presets (`shims.presets: ["argo"]`, `"alcf"`, `"asksage"`) pointed to the old repositories' archives. They are not served by this repository.
4. `<owner>` in every install line is a placeholder.
