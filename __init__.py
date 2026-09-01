"""Storj decentralized storage plugin for Hermes — registration.

Wires the ten `storj_*` tools to their handlers, gates write/delete/share calls
behind the human approval gate (the Hermes counterpart to OpenClaw's
`ownerOnly`), and adds a `/storj` slash command for quick browsing.
"""

from __future__ import annotations

import logging

from . import schemas, tools

logger = logging.getLogger(__name__)

_TOOLSET = schemas.TOOLSET


def _approval_hook(toolset: tools.StorjTools):
    """pre_tool_call: escalate destructive Storj calls to the approval gate.

    The setting is read per call, so toggling `confirm_destructive` takes effect
    without restarting Hermes.
    """

    def _on_pre_tool_call(tool_name: str, args: dict, task_id: str = "", **kwargs):
        del args, task_id, kwargs
        if tool_name not in schemas.DESTRUCTIVE or not toolset.confirm_destructive():
            return None
        return {
            "action": "approve",
            "message": f"{tool_name} writes to, deletes from, or shares access to Storj storage.",
            "rule_key": f"storj:{tool_name}",
        }

    return _on_pre_tool_call


def _slash_command(toolset: tools.StorjTools):
    """`/storj` — list buckets, or list objects in a bucket/prefix."""

    def handle(raw_args: str) -> str:
        parts = (raw_args or "").split()
        if not parts:
            return toolset.list_buckets({})
        bucket, prefix = parts[0], (parts[1] if len(parts) > 1 else None)
        return toolset.list_objects({"bucket": bucket, "prefix": prefix})

    return handle


def register(ctx):
    """Plugin entry point — called once at startup."""
    toolset = tools.StorjTools(ctx)
    handlers = toolset.handlers()

    for schema in schemas.ALL:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset=_TOOLSET,
            schema=schema,
            handler=handlers[name],
            check_fn=toolset.available,
            emoji=schemas.EMOJI.get(name, "🪣"),
        )

    ctx.register_hook("pre_tool_call", _approval_hook(toolset))

    register_command = getattr(ctx, "register_command", None)
    if register_command is not None:
        register_command(
            "storj",
            _slash_command(toolset),
            description="List Storj buckets, or objects: /storj <bucket> [prefix]",
        )

    if not toolset.access_grant():
        logger.info(
            "storj: no access grant configured — tools stay hidden until "
            "plugins.entries.storj.settings.access_grant or STORJ_ACCESS_GRANT is set."
        )
