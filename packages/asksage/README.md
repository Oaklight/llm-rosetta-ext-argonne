# asksage

AskSage provider shims for [llm-rosetta](https://github.com/Oaklight/llm-rosetta), delivered as an **extension** (`llm_rosetta_ext.asksage`).

The `asksage--*` shims left llm-rosetta core in 0.14.0 ([#666](https://github.com/Oaklight/llm-rosetta/issues/666)); this extension is now their only source. Install it and existing provider entries keep their names (see *Install*).

## Shims

| Shim | Model type | Format |
|:---|:---|:---|
| `asksage--chat_completions` | `llm` | `chat_completions` |
| `asksage--open_responses` | `llm` | `open_responses` |
| `asksage--messages` | `llm` | `messages` |
| `asksage--google_generate` | `llm` | `google_generate` |
| `asksage--embeddings` | `embeddings` | `openai` |

`asksage--embeddings` targets the embeddings lane asksage-proxy adds by hand at
`POST /server/openai/v1/embeddings` (Oaklight/asksage-proxy PR #10), so its base
is the same `/server/openai/v1` root as the chat lane and its path is
`/embeddings`.

`asksage--messages` targets `/server/anthropic`.  Measured 2026-11-06 against
the ANL deployment, that path answers HTTP 200 with an OpenAI `chat.completion`
body rather than a Messages envelope, so an ANL provider should use
`asksage--chat_completions` and let the gateway convert the client's Messages
request into the upstream chat lane.

The pre-0.14 spellings `asksage--openai_chat`, `asksage--openai_responses` and
`asksage--anthropic` no longer resolve: this package registers the canonical
names only. Update a legacy spelling to the canonical name above.

All use AskSage's API-key env `ASKSAGE_API_KEY`; the `google_generate` leaf
overrides the auth header to `x-access-tokens`, the `chat_completions` and
`open_responses` leaves add field renames, and the `embeddings` leaf declares
only its base URL and path. Unlike the argo/alcf packages, these transforms use
only absolute imports.

## Credentials

AskSage's inference lanes take a short-lived access token minted by
`POST {host}/user/get-token-with-api-key` from the account key the holder copies
off the AskSage website. The exchange that performs that swap ships with this
package: `auth.py`, beside the vendor manifest, so every leaf
inherits it. A shim ships one form of its credential exchange, so there is no
`token_command` any more.

What the exchange owns:

- **The account key is its input.** Put the key in the provider's `api_key`
  (or export `ASKSAGE_API_KEY`, which the manifest names as the shim's
  `api_key_env`). Both are the same input — the minted token is what goes
  upstream, never the key.
- **The host is part of the credential.** The token is minted against the origin
  of the provider's `base_url`, so the ANL and public deployments can never be
  mixed up — the mismatch that made a `token_command` deployment fail with
  `Key doesnt exist`.
- **The account email is required**, and there are three ways to give it, in
  order of precedence: the **Account email** field on the provider (written into
  the entry's `auth_fields`), a hand-written flat `email` key, or
  `ASKSAGE_TOKEN_EMAIL` in the gateway's environment. The field is declared in
  the vendor manifest, so the admin drawer renders it beside the API key and one
  **Save** writes both — no CLI step and no separate record:

  ```yaml
  fields:
    - key: email
      label: Account email
      placeholder: you@example.gov
      help: The address the AskSage account key was issued to.
  ```

  The field is not marked `required`: the later sources still work, so a form
  that refused to save without it would block a deployment that supplies the
  address elsewhere.

The token is cached until shortly before its `exp` claim, so a one-hour refresh
interval does not buy a round trip per hour.

Measured 2026-11-06 against the ANL deployment: the raw account key is also
accepted directly by the OpenAI lanes.  `POST /server/openai/v1/chat/completions`
and `POST /server/openai/v1/responses` both answer 200 with a real body, and
`/server/openai/v1/embeddings` passes authentication and then answers 503
`Embedding service unavailable` (a bogus key gets the `Token is invalid [2]`
envelope on the same path, so the 503 is the service, not the credential).
The minted-token default is unchanged.

### Typed endpoints

An embeddings provider declared under `providers:` shares its LLM lane's key
ring, so `asksage--embeddings` is served by the same minted token — one entry
covers every lane:

```jsonc
{
  "providers": {
    "asksage": {
      "shim": "asksage--chat_completions",
      "api_key": "<account key>",
      "embeddings_shim": "asksage--embeddings"
    }
  },
  "models": {},
  "embeddings_models": { "text-embedding-3-small": "asksage" }
}
```

The legacy `embeddings_providers` section has no `providers:` lane to share the
mint from, so an entry there that mints is still auto-disabled with a reason
that names the section and the fix — move the provider to `providers:`.

Two keys in that shape are easy to get wrong. Inside a legacy
`embeddings_providers` entry the wire dialect is `format`, not
`embeddings_format` — the latter is not read and the entry silently keeps the
`openai` default. And the provider alone resolves nothing: a request's `model`
is looked up in `embeddings_models`, so without that mapping
`POST /v1/embeddings` answers `404 Unknown model: '<id>'. Configured: (none)`
and never calls upstream.

## Install

```bash
pip install "git+https://github.com/<owner>/llm-rosetta-ext-argonne@asksage/v0.4.0#subdirectory=packages/asksage"
# or, from a built wheel:
llm-rosetta ext install <wheel>
```

llm-rosetta discovers the extension through the `llm_rosetta.extensions` entry point and registers the `asksage--*` shims.

## Requirements

- Python >= 3.10
- `llm-rosetta >= 0.14.0.dev40`
- One of `ASKSAGE_TOKEN_API_KEY` / `ASK_SAGE_API` / `ASKSAGE_API_KEY` in the gateway's environment, for the shipped exchange to mint its token

## Tests

```bash
python -m pytest packages/asksage/tests
```

The embeddings tests import `llm_rosetta_gateway`, so run them where the gateway distribution is importable.

## Live verification

Measured 2026-11-06 against the ANL deployment (the `messages` path and the raw-key behaviour above); `llm/messages/provider.yaml` also records a probe of 2026-10-13, and `llm/open_responses/provider.yaml` a verification of 2026-10-12 (issue #899).

## License

MIT — see [LICENSE](LICENSE).
