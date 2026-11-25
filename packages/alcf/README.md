# alcf

ALCF (Argonne Leadership Computing Facility) provider shims for [llm-rosetta](https://github.com/Oaklight/llm-rosetta), delivered as an **extension** (`llm_rosetta_ext.alcf`).

The `alcf_*` shims left llm-rosetta core in 0.14.0 ([#666](https://github.com/Oaklight/llm-rosetta/issues/666)); this extension is now their only source. Install it and existing provider entries keep their names (see *Install*).

## Shims

The names follow the parent's canonical `alcf_<cluster>--<format>` spelling: the
cluster sits in the provider segment and the segment after `--` is always the API
format. All three clusters declare `group: alcf`, so the admin provider picker
shows a single `alcf` top level whose rows read `metis · chat_completions`,
`minerva · chat_completions` and `sophia · chat_completions`.

| Shim | Base | Endpoint |
|:---|:---|:---|
| `alcf_metis--chat_completions` | `chat_completions` | `https://inference-api.alcf.anl.gov/resource_server/metis/api/v1` |
| `alcf_minerva--chat_completions` | `chat_completions` | `https://inference-api.alcf.anl.gov/resource_server/minerva/api/v1` |
| `alcf_sophia--chat_completions` | `chat_completions` | `https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1` |

The pre-rename spellings (`alcf--metis`, `alcf--minerva`, `alcf--sophia`) no
longer resolve; use the canonical names above.

Model ID slugs come from a shared `model_list_transform` (framework-aware filtering).

## Credential

The Globus grant *is* this vendor's credential, and the package ships the
exchange that owns it: `auth.py`, beside the vendor manifest, so
all three clusters authenticate alike. There is no static key and no argv: a
shim ships one form of its credential exchange.

The first sign-in is interactive and happens once per provider:

```bash
llm-rosetta credential login --provider "<the provider's name>"
```

That prints a Globus URL and takes the code the page shows; from then on the
rotating refresh token keeps every cluster served, at startup, on the gateway's
refresh interval and after an upstream 401.

The grant is stored where the vendor's own tooling keeps it —
`~/.globus/app/<client-id>/inference_app/tokens.json` — and written back in that
layout, so:

- an installation that already signed in with `alcf-ai` needs no step at all,
  and a container that mounts `~/.globus` is configured once for both;
- nothing needs to be exported into the environment; `ALCF_API_KEY` is no longer
  read, and a provider that still carries `token_command` keeps the old argv
  path only while its shim does.

In the admin panel the same flow is the provider's **Sign in** action: it
returns the URL and accepts the pasted code, so the gateway host needs no
loopback port and no browser.

ALCF enforces a *high-assurance* session policy. A grant that keeps renewing can
still be refused once the interactive authentication is too old; the upstream
401 names it. Sign in again when that happens — the exchange reports it as a
mint failure, not as a wrong key.

## Install

```bash
pip install "git+https://github.com/<owner>/llm-rosetta-ext-argonne@alcf/v0.4.0#subdirectory=packages/alcf"
# or, from a built wheel:
llm-rosetta ext install <wheel>
```

llm-rosetta discovers the extension through the `llm_rosetta.extensions` entry point and registers the `alcf_<cluster>--chat_completions` shims.

## Requirements

- Python >= 3.10
- `llm-rosetta >= 0.14.0`
- No credential in the environment: the shipped exchange reads and renews the Globus grant in `~/.globus`, or the record under the gateway's data directory

## Tests

```bash
python -m pytest packages/alcf/tests
```

## Live verification

No dated live-verification record was kept in the old README. `sophia/llm/provider.yaml` notes that the effort ladder was verified live 2026-10-13 with openai/gpt-oss-120b, issue #961.

## License

MIT — see [LICENSE](LICENSE).
