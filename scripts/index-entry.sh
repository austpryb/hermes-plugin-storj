#!/usr/bin/env bash
# Print this plugin's entry for the Hermes community plugin index, pinned to the
# current HEAD. Submit it as a pull request to:
#   https://github.com/NousResearch/hermes-plugin-index
set -euo pipefail
cd "$(dirname "$0")/.."

sha=$(git rev-parse HEAD)
if ! git diff --quiet HEAD -- || [ -n "$(git status --porcelain)" ]; then
  echo "warning: working tree is dirty — the pinned SHA will not match what you publish" >&2
fi

cat <<JSON
{
  "name": "hermes-plugin-storj",
  "description": "Storj decentralized storage — upload, download, list, share, and receive files on the Storj network.",
  "author": "austpryb",
  "tags": ["storage", "storj", "files", "decentralized"],
  "repo": "austpryb/hermes-plugin-storj",
  "ref": "${sha}",
  "subdir": null,
  "homepage": "https://github.com/austpryb/hermes-plugin-storj",
  "capabilities": ["tools"],
  "api_version": 1,
  "added_at": "$(date -u +%Y-%m-%d)"
}
JSON
