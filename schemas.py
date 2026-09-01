"""Model-facing schemas for the Storj toolset.

`schema["description"]` is what the model actually reads — keep the wording here
authoritative and let the registry metadata fall back to it.
"""

TOOLSET = "storj"

STORJ_LIST_BUCKETS = {
    "name": "storj_list_buckets",
    "description": "List all buckets in the Storj project.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

STORJ_CREATE_BUCKET = {
    "name": "storj_create_bucket",
    "description": "Create a new bucket in the Storj project. Idempotent — succeeds if the bucket already exists.",
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Bucket name"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}

STORJ_DELETE_BUCKET = {
    "name": "storj_delete_bucket",
    "description": "Delete an empty bucket from the Storj project. Fails if the bucket still contains objects.",
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Bucket name to delete"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}

STORJ_LIST_OBJECTS = {
    "name": "storj_list_objects",
    "description": (
        "List objects in a Storj bucket. Optionally filter by prefix. "
        "Returns key, size, and creation date."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "Bucket name"},
            "prefix": {"type": "string", "description": "Filter by key prefix (optional)"},
            "recursive": {
                "type": "boolean",
                "description": "List recursively (default true). When false, shared prefixes are returned as folders.",
            },
        },
        "required": ["bucket"],
        "additionalProperties": False,
    },
}

STORJ_STAT_OBJECT = {
    "name": "storj_stat_object",
    "description": "Get metadata (size, created, expires) for a specific object in a Storj bucket.",
    "parameters": {
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "Bucket name"},
            "key": {"type": "string", "description": "Object key/path"},
        },
        "required": ["bucket", "key"],
        "additionalProperties": False,
    },
}

STORJ_DELETE_OBJECT = {
    "name": "storj_delete_object",
    "description": "Delete an object from a Storj bucket.",
    "parameters": {
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "Bucket name"},
            "key": {"type": "string", "description": "Object key/path to delete"},
        },
        "required": ["bucket", "key"],
        "additionalProperties": False,
    },
}

STORJ_UPLOAD = {
    "name": "storj_upload",
    "description": (
        "Upload a local file to a Storj bucket. Provide the local file path and the "
        "destination bucket; the key defaults to the file's basename."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "local_path": {
                "type": "string",
                "description": "Absolute path to the local file to upload",
            },
            "bucket": {"type": "string", "description": "Destination bucket name"},
            "key": {
                "type": "string",
                "description": "Destination object key/path. If omitted, uses the filename.",
            },
        },
        "required": ["local_path", "bucket"],
        "additionalProperties": False,
    },
}

STORJ_DOWNLOAD = {
    "name": "storj_download",
    "description": "Download an object from a Storj bucket to a local file.",
    "parameters": {
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "Source bucket name"},
            "key": {"type": "string", "description": "Object key/path to download"},
            "local_path": {
                "type": "string",
                "description": "Absolute path where the file should be saved locally",
            },
        },
        "required": ["bucket", "key", "local_path"],
        "additionalProperties": False,
    },
}

STORJ_SHARE = {
    "name": "storj_share",
    "description": (
        "Create a restricted access grant for sharing a bucket or prefix. Returns a "
        "serialized access grant string that can be handed to another person or agent, "
        "who opens it with storj_receive. The grant is read-only by default."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bucket": {"type": "string", "description": "Bucket to share"},
            "prefix": {
                "type": "string",
                "description": 'Key prefix to restrict sharing to (default "" — the whole bucket)',
            },
            "allow_download": {"type": "boolean", "description": "Allow downloads (default true)"},
            "allow_list": {"type": "boolean", "description": "Allow listing (default true)"},
            "expires_in_hours": {
                "type": "number",
                "description": "Expire the grant this many hours from now (default: never)",
            },
        },
        "required": ["bucket"],
        "additionalProperties": False,
    },
}

STORJ_RECEIVE = {
    "name": "storj_receive",
    "description": (
        "Open a shared Storj access grant to list and optionally download the files it "
        "provides. Use this when another agent or user shares an access grant string with you."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "access_grant": {
                "type": "string",
                "description": "The shared Storj access grant string",
            },
            "prefix": {
                "type": "string",
                "description": (
                    "Key prefix the grant is restricted to. Required when the sender scoped the "
                    "grant to a prefix — listing without it is denied by the macaroon caveat."
                ),
            },
            "download": {
                "type": "boolean",
                "description": "Download all files into local_dir (default false — just list)",
            },
            "local_dir": {
                "type": "string",
                "description": "Local directory to download files into (required when download is true)",
            },
        },
        "required": ["access_grant"],
        "additionalProperties": False,
    },
}

ALL = [
    STORJ_LIST_BUCKETS,
    STORJ_CREATE_BUCKET,
    STORJ_DELETE_BUCKET,
    STORJ_LIST_OBJECTS,
    STORJ_STAT_OBJECT,
    STORJ_DELETE_OBJECT,
    STORJ_UPLOAD,
    STORJ_DOWNLOAD,
    STORJ_SHARE,
    STORJ_RECEIVE,
]

# Tools that write, delete, or hand out credentials — the Hermes equivalent of
# OpenClaw's `ownerOnly`. `register()` routes these through the approval gate.
DESTRUCTIVE = {
    "storj_create_bucket",
    "storj_delete_bucket",
    "storj_delete_object",
    "storj_upload",
    "storj_download",
    "storj_share",
}

EMOJI = {
    "storj_list_buckets": "🪣",
    "storj_create_bucket": "🪣",
    "storj_delete_bucket": "🗑️",
    "storj_list_objects": "📂",
    "storj_stat_object": "🔍",
    "storj_delete_object": "🗑️",
    "storj_upload": "☁️",
    "storj_download": "⬇️",
    "storj_share": "🔗",
    "storj_receive": "📥",
}
