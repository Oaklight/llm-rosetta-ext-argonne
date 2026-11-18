# llm-rosetta-shim-argo

Argo (Argonne) provider shims for [llm-rosetta](https://github.com/Oaklight/llm-rosetta),
delivered as a **plugin package** rather than as built-in shims.

The `argo--*` shims left llm-rosetta core in 0.14.0
([#666](https://github.com/Oaklight/llm-rosetta/issues/666)); this package is now
their only source. Declare it in the gateway config and existing provider
entries keep their names:

```jsonc
{ "shims": { "presets": ["argo"] } }
```

`shims.presets` expands to this repository's archive path via llm-rosetta's
catalogue; the equivalent explicit entry is `{"url": "...", "path":
"src/llm_rosetta_shim_argo/providers"}`. The repository is public, so no
`token_env` is needed.

The same package also ships `llm-rosetta-argo-tunnel`, the SSH tunnel CLI that
makes the endpoint reachable from outside the network — see
[The tunnel](#the-tunnel-llm-rosetta-argo-tunnel).

## Shims

| Shim | Base | Endpoint |
|:---|:---|:---|
| `argo--chat_completions` | `chat_completions` | `https://apps.inside.anl.gov/argoapi/v1` |
| `argo--messages` | `messages` | `https://apps.inside.anl.gov/argoapi` |
| `argo--open_responses` | `open_responses` | `https://apps.inside.anl.gov/argoapi` |

Each shim carries the Argo-specific connection defaults, reasoning config, soft-error
patterns, and field/schema transforms (Gemini-via-Argo quirks, model-ID mapping).

## Install

```bash
pip install llm-rosetta
pip install llm-rosetta-shim-argo
```

llm-rosetta discovers the `llm_rosetta.shim_providers` entry point on startup and
registers the `argo--*` shims automatically — no import needed in application code.

## Usage

```python
from llm_rosetta.shims import get_shim

shim = get_shim("argo--chat_completions")   # requires ARGO_API_KEY in the environment
print(shim.connection.base_url)
```

The pre-0.14 spellings `argo--openai_chat`, `argo--openai_responses` and
`argo--anthropic` no longer resolve to a shim: this package registers the
canonical names only. They remain in llm-rosetta as a spelling map, so an old
config canonicalises first and reaches the error naming this package. Update
the spelling to the canonical name above.

## Archive and mirror

Every release publishes one archive of the bundled shims, so a gateway can load
them from a host other than GitHub. `main` never carries it: `dist/` is build
output and is in `.gitignore`.

- `v<version>/argo.tar.gz` and `v<version>/argo.tar.gz.sha256` live on the
  orphan `dist` branch.
- The same bytes are attached to the GitHub Release, with the digest in its
  notes.

Two interchangeable, version-pinned URLs for the same bytes:

```
https://github.com/Oaklight/llm-rosetta-shim-argo/releases/download/v<version>/argo.tar.gz
https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-argo@dist/v<version>/argo.tar.gz
```

The archive's root is `providers/`, the layout the package ships under
`src/llm_rosetta_shim_argo/providers`, so a gateway source declares `path: "providers"`:

```jsonc
{
  "shims": {
    "remotes": [
      {
        "url": "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-argo@dist/v<version>/argo.tar.gz",
        "path": "providers",
        "archive": "tar.gz",
        "sha256": "<digest from v<version>/argo.tar.gz.sha256>"
      }
    ]
  }
}
```

The digest is what pins the mirror, and the same value appears in the release
notes. jsDelivr is only the default suggestion: the gateway accepts any URL that
serves the same bytes, an internal mirror included.

### Publishing a release

1. Bump `__version__` in `src/llm_rosetta_shim_argo/__init__.py`. The tag must match it —
   the release workflow passes the tag without its `v` as `--expect-version` and
   refuses a mismatch.
2. `python scripts/build_shim_archive.py --write` builds
   `dist/v<version>/argo.tar.gz` and its digest locally and verifies the
   layout. CI runs the same build without writing on every push, so a tree whose
   `providers/` layout changed fails before a tag is cut.
3. Tag and push: `git tag v<version> && git push origin v<version>`.
4. `.github/workflows/release.yml` builds from the tag, creates or updates the
   GitHub Release, uploads the archive and its digest file, and commits
   `v<version>/` to the `dist` branch.

The workflow requests `contents: write` for `GITHUB_TOKEN`, because it creates
the release and pushes `dist`. An organization that downgrades action tokens to
read-only must restore "Read and write permissions" under Settings → Actions →
General, or the release step fails.

## The tunnel (`llm-rosetta-argo-tunnel`)

`apps.inside.anl.gov` resolves only inside the Argonne network, and the jump
host asks for Duo MFA on every new connection. The `llm-rosetta-argo-tunnel`
console script owns that: one authenticated SSH master connection, one SOCKS5
forward on top of it, and a status you can branch on.

```bash
llm-rosetta-argo-tunnel auth --target homes   # the one command that prompts for MFA
llm-rosetta-argo-tunnel start                   # publish the SOCKS forward
llm-rosetta-argo-tunnel proxy-url               # socks5://127.0.0.1:10801
```

No install needed — the same program is published as one file:

```bash
curl -fsSLO https://raw.githubusercontent.com/Oaklight/llm-rosetta-shim-argo/main/scripts/argo-tunnel.py
python argo-tunnel.py auth --target homes
```

### Which machine it connects to

`--target` is an **ssh destination**, passed to ssh verbatim:

| `--target` | What ssh does |
|---|---|
| `homes` | Uses your `~/.ssh/config` `Host homes` stanza — its `HostName`, `Port`, `IdentityFile`, and `ProxyJump` if it has one |
| `me@homes.cels.anl.gov` | Connects to that, exactly as `ssh me@homes.cels.anl.gov` would |
| *(omitted)* | Builds `homes.cels.anl.gov` through `logins.cels.anl.gov` — a documented default, not a verified fact |

With a target, no `-J` is passed unless you give `--jump`: an alias normally
carries its own `ProxyJump`, and overriding it would silently replace your
routing with this tool's guess. `--jump none` means a direct connection.

`--user` applies only to a *built* destination, never to `--target` — an alias
carries its own user, and rewriting `homes` into `homes@homes` would
address a host ssh has never heard of.

Then point the Argo provider's `proxy` field at that URL:

```jsonc
{
  "providers": {
    "argo": {
      "type": "argo--chat_completions",
      "proxy": "socks5://127.0.0.1:10801",
      "api_key": "<your ANL username>"
    }
  },
  "shims": { "presets": ["argo"] }
}
```

`base_url` stays `https://apps.inside.anl.gov/argoapi/v1` — a **dynamic**
(SOCKS) forward, not a local `-L` one, so the hostname the shim declares is the
hostname the TLS certificate is checked against. A local forward would answer
on `127.0.0.1` and fail verification.

### Commands

| Command | Does | Prompts |
|---|---|---|
| `auth` | Opens the master connection (`ssh -M -N -f`) and keeps it for `ControlPersist` (default 8h) | yes, once |
| `start` | Adds the forward to the running master (`ssh -O forward -D`); idempotent | no |
| `stop` | Cancels the forward; the master stays authenticated | no |
| `status` | Prints `forwarding` / `idle` / `wedged` / `absent`; exit code 0 only for `forwarding` | no |
| `logout` | Drops the master, and any forward on it | no |
| `proxy-url` | Prints the URL to paste into a provider config | no |

`status --json` prints the same state as one object, for a launcher:

```json
{"state": "forwarding", "proxy_url": "socks5://127.0.0.1:10801",
 "socket": "/home/user/.ssh/argo-tunnel-user-1a2b3c4d5e6f",
 "host": "homes.cels.anl.gov", "jump": "logins.cels.anl.gov"}
```

### Where the socket lives, and how long it lasts

Both come from your own SSH setup first. The CLI reads the effective
configuration with `ssh -G`, so whatever you set globally is what gets used:

| | Your `ssh_config` sets it | You pass a flag / env | Neither |
|---|---|---|---|
| socket | `ControlPath` — used as given | `--state-dir` / `ARGO_TUNNEL_STATE_DIR`, or `--socket` / `ARGO_TUNNEL_SOCKET` for an exact path | `$XDG_CONFIG_HOME/llm-rosetta-gateway/tunnel/ssh-<hash>` (else `~/.config/…`) |
| lifetime | `ControlPersist` — used as given | `--control-persist` / `ARGO_TUNNEL_CONTROL_PERSIST` | `8h` |

```bash
llm-rosetta-argo-tunnel status --json   # "socket" tells you which one is in play
```

Three details worth knowing:

- **A `ControlMaster auto` you already configured is reused, not routed
  around.** If `ssh_config` names a `ControlPath`, that is the socket — a tool
  that invented its own would report `absent` while an authenticated master sat
  right there.
- **`ControlPersist` counts from the last *use*, not the last authentication.**
  A request through the forward counts. Measured: with `ControlPersist=20s`
  and traffic at t=12s, the master exited at t=33s — the deadline moved with
  the traffic. Under steady use the master does not expire; an idle one does.
  A request that is still in flight when the master exits fails; the next
  request needs `start` again, or `auth` if the master is gone.
- **Socket paths have a hard length limit** (`sun_path`, ~100 bytes). A deep
  `$HOME` would silently truncate; the CLI keeps your directory but shortens
  the file name, and falls back to `/tmp/argo-tunnel-<uid>` if even that is too
  long.

`--ssh-config FILE` reads an additional ssh config file (ssh still reads
`~/.ssh/config` itself).

### Configuration

Every command accepts `--host`, `--jump`, `--user`, `--bind`, `--port` and
`--control-persist` before or after the subcommand, and reads the same names
from the environment as `ARGO_TUNNEL_HOST`, `ARGO_TUNNEL_JUMP`,
`ARGO_TUNNEL_USER`, `ARGO_TUNNEL_BIND`, `ARGO_TUNNEL_PORT`,
`ARGO_TUNNEL_SOCKET` and `ARGO_TUNNEL_CONTROL_PERSIST`. `ARGO_TUNNEL_JUMP=none`
drops the jump hop, for a host already inside the network.

The defaults are the Argonne pair: `homes.cels.anl.gov` through
`logins.cels.anl.gov`, port `10801` on `127.0.0.1`.

### Notes

- **Only `auth` prompts.** Everything else runs with `BatchMode=yes`, so a
  launcher or a unit file gets a failure instead of a hung process. If `auth`
  is run while a master is already up, it says so rather than asking for a
  second approval.
- **`wedged` is a real state.** A master that does not answer (as opposed to
  one that was never there) needs `logout` first; `start` refuses it rather
  than forwarding over a dead control socket.
- **Two goals need two masters.** The control socket path is derived from the
  target, the jump host and the port, so a second target does not silently
  reuse the first one's session.
- **Containers.** An image cannot see the host's control socket or its
  `127.0.0.1`. Bind the forward to the host's bridge address
  (`--bind 172.17.0.1`) and point `proxy` at it. Never bind `0.0.0.0`: SOCKS5
  here has no authentication.

## Requirements

- Python >= 3.10
- `llm-rosetta >= 0.14.0.dev28` (needs the plugin shim loader and the
  vendor manifest)
- `ARGO_API_KEY` in the environment at request time
- for the tunnel: `ssh` on `PATH`, and an SSH account that reaches
  `homes.cels.anl.gov` through `logins.cels.anl.gov`. `llm-rosetta` itself is
  not needed for the tunnel — importing the package does not import it.

## License

MIT — see [LICENSE](LICENSE).
