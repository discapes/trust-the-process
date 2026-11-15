#!/usr/bin/env bash
# Run selected tests of a ref in a throwaway worktree, after optionally reverting a patch and adding test files.
# Results (test.log, TRX) go to /root/results/<name>/. Used for per-claim reverts and adversary probes.
# Usage: wt_test.sh <name> <ref> <test filter> "<test project dirs>" <patch to revert or -> [<file>:<dest dir>]...
set -uo pipefail
export DOTNET_ROOT=/root/.dotnet PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
NAME=$1 REF=$2 FILTER=$3 PROJS=$4 PATCH=$5; shift 5
WT=/root/wt/$NAME OUT=/root/results/$NAME
rm -rf "$OUT" && mkdir -p "$OUT"
git -C /root/mp worktree remove --force "$WT" 2>/dev/null
git -C /root/mp worktree add -q --detach "$WT" "$REF" > "$OUT/test.log" 2>&1 || { echo "worktree failed" >> "$OUT/test.log"; exit 1; }
cd "$WT" && cp /root/global.json global.json
if [ "$PATCH" != - ]; then
  git apply -R --whitespace=nowarn "$PATCH" >> "$OUT/test.log" 2>&1 || { echo "patch failed" >> "$OUT/test.log"; exit 1; }
fi
for f in "$@"; do cp "${f%%:*}" "${f#*:}/"; done
for p in $PROJS; do
  dotnet test "tests/$p" -c Release --filter "$FILTER" --logger "trx;LogFilePrefix=$p" --results-directory "$OUT" >> "$OUT/test.log" 2>&1
done
echo "test exit $?" >> "$OUT/test.log"
cd / && git -C /root/mp worktree remove --force "$WT"
