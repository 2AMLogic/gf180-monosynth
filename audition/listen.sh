#!/usr/bin/env bash
# Play the three contact sheets back to back, with a spoken label before each.
set -euo pipefail
cd "$(dirname "$0")"
for e in monosynth drums fm; do
  say "$e" 2>/dev/null || true
  afplay "audio/00-$e-all.wav"
done
