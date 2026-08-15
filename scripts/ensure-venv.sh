#!/usr/bin/env bash
# Synchronize the repository-local environment without requiring shell activation.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required; install it before running bootstrap" >&2
  exit 1
fi

UV_LINK_MODE=copy uv sync --all-groups --frozen

