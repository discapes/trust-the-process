#!/usr/bin/env bash
# Build and test the MessagePack-CSharp working tree (after checking out <ref> if given); writes build.log, test.log and TRX files to /root/results/<name>/
# Runs on the earned-trust-dotnet Verda instance, repo at /root/mp. Usage: suite.sh <name> [ref]
# /root/global.json pins SDK 9 because the Roslyn 4.12 generator does not load in the SDK 8.0.402 that the repo pins.
set -uo pipefail
export DOTNET_ROOT=/root/.dotnet PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
NAME=$1 REF=${2:-} OUT=/root/results/$1
cd /root/mp
[ -n "$REF" ] && { git checkout -q --force "$REF" && git clean -qfdx || exit 1; }
cp /root/global.json global.json
rm -rf "$OUT" && mkdir -p "$OUT"
dotnet build -c Release > "$OUT/build.log" 2>&1
echo "build exit $?" | tee -a "$OUT/build.log"
dotnet test --no-build -c Release --filter "TestCategory!=FailsInCloudTest" \
  --logger "trx;LogFilePrefix=$NAME" --results-directory "$OUT" > "$OUT/test.log" 2>&1
echo "test exit $?" | tee -a "$OUT/test.log"
grep -E "^(Passed|Failed)!" "$OUT/test.log"
