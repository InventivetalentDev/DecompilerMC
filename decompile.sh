#!/bin/bash
# Decompile both sides of a version into ./src/<version>/{client,server}.
# This only decompiles -- use ./publish.py to also commit into the mc repos.
#
#   ./decompile.sh 26.3-snapshot-9
#   PYTHON=python.exe ./decompile.sh latest
set -euo pipefail

version=${1:?usage: $0 <version|latest|snapshot>}
python=${PYTHON:-python3}

rm -f ./versions/version_manifest.json
rm -rf "./src/$version" "./versions/$version" "./mappings/$version"

# -y so neither run blocks on a prompt; they are independent so run them together
"$python" ./main.py -y client "$version" &
pid1=$!
sleep 1  # breaks for some reason if you launch these too quickly
"$python" ./main.py -y server "$version" &
pid2=$!

wait $pid1
wait $pid2
echo "done -> ./src/$version"
