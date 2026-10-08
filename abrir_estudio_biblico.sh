#!/usr/bin/env bash
set -euo pipefail
URL="http://127.0.0.1:8765"
systemctl --user start mi-estudio-biblico.service
for intento in {1..30}; do
    if curl -fsS "$URL/api/books" >/dev/null 2>&1; then
        if command -v firefox >/dev/null 2>&1; then
            setsid -f firefox --new-window "$URL" >/dev/null 2>&1 || true
        else
            xdg-open "$URL" >/dev/null 2>&1 || true
        fi
        exit 0
    fi
    sleep 0.25
done
if command -v firefox >/dev/null 2>&1; then
    setsid -f firefox --new-window "$URL" >/dev/null 2>&1 || true
else
    xdg-open "$URL" >/dev/null 2>&1 || true
fi
