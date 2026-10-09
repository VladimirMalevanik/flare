#!/usr/bin/env bash
set -euo pipefail

umask 077
runtime_dir=$(mktemp -d /tmp/flare_worker_runtime.XXXXXX)
pids=()

cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]-}"; do
    [[ -n "$pid" ]] || continue
    kill -TERM "$pid" 2>/dev/null || true
  done
  deadline=$((SECONDS + 30))
  while (( SECONDS < deadline )); do
    running=false
    for pid in "${pids[@]-}"; do
      [[ -n "$pid" ]] || continue
      if kill -0 "$pid" 2>/dev/null; then running=true; fi
    done
    if [[ "$running" == false ]]; then break; fi
    sleep 1
  done
  for pid in "${pids[@]-}"; do
    [[ -n "$pid" ]] || continue
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  rm -rf "$runtime_dir"
}

trap cleanup EXIT
trap 'exit 0' INT TERM
tar --use-compress-program=unzstd -xf /home/site/wwwroot/output.tar.zst -C "$runtime_dir"
cd "$runtime_dir"
export FLARE_WORKER_HEARTBEAT_DIR="$runtime_dir/heartbeats"
mkdir -p "$FLARE_WORKER_HEARTBEAT_DIR"

case "${FLARE_IMPORT_ENABLED:-false}" in
  true|false) ;;
  *) exit 1 ;;
esac

python_bin="$runtime_dir/antenv/bin/python"
"$python_bin" -m app.workers.health_server &
pids+=("$!")
"$python_bin" -m app.workers.analysis_worker &
pids+=("$!")
if [[ "${FLARE_IMPORT_ENABLED:-false}" == true ]]; then
  "$python_bin" -m app.workers.import_worker --mode jobs &
  pids+=("$!")
  "$python_bin" -m app.workers.import_worker --mode cleanup &
  pids+=("$!")
fi

# A failed consumer must stop the whole app, including its readiness endpoint.
# Polling also works on older Bash versions without wait -n.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      set +e
      wait "$pid"
      status=$?
      set -e
      if (( status == 0 )); then status=1; fi
      exit "$status"
    fi
  done
  sleep 1
done
