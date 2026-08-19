#!/bin/sh
set -eu

BACKUP_DIR=/home/mlatserver/modeac-poc/backups/tar1090-phase10-20260810T091313Z
ORIGINAL_INDEX_SHA=1c616be3ca30ada8aa25bb7bcb5bdc0f4ad956b50985563365e258f38de65e59
ORIGINAL_API_SHA=8b16731a08d0af80baecd8c89fbf96ce396a8044485ed6442b3c4aae34faf354

test "$(sha256sum "$BACKUP_DIR/usr-local-share-tar1090-html/index.html" | awk '{print $1}')" = "$ORIGINAL_INDEX_SHA"
test "$(sha256sum "$BACKUP_DIR/home-mlatserver-modeac-poc-realtime/api.py" | awk '{print $1}')" = "$ORIGINAL_API_SHA"

sudo install -o root -g root -m 0644 "$BACKUP_DIR/usr-local-share-tar1090-html/index.html" /usr/local/share/tar1090/html/index.html
sudo rm -f /usr/local/share/tar1090/html/poc-mlat-overlay.js /usr/local/share/tar1090/html/poc-mlat-overlay.css
install -m 0644 "$BACKUP_DIR/home-mlatserver-modeac-poc-realtime/api.py" /home/mlatserver/modeac-poc/realtime/api.py

echo "Rollback restored the original tar1090 entry point and PoC API CORS file."
echo "No tar1090 service restart is required for static files; hard-refresh open browsers."
