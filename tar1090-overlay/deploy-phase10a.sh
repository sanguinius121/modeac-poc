#!/bin/sh
set -eu

ROOT=/home/mlatserver/modeac-poc
WEBROOT=/usr/local/share/tar1090/html
ORIGINAL_INDEX_SHA=1c616be3ca30ada8aa25bb7bcb5bdc0f4ad956b50985563365e258f38de65e59
PREVIOUS_INDEX_SHA=20a0c5d6eee17218866f0923aadb6838a597038f5138daeddde64becc51f11ae
PREVIOUS_INDEX_SHA_B=2efa16bbaccc23dff9d0802a6c70d2332215cd97e2aaae9e648d8ef9df7dd9b4
PREVIOUS_INDEX_SHA_FIT=7cf2bfc1594b89683f621feaa94dad4cf5c20461963758751ced3c3c57345d0b
STAGED_INDEX_SHA=$(sha256sum "$ROOT/tar1090-overlay/stage/index.html" | awk '{print $1}')
CURRENT_INDEX_SHA=$(sha256sum "$WEBROOT/index.html" | awk '{print $1}')

if [ "$CURRENT_INDEX_SHA" != "$ORIGINAL_INDEX_SHA" ] && [ "$CURRENT_INDEX_SHA" != "$PREVIOUS_INDEX_SHA" ] && [ "$CURRENT_INDEX_SHA" != "$PREVIOUS_INDEX_SHA_B" ] && [ "$CURRENT_INDEX_SHA" != "$PREVIOUS_INDEX_SHA_FIT" ] && [ "$CURRENT_INDEX_SHA" != "$STAGED_INDEX_SHA" ]; then
  echo "Refusing deployment: production index.html changed after the Phase 10 backup." >&2
  echo "Current:  $CURRENT_INDEX_SHA" >&2
  echo "Expected: $ORIGINAL_INDEX_SHA or $STAGED_INDEX_SHA" >&2
  exit 1
fi

sudo install -o root -g root -m 0644 "$ROOT/tar1090-overlay/poc-mlat-overlay.js" "$WEBROOT/poc-mlat-overlay.js"
sudo install -o root -g root -m 0644 "$ROOT/tar1090-overlay/poc-mlat-overlay.css" "$WEBROOT/poc-mlat-overlay.css"
sudo install -o root -g root -m 0644 "$ROOT/tar1090-overlay/stage/index.html" "$WEBROOT/index.html"

test "$(sha256sum "$WEBROOT/index.html" | awk '{print $1}')" = "$STAGED_INDEX_SHA"
test "$(sha256sum "$WEBROOT/poc-mlat-overlay.js" | awk '{print $1}')" = "$(sha256sum "$ROOT/tar1090-overlay/poc-mlat-overlay.js" | awk '{print $1}')"
test "$(sha256sum "$WEBROOT/poc-mlat-overlay.css" | awk '{print $1}')" = "$(sha256sum "$ROOT/tar1090-overlay/poc-mlat-overlay.css" | awk '{print $1}')"

echo "Current reviewed Phase 10 overlay deployed. No service restart was performed."
echo "Hard-refresh http://100.100.24.4/tar1090/"
