#!/usr/bin/env bash
# 将 plugins/moviepilotapppush 同步到 plugins.v2/moviepilotapppush
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/plugins/moviepilotapppush"
DST="$ROOT/plugins.v2/moviepilotapppush"

if [[ ! -d "$SRC" ]]; then
  echo "源目录不存在: $SRC" >&2
  exit 1
fi

mkdir -p "$DST"
rsync -a --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  "$SRC/" "$DST/"

echo "已同步: $SRC -> $DST"
