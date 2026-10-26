#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
if [[ ! -x ./.venv/bin/paperflow ]]; then
  print -u2 '请先按照 README 安装依赖并创建 .venv。'
  exit 1
fi
exec ./.venv/bin/paperflow gui --host 127.0.0.1 --port 8766
