#!/bin/sh
set -eu

runtime_dir=/tmp/flare_api_runtime
rm -rf "$runtime_dir"
mkdir -p "$runtime_dir"
tar --use-compress-program=unzstd -xf /home/site/wwwroot/output.tar.zst -C "$runtime_dir"
cd "$runtime_dir"
exec "$runtime_dir/antenv/bin/python" -m uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
