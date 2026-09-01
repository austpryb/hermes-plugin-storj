"""Tool handlers for the Storj toolset.

Each handler takes ``(params, **kwargs)`` and returns a JSON string with a
``success`` flag, a human-readable ``text`` summary, and structured fields the
model can act on. A short-lived project handle is opened per call and always
closed — matching the OpenClaw plugin's per-call client lifecycle.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .uplink import StorjClient, StorjError, library_available

DEFAULT_MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024

GRANT_HELP = (
    "No Storj access grant configured. Set it with:\n"
    '  hermes config set plugins.entries.storj.settings.access_grant "YOUR_GRANT"\n'
    "or export STORJ_ACCESS_GRANT in the environment."
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_bytes(size: int) -> str:
    if size == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


def format_date(epoch: int) -> str:
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ok(text: str, **fields: Any) -> str:
    return json.dumps({"success": True, "text": text, **fields}, indent=2)


def _err(error: Any) -> str:
    """Error JSON. uplink errors carry a multi-line Go trace — keep the first line."""
    message = str(error).strip()
    first, _, rest = message.partition("\n")
    payload: dict[str, Any] = {"success": False, "error": first or message}
    if rest.strip():
        payload["detail"] = message
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# Toolset
# ---------------------------------------------------------------------------


class StorjTools:
    """Holds the plugin context so handlers can resolve settings per call."""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    # -- configuration --

    def _setting(self, key: str, default: Any = None) -> Any:
        getter = getattr(self.ctx, "get_config", None)
        if getter is None:
            return default
        try:
            value = getter(key, default=default)
        except Exception:
            return default
        return default if value is None else value

    def access_grant(self) -> str:
        return str(
            self._setting("access_grant", "") or os.environ.get("STORJ_ACCESS_GRANT", "")
        ).strip()

    def libuplink_path(self) -> str:
        return str(self._setting("libuplink_path", "") or "").strip()

    def max_download_bytes(self) -> int:
        try:
            return int(self._setting("max_download_bytes", DEFAULT_MAX_DOWNLOAD_BYTES))
        except (TypeError, ValueError):
            return DEFAULT_MAX_DOWNLOAD_BYTES

    def confirm_destructive(self) -> bool:
        return bool(self._setting("confirm_destructive", True))

    # -- availability --

    def available(self) -> bool:
        """check_fn: hide the toolset unless a grant and the native library exist."""
        return bool(self.access_grant()) and library_available(self.libuplink_path())

    def _client(self, grant: str | None = None) -> StorjClient:
        grant = grant or self.access_grant()
        if not grant:
            raise ValueError(GRANT_HELP)
        return StorjClient.open(grant, self.libuplink_path())

    # -- handlers --

    def list_buckets(self, params: dict[str, Any], **kwargs: Any) -> str:
        del params, kwargs
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            buckets = client.list_buckets()
            if not buckets:
                return _ok("No buckets found.", buckets=[])
            lines = [f"- **{b['name']}** (created {format_date(b['created'])})" for b in buckets]
            return _ok(
                f"Found {len(buckets)} bucket(s):\n\n" + "\n".join(lines),
                buckets=[
                    {"name": b["name"], "created": format_date(b["created"])} for b in buckets
                ],
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def create_bucket(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        name = (params or {}).get("name", "")
        if not name:
            return _err("Parameter 'name' is required.")
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            bucket = client.create_bucket(name)
            return _ok(f"Bucket **{bucket['name']}** created.", bucket=bucket["name"])
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def delete_bucket(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        name = (params or {}).get("name", "")
        if not name:
            return _err("Parameter 'name' is required.")
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            client.delete_bucket(name)
            return _ok(f"Bucket **{name}** deleted.", bucket=name)
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def list_objects(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        bucket = params.get("bucket", "")
        if not bucket:
            return _err("Parameter 'bucket' is required.")
        prefix = params.get("prefix") or None
        recursive = params.get("recursive", True)
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            objects = client.list_objects(bucket, prefix=prefix, recursive=bool(recursive))
            if not objects:
                suffix = f' with prefix "{prefix}"' if prefix else ""
                return _ok(f"No objects found in **{bucket}**{suffix}.", objects=[])
            lines = []
            for obj in objects:
                if obj["is_prefix"]:
                    lines.append(f"- `{obj['key']}` (prefix/folder)")
                else:
                    lines.append(
                        f"- `{obj['key']}` — {format_bytes(obj['content_length'])}, "
                        f"created {format_date(obj['created'])}"
                    )
            return _ok(
                f"Found {len(objects)} object(s) in **{bucket}**:\n\n" + "\n".join(lines),
                bucket=bucket,
                objects=[
                    {
                        "key": o["key"],
                        "is_prefix": o["is_prefix"],
                        "size_bytes": o["content_length"],
                        "created": format_date(o["created"]),
                    }
                    for o in objects
                ],
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def stat_object(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        bucket, key = params.get("bucket", ""), params.get("key", "")
        if not bucket or not key:
            return _err("Parameters 'bucket' and 'key' are required.")
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            obj = client.stat_object(bucket, key)
            return _ok(
                f"`{bucket}/{obj['key']}` — {format_bytes(obj['content_length'])}, "
                f"created {format_date(obj['created'])}",
                bucket=bucket,
                key=obj["key"],
                size=format_bytes(obj["content_length"]),
                size_bytes=obj["content_length"],
                created=format_date(obj["created"]),
                expires=format_date(obj["expires"]) if obj["expires"] else None,
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def delete_object(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        bucket, key = params.get("bucket", ""), params.get("key", "")
        if not bucket or not key:
            return _err("Parameters 'bucket' and 'key' are required.")
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            client.delete_object(bucket, key)
            return _ok(f"Deleted **{key}** from **{bucket}**.", bucket=bucket, key=key)
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def upload(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        local_path = params.get("local_path", "")
        bucket = params.get("bucket", "")
        if not local_path or not bucket:
            return _err("Parameters 'local_path' and 'bucket' are required.")

        source = Path(local_path).expanduser()
        if not source.is_file():
            return _err(f"Local file not found: {source}")
        key = params.get("key") or source.name

        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            info = client.upload_file(bucket, key, source)
            size = info["content_length"]
            return _ok(
                f"Uploaded **{key}** to **{bucket}** ({format_bytes(size)}).",
                bucket=bucket,
                key=key,
                size_bytes=size,
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def download(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        bucket, key = params.get("bucket", ""), params.get("key", "")
        local_path = params.get("local_path", "")
        if not bucket or not key or not local_path:
            return _err("Parameters 'bucket', 'key', and 'local_path' are required.")

        dest = Path(local_path).expanduser()
        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            size = client.download_to_file(bucket, key, dest, max_bytes=self.max_download_bytes())
            return _ok(
                f"Downloaded **{key}** from **{bucket}** to `{dest}` ({format_bytes(size)}).",
                bucket=bucket,
                key=key,
                local_path=str(dest),
                size_bytes=size,
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def share(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        bucket = params.get("bucket", "")
        if not bucket:
            return _err("Parameter 'bucket' is required.")
        prefix = params.get("prefix") or ""
        expires_in_hours = params.get("expires_in_hours")
        not_after = 0
        if expires_in_hours:
            try:
                not_after = int(
                    datetime.now(tz=timezone.utc).timestamp() + float(expires_in_hours) * 3600
                )
            except (TypeError, ValueError):
                return _err("Parameter 'expires_in_hours' must be a number.")

        try:
            client = self._client()
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            grant = client.create_share_grant(
                bucket,
                prefix,
                allow_download=params.get("allow_download", True),
                allow_list=params.get("allow_list", True),
                not_after=not_after,
            )
            expiry_note = (
                f"\nExpires {format_date(not_after)}." if not_after else "\nNo expiry set."
            )
            return _ok(
                f"Restricted access grant for **{bucket}/{prefix}**:\n\n```\n{grant}\n```\n"
                f"Share this grant so the recipient can call `storj_receive` on it"
                + (f' with prefix "{prefix}"' if prefix else "")
                + f".{expiry_note}",
                bucket=bucket,
                prefix=prefix,
                access_grant=grant,
                expires=format_date(not_after) if not_after else None,
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    def receive(self, params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        params = params or {}
        grant = (params.get("access_grant") or "").strip()
        if not grant:
            return _err("Parameter 'access_grant' is required.")
        download = bool(params.get("download", False))
        local_dir = params.get("local_dir", "")
        if download and not local_dir:
            return _err("Parameter 'local_dir' is required when download is true.")

        try:
            client = self._client(grant)
        except (ValueError, OSError, StorjError) as exc:
            return _err(exc)
        try:
            buckets = client.list_buckets()
            if not buckets:
                return _ok("Shared grant contains no accessible buckets.", files=[])

            prefix = params.get("prefix") or None
            files = []
            denied = []
            for bucket in buckets:
                try:
                    listing = client.list_objects(bucket["name"], prefix=prefix, recursive=True)
                except StorjError as exc:
                    # A grant scoped to a prefix denies unscoped listing — the caller
                    # needs to pass the prefix the sender shared.
                    denied.append(f"{bucket['name']} ({exc.message.splitlines()[0]})")
                    continue
                for obj in listing:
                    if not obj["is_prefix"]:
                        files.append(
                            {
                                "bucket": bucket["name"],
                                "key": obj["key"],
                                "size_bytes": obj["content_length"],
                            }
                        )

            if not files:
                names = ", ".join(b["name"] for b in buckets)
                hint = ""
                if denied:
                    hint = (
                        "\n\nListing was denied for: "
                        + ", ".join(denied)
                        + "\nThe grant is probably scoped to a prefix — call this tool again with "
                        "the `prefix` the sender shared."
                    )
                return _ok(
                    f"Shared grant provides access to bucket(s): {names} — but no files found.{hint}",
                    files=[],
                    denied=denied,
                )

            listing = "\n".join(
                f"- `{f['bucket']}/{f['key']}` ({format_bytes(f['size_bytes'])})" for f in files
            )

            if not download:
                return _ok(
                    f"Shared grant contains {len(files)} file(s):\n\n{listing}\n\n"
                    "To download, call this tool again with `download: true` and a `local_dir`.",
                    files=files,
                )

            root = Path(local_dir).expanduser()
            max_bytes = self.max_download_bytes()
            saved = []
            for entry in files:
                dest = root / entry["bucket"] / entry["key"]
                client.download_to_file(entry["bucket"], entry["key"], dest, max_bytes=max_bytes)
                saved.append(str(dest))

            return _ok(
                f"Downloaded {len(saved)} file(s) to `{root}`:\n\n{listing}",
                local_dir=str(root),
                files=files,
                saved=saved,
            )
        except (StorjError, OSError) as exc:
            return _err(exc)
        finally:
            client.close()

    # -- name -> handler map used by register() --

    def handlers(self) -> dict[str, Any]:
        return {
            "storj_list_buckets": self.list_buckets,
            "storj_create_bucket": self.create_bucket,
            "storj_delete_bucket": self.delete_bucket,
            "storj_list_objects": self.list_objects,
            "storj_stat_object": self.stat_object,
            "storj_delete_object": self.delete_object,
            "storj_upload": self.upload,
            "storj_download": self.download,
            "storj_share": self.share,
            "storj_receive": self.receive,
        }
