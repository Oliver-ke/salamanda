#!/usr/bin/env bash
# Builds build/lambdas.zip for the intake and task Lambdas (arm64, Python 3.13).
# boto3 is bundled because the managed runtime's copy may predate lambda-microvms.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/build/lambdas"
rm -rf "$out" "$root/build/lambdas.zip"
mkdir -p "$out"
uv pip install --quiet --target "$out" --python-version 3.13 \
  --python-platform aarch64-manylinux2014 --only-binary :all: \
  "boto3>=1.43" httpx "pyjwt[crypto]"
cp -r "$root/agent/src/loop_agent" "$out/"
find "$out" -name __pycache__ -prune -exec rm -rf {} +
(cd "$out" && zip -qr "$root/build/lambdas.zip" .)
echo "$root/build/lambdas.zip"
