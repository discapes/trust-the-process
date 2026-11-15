#!/usr/bin/env bash
# Build a standalone probe project from /root/probes/<name>/ (an adversary probe that needs its own target framework).
# Usage: project_build.sh <name>   -> /root/results/<name>/build.log ending in "build exit <code>"
set -uo pipefail
export DOTNET_ROOT=/root/.dotnet PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
OUT=/root/results/$1
rm -rf "$OUT" && mkdir -p "$OUT"
cd "/root/probes/$1" && cp /root/global.json . && dotnet build > "$OUT/build.log" 2>&1
echo "build exit $?" >> "$OUT/build.log"
