#!/usr/bin/env bash
set -euo pipefail

runtime_dir=/tmp/flare_worker_runtime
rm -rf "$runtime_dir"
mkdir -p "$runtime_dir"
tar --use-compress-program=unzstd -xf /home/site/wwwroot/output.tar.zst -C "$runtime_dir"
cd "$runtime_dir"

python_bin="$runtime_dir/antenv/bin/python"
"$python_bin" -m app.workers.health_server &
health_pid=$!
"$python_bin" -m app.workers.analysis_worker &
worker_pid=$!

cleanup() {
  kill "$health_pid" "$worker_pid" 2>/dev/null || true
  wait "$health_pid" "$worker_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM
set +e
wait -n "$health_pid" "$worker_pid"
status=$?
set -e
exit "$status"
