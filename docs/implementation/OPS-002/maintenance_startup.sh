#!/bin/sh
set -eu
runtime_dir=/tmp/flare_api_runtime
rm -rf "$runtime_dir"
mkdir -p "$runtime_dir"
tar --use-compress-program=unzstd -xf /home/site/wwwroot/output.tar.zst -C "$runtime_dir"
exec python3 /home/LogFiles/flare-ops002-maintenance-server.py
