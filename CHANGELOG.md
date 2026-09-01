# Changelog

## 0.1.0 — 2026-09-01

First release. Hermes port of [`openclaw-plugin-storj`](https://github.com/austpryb/openclaw-plugin-storj).

- Ten `storj_*` tools under the `storj` toolset: list/create/delete buckets,
  list/stat/delete objects, upload, download, share, receive.
- `ctypes` bindings to `uplink-c`, replacing the OpenClaw build's koffi FFI.
- Uploads and downloads stream in 1 MiB chunks, so object size does not drive
  memory use. Downloads land on a `.part` file and are renamed on success.
- Write, delete, and share tools route through Hermes' human-approval gate via a
  `pre_tool_call` hook — the counterpart to OpenClaw's `ownerOnly`. Toggle with
  the `confirm_destructive` setting.
- `check_fn` hides the toolset until an access grant and a loadable `libuplink`
  are both present.
- `/storj [bucket] [prefix]` slash command.
- Two bugs found while porting, fixed here and not present upstream at 0.1.1:
  - EOF from `uplink_download_read` is code `-1` with a NULL message; the
    OpenClaw build treats any error as EOF, hiding real read failures.
  - `storj_receive` on a prefix-scoped grant was denied by the macaroon caveat
    because it listed without a prefix. `storj_receive` now takes `prefix` and
    degrades per bucket instead of failing outright.
