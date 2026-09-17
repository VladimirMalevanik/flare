#!/bin/sh
set -eu

runtime_dir=/tmp/flare_api_runtime
rm -rf "$runtime_dir"
mkdir -p "$runtime_dir"
tar --use-compress-program=unzstd -xf /home/site/wwwroot/output.tar.zst -C "$runtime_dir"

# The built-in Azure Python image cannot install Debian's ffmpeg package within
# its startup deadline. Keep a checksum-pinned, unprivileged ffprobe in the
# persistent /home volume instead. An operator-provided path always wins.
if [ -z "${VOICE_FFPROBE_PATH:-}" ]; then
  ffprobe_path=/home/site/flare-tools/ffprobe-7.0.2/ffprobe
  ensure_script="$(dirname "$0")/ensure_ffprobe.py"
  if python3 "$ensure_script" --destination "$ffprobe_path"; then
    export VOICE_FFPROBE_PATH="$ffprobe_path"
  else
    echo "warning: ffprobe bootstrap failed; voice transcription remains unavailable" >&2
  fi
fi

cd "$runtime_dir"
exec "$runtime_dir/antenv/bin/python" -m uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
