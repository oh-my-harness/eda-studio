#!/usr/bin/env bash
# Uninstall the editable-installed Senza, falling back to the PyPI
# version declared in pyproject.toml.
#
# Pairs with install-senza-dev.sh. Uses the repo venv (created on
# demand by Senza's _venv.sh helper) for the pip uninstall.
#
# Usage:
#   ./scripts/uninstall-senza-dev.sh
#   VENV=/path/to/venv ./scripts/uninstall-senza-dev.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SENZA_DIR="${SENZA_DIR:-$(cd "$REPO_ROOT/../Senza" && pwd)}"

if [ ! -f "$SENZA_DIR/scripts/_venv.sh" ]; then
    echo "ERROR: $SENZA_DIR/scripts/_venv.sh 不存在（Senza 版本太旧，需要 >=0.4.3）" >&2
    exit 1
fi

# Reuse Senza's venv helper for a consistent venv location.
# shellcheck source=/dev/null
. "$SENZA_DIR/scripts/_venv.sh"
ensure_venv
if "$PYTHON" -m pip show senza-sdk >/dev/null 2>&1; then
    echo "==> 卸载本地 senza-sdk ..."
    "$PYTHON" -m pip uninstall -y senza-sdk
else
    echo "==> 未发现 senza-sdk 安装，跳过"
fi

echo ""
echo "==> 完成。如需恢复 PyPI 版本："
echo "    $PYTHON -m pip install senza-sdk"
