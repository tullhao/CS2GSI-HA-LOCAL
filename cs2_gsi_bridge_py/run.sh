#!/usr/bin/with-contenv bashio
set -e

cd /app
exec /opt/venv/bin/python /app/app/main.py
