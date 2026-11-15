#!/usr/bin/env bash
# Fail-before setup: check out <branch>, put every file it changed under src/ back to the base commit, then build and test.
# Tests that pass at the branch head and fail here exercise the change. Usage: revert_src.sh <name> <branch>
set -uo pipefail
NAME=$1 B=$2
cd /root/mp
git checkout -q --force --detach "$B" && git clean -qfdx || exit 1
git diff --name-only --diff-filter=MD "$B~1" "$B" -- src | xargs -r git checkout -q "$B~1" --
git diff --name-only --diff-filter=A "$B~1" "$B" -- src | xargs -r rm -f
git status --short
exec /root/suite.sh "$NAME"
