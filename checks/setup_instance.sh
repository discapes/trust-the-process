#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 Verda instance for the checks: git, ICU, legacy time zones (a test needs "Cuba"),
# the fork with every ju26-* branch in /root/mp, .NET SDK 8.0.402 (pinned) and 9.0 (the one actually used), and
# /root/global.json selecting SDK 9, which suite.sh copies over the repo's pin.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -qq update >/dev/null && apt-get -qq install -y git libicu74 tzdata-legacy rsync >/dev/null
[ -d /root/mp ] || git clone -q https://github.com/te-industry-tech-office/junction26-messagepack-csharp /root/mp
git -C /root/mp fetch -q origin "+refs/heads/ju26-*:refs/remotes/origin/ju26-*"
curl -sSL https://dot.net/v1/dotnet-install.sh -o /root/dotnet-install.sh
bash /root/dotnet-install.sh --version 8.0.402 --install-dir /root/.dotnet >/dev/null
bash /root/dotnet-install.sh --channel 9.0 --install-dir /root/.dotnet >/dev/null
V=$(ls /root/.dotnet/sdk | grep '^9' | tail -1)
printf '{"sdk":{"version":"%s","rollForward":"latestFeature"}}\n' "$V" > /root/global.json
mkdir -p /root/results /root/wt /root/probes /root/patches
echo "ready: SDK $V"
