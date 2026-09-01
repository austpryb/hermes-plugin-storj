#!/usr/bin/env python3
"""Smoke test for the Storj Hermes plugin.

Offline checks (registration, schemas, approval hook) always run — they need
neither credentials nor the native library, so CI can run them:

    python3 test_plugin.py

With STORJ_ACCESS_GRANT and a loadable libuplink (STORJ_LIBUPLINK_PATH or
./native/), the live checks run too:

    STORJ_ACCESS_GRANT=... python3 test_plugin.py                     # read-only
    STORJ_ACCESS_GRANT=... python3 test_plugin.py --bucket my-bucket  # round trip

The round trip writes under `hermes-plugin-storj-selftest/` in the bucket you
name and deletes what it wrote.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Load this directory as a package so the plugin's relative imports resolve,
# regardless of what the install directory is named.
_PKG_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "storj_plugin", _PKG_DIR / "__init__.py", submodule_search_locations=[str(_PKG_DIR)]
)
plugin = importlib.util.module_from_spec(_spec)
sys.modules["storj_plugin"] = plugin
_spec.loader.exec_module(plugin)


class FakeCtx:
    """Minimal stand-in for Hermes' PluginContext."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.tools = {}
        self.hooks = {}
        self.commands = {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kwargs}

    def register_hook(self, event, callback):
        self.hooks.setdefault(event, []).append(callback)

    def register_command(self, name, handler, description=""):
        self.commands[name] = handler


def call(ctx, name, **params):
    result = json.loads(ctx.tools[name]["handler"](params))
    status = "ok  " if result.get("success") else "FAIL"
    summary = result.get("text") or result.get("error", "")
    print(f"  [{status}] {name}: {summary.splitlines()[0][:120]}")
    return result


def check_offline() -> FakeCtx:
    """Registration, schema shape, and approval gating — no credentials needed."""
    print("offline checks:")
    ctx = FakeCtx()
    plugin.register(ctx)

    expected = {s["name"] for s in plugin.schemas.ALL}
    assert set(ctx.tools) == expected, f"missing tools: {expected ^ set(ctx.tools)}"
    assert len(expected) == 10, f"expected 10 tools, got {len(expected)}"
    print(
        f"  [ok  ] registered {len(ctx.tools)} tools, "
        f"{len(ctx.hooks)} hook(s), {len(ctx.commands)} command(s)"
    )

    for name, entry in ctx.tools.items():
        schema = entry["schema"]
        assert entry["toolset"] == "storj", f"{name}: wrong toolset"
        assert schema["name"] == name, f"{name}: schema name mismatch"
        assert schema.get("description"), f"{name}: missing model-facing description"
        params = schema["parameters"]
        assert params["type"] == "object", f"{name}: parameters must be an object"
        for required in params.get("required", []):
            assert required in params["properties"], f"{name}: required '{required}' undeclared"
        json.dumps(schema)  # must survive serialization to the model
        assert callable(entry.get("check_fn")), f"{name}: no availability check"
    print("  [ok  ] all schemas well-formed and serializable")

    hook = ctx.hooks["pre_tool_call"][0]
    for name in plugin.schemas.DESTRUCTIVE:
        directive = hook(name, {}, "")
        assert directive and directive["action"] == "approve", f"{name} not gated"
    for name in expected - plugin.schemas.DESTRUCTIVE:
        assert hook(name, {}, "") is None, f"{name} should not need approval"
    print(f"  [ok  ] approval hook gates {len(plugin.schemas.DESTRUCTIVE)} destructive tools only")

    relaxed = FakeCtx({"confirm_destructive": False})
    plugin.register(relaxed)
    assert relaxed.hooks["pre_tool_call"][0]("storj_upload", {}, "") is None
    print("  [ok  ] confirm_destructive=false disables gating")

    unconfigured = FakeCtx({"access_grant": ""})
    plugin.register(unconfigured)
    saved = os.environ.pop("STORJ_ACCESS_GRANT", None)
    try:
        assert not unconfigured.tools["storj_upload"]["check_fn"](), (
            "tools must stay hidden without a grant"
        )
        result = json.loads(unconfigured.tools["storj_list_buckets"]["handler"]({}))
        assert not result["success"] and "access grant" in result["error"].lower()
    finally:
        if saved is not None:
            os.environ["STORJ_ACCESS_GRANT"] = saved
    print("  [ok  ] unconfigured plugin hides tools and explains itself")
    return ctx


def check_live(ctx, bucket: str | None, size_mb: float) -> None:
    print("\nlive read-only checks:")
    buckets = call(ctx, "storj_list_buckets")
    assert buckets["success"], "could not list buckets"

    if not bucket:
        print("\nno --bucket given; skipping the write round trip")
        return

    key = f"hermes-plugin-storj-selftest/{int(time.time())}.bin"
    payload = os.urandom(int(size_mb * 1024 * 1024)) if size_mb else b"hermes-plugin-storj\n"

    print(f"\nround trip in {bucket} ({len(payload)} bytes):")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "upload.bin"
        src.write_bytes(payload)

        assert call(ctx, "storj_upload", local_path=str(src), bucket=bucket, key=key)["success"]

        stat = call(ctx, "storj_stat_object", bucket=bucket, key=key)
        assert stat["success"] and stat["size_bytes"] == len(payload), "size mismatch after upload"

        listed = call(
            ctx, "storj_list_objects", bucket=bucket, prefix="hermes-plugin-storj-selftest/"
        )
        assert listed["success"] and any(o["key"] == key for o in listed["objects"])

        dest = Path(tmp) / "download.bin"
        assert call(ctx, "storj_download", bucket=bucket, key=key, local_path=str(dest))["success"]
        assert dest.read_bytes() == payload, "downloaded bytes differ from uploaded bytes"
        assert not dest.with_name(dest.name + ".part").exists(), "partial file left behind"
        print("  [ok  ] byte-for-byte round trip")

        share = call(ctx, "storj_share", bucket=bucket, prefix="hermes-plugin-storj-selftest/")
        assert share["success"]
        received = call(
            ctx,
            "storj_receive",
            access_grant=share["access_grant"],
            prefix="hermes-plugin-storj-selftest/",
        )
        assert received["success"] and any(f["key"] == key for f in received["files"])

        missing = call(ctx, "storj_stat_object", bucket=bucket, key=f"{key}.nope")
        assert not missing["success"], "stat of a missing object should fail"
        print("  [ok  ] missing objects report a clean error")

        assert call(ctx, "storj_delete_object", bucket=bucket, key=key)["success"]

    leftovers = call(
        ctx, "storj_list_objects", bucket=bucket, prefix="hermes-plugin-storj-selftest/"
    )
    assert leftovers["success"] and not leftovers["objects"], "self-test left objects behind"
    print("  [ok  ] no test objects left behind")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", help="Bucket to use for the read/write round trip")
    parser.add_argument(
        "--size-mb",
        type=float,
        default=4,
        help="Round-trip payload size in MiB (default 4, exercises chunked streaming)",
    )
    args = parser.parse_args()

    ctx = check_offline()

    if not os.environ.get("STORJ_ACCESS_GRANT"):
        print("\nSTORJ_ACCESS_GRANT not set — skipping live checks")
        return 0
    if not ctx.tools["storj_list_buckets"]["check_fn"]():
        print(
            "\nlibuplink not loadable — skipping live checks "
            "(set STORJ_LIBUPLINK_PATH or populate native/)"
        )
        return 0

    check_live(ctx, args.bucket, args.size_mb)
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
