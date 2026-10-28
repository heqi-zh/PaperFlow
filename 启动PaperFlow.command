#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ ! -x ./.venv/bin/python ]]; then
  print -u2 '请先按照 README 安装依赖并创建 .venv。'
  exit 1
fi
exec ./.venv/bin/python scripts/launch_desktop.py "$@"
