# hermes-plugin-storj

Storj decentralized storage plugin for [Hermes](https://hermes-agent.nousresearch.com). Upload, download, list, share, and receive files on [Storj](https://storj.io) — powered by `ctypes` bindings to [uplink-c](https://github.com/storj/uplink-c).

This is the Hermes port of [`openclaw-plugin-storj`](https://github.com/austpryb/openclaw-plugin-storj): same ten tools, same capability-based sharing model.

## Prerequisites

1. **Storj account** — sign up at [storj.io](https://storj.io) and create an access grant from the satellite UI or with `uplink share`.

2. **Native library** — this plugin needs the `libuplink` shared library:
   - **Linux:** `libuplink.so`
   - **macOS:** `libuplink.dylib`
   - **Windows:** `libuplink.dll`

   Build it from [storj/uplink-c](https://github.com/storj/uplink-c) (`make build`) or download a prebuilt binary. Put it in this plugin's `native/` directory, set `STORJ_LIBUPLINK_PATH`, or install it somewhere the system loader finds it.

## Install

```bash
hermes plugins install austpryb/hermes-plugin-storj --enable
```

Then configure the access grant — either as a plugin setting:

```bash
hermes config set plugins.entries.storj.settings.access_grant "YOUR_ACCESS_GRANT"
```

or as an environment variable:

```bash
export STORJ_ACCESS_GRANT="YOUR_ACCESS_GRANT"
```

The tools stay hidden (via `check_fn`) until both a grant and a loadable `libuplink` are present, so a half-configured install never shows the model tools it cannot run.

## Tools

| Tool | Description | Approval |
|------|-------------|:--------:|
| `storj_list_buckets` | List all buckets | |
| `storj_create_bucket` | Create a bucket | Yes |
| `storj_delete_bucket` | Delete an empty bucket | Yes |
| `storj_list_objects` | List objects (with prefix filter) | |
| `storj_stat_object` | Get object metadata | |
| `storj_delete_object` | Delete an object | Yes |
| `storj_upload` | Upload a local file | Yes |
| `storj_download` | Download to a local file | Yes |
| `storj_share` | Create a restricted access grant | Yes |
| `storj_receive` | List/download from a shared grant | |

All ten register under the `storj` toolset, so `hermes` can enable or disable them as a unit.

### Approval gating

OpenClaw's `ownerOnly` flag has no direct Hermes equivalent, so the plugin registers a `pre_tool_call` hook that returns `{"action": "approve"}` for the write, delete, and share tools. Those calls go through Hermes' normal human-approval gate; reads run unattended. Turn it off with:

```bash
hermes config set plugins.entries.storj.settings.confirm_destructive false
```

### Slash command

`/storj` lists buckets; `/storj <bucket> [prefix]` lists objects.

## Settings

Under `plugins.entries.storj.settings`:

| Setting | Default | Meaning |
|---------|---------|---------|
| `access_grant` | `""` | Serialized access grant (falls back to `STORJ_ACCESS_GRANT`) |
| `libuplink_path` | `""` | Explicit path to `libuplink` (falls back to `STORJ_LIBUPLINK_PATH`, then `native/`, then the system loader) |
| `confirm_destructive` | `true` | Route write/delete/share tools through the approval gate |
| `max_download_bytes` | `268435456` | Refuse downloads above this size (256 MiB) |

## Agent-to-agent file sharing

Agents share files using Storj's capability-based access grants:

1. **Agent A** uploads a file and calls `storj_share` to mint a scoped, read-only grant.
2. **Agent A** sends the grant string to Agent B (chat, gateway message, wherever).
3. **Agent B** calls `storj_receive` with that grant — plus the `prefix` it was scoped to — to list and download the shared files.

The grant is a macaroon: the prefix caveat is enforced by the network, not by this plugin. A grant scoped to `bucket/prefix/` denies an unscoped listing, which is why `storj_receive` takes a `prefix` argument.

## Development

```bash
# read-only checks (list buckets, tool + hook registration)
STORJ_ACCESS_GRANT=... STORJ_LIBUPLINK_PATH=/path/to/libuplink.so python3 test_plugin.py

# full round trip: upload → stat → list → download → share → receive → delete
STORJ_ACCESS_GRANT=... STORJ_LIBUPLINK_PATH=/path/to/libuplink.so python3 test_plugin.py --bucket my-bucket
```

The round trip writes under `hermes-plugin-storj-selftest/` in the bucket you name and deletes what it wrote.

## Layout

```
hermes-plugin-storj/
├── plugin.yaml      # manifest (v2): env vars, config schema, metadata
├── __init__.py      # register() — tools, approval hook, /storj command
├── schemas.py       # model-facing tool schemas
├── tools.py         # handlers (JSON-string returns, never raise)
├── uplink.py        # ctypes bindings to uplink-c
└── native/          # drop libuplink.so / .dylib / .dll here
```

## License

MIT
