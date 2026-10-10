#!/usr/bin/env bash
# Existing-resource Cloud Shell operator. Default mode is READ ONLY.
set -euo pipefail
umask 077
mode=${1:-check}
case "$mode" in check|migrate) ;; *) exit 64 ;; esac
flare_ops005_root=$(mktemp -d /tmp/flare-ops005.XXXXXX)
trap 'rm -rf -- "$flare_ops005_root"' EXIT
git clone -q https://github.com/VladimirMalevanik/flare.git "$flare_ops005_root/source"
git -C "$flare_ops005_root/source" checkout -q 7365f5342e08561567206de38c224620dcc00d6e
python3 -m venv "$flare_ops005_root/venv"
# Match versions in the verified immutable Linux runtime package.
"$flare_ops005_root/venv/bin/pip" install -q \
  'alembic==1.20.0' 'psycopg[binary]==3.3.6' \
  'SQLAlchemy==2.1.4' 'python-dotenv==1.2.4'
curl -fsS https://raw.githubusercontent.com/VladimirMalevanik/flare/53991dc03ced80f6452639ad31f139775942b6b8/docs/implementation/OPS-005/cloud_migration_operator.py \
  -o "$flare_ops005_root/operator.py"
printf '7d37df4a9a06fb92331725fa3f4dac5206e64f11a8f75ac57636adabbe866405  %s\n' "$flare_ops005_root/operator.py" | sha256sum -c -
cd "$flare_ops005_root/source"
"$flare_ops005_root/venv/bin/python" "$flare_ops005_root/operator.py" "$mode"
