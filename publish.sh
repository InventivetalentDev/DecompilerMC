#!/bin/bash
# Decompile version(s) and commit them into ../minecraft-decompile (and ../minecraft-mappings
# for versions that still have mappings). Never pushes -- it prints the push commands.
#
#   ./publish.sh 26.3-snapshot-9        # one version
#   ./publish.sh latest snapshot        # manifest aliases
#   ./publish.sh --missing              # everything released since the newest branch present
#   ./publish.sh --missing --limit 3 -n # dry run
#
# Every publish.py flag is passed straight through; see ./publish.py --help.
#
# Overridable:
#   PYTHON    interpreter to use            (default: python3, or python.exe if that is all there is)
#   GIT_BIN   git binary publish.py calls   (default: git.exe under WSL on /mnt, else git)
#   JAVA_BIN  java binary main.py calls     (default: auto-detected)
set -euo pipefail

cd "$(dirname "$0")"

if [ $# -eq 0 ]; then
    echo "usage: $0 <version...|--missing> [publish.py flags]" >&2
    echo "       see ./publish.py --help" >&2
    exit 2
fi

if [ -z "${PYTHON:-}" ]; then
    if command -v python3 >/dev/null 2>&1; then PYTHON=python3
    elif command -v python.exe >/dev/null 2>&1; then PYTHON=python.exe
    else echo "no python3 or python.exe on PATH" >&2; exit 1
    fi
fi

# Under WSL the Linux git takes ~2min for a status on minecraft-decompile; git.exe takes ~1s.
# publish.py pins the commit identity to the repo's own history, so the two agree on the author.
if [ -z "${GIT_BIN:-}" ] && grep -qi microsoft /proc/version 2>/dev/null \
   && command -v git.exe >/dev/null 2>&1 && [ "${PWD#/mnt/}" != "$PWD" ]; then
    export GIT_BIN=git.exe
    echo "[publish.sh] using git.exe (much faster on /mnt); override with GIT_BIN=git"
fi

exec "$PYTHON" ./publish.py "$@"
