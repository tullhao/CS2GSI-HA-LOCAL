#!/usr/bin/with-contenv bashio
set -e

cd /app
exec python3 /app/app/main.py
