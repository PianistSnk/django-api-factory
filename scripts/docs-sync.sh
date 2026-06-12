#!/usr/bin/env bash
# Sync examples/*/README.md → docs/examples/*/README.md for mkdocs build.
#
# Why: the canonical README for each example lives in `examples/` (so
# GitHub renders it nicely when you browse the repo). The mkdocs site
# under `docs/` needs the same content to render the Examples section.
# Rather than maintain two copies by hand, this script syncs them.
#
# Run this before `mkdocs build` (or just commit if you've already
# changed `examples/*/README.md` and the docs build is local).
#
# The .gitignore excludes docs/examples/ so this doesn't show up as
# untracked noise.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p docs/examples/jsonplaceholder docs/examples/local-mock

cp examples/README.md docs/examples/README.md
cp examples/jsonplaceholder/README.md docs/examples/jsonplaceholder/README.md
cp examples/local-mock/README.md docs/examples/local-mock/README.md

echo "Synced 3 README files to docs/examples/"
