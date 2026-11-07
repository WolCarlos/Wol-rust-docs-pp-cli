#!/usr/bin/env sh
set -eu

REPOSITORY="git+https://github.com/WolCarlos/Wol-rust-docs-pp-cli.git"

if command -v uv >/dev/null 2>&1; then
    uv tool install --force "$REPOSITORY"
elif command -v python3 >/dev/null 2>&1; then
    python3 -m pip install --user "$REPOSITORY"
elif command -v python >/dev/null 2>&1; then
    python -m pip install --user "$REPOSITORY"
else
    echo "Python 3.11+ or uv is required." >&2
    exit 1
fi

rust-docs-pp-cli sync
printf '\nInstalled. Try: rust-docs-pp-cli which "borrow checker" --json\n'
