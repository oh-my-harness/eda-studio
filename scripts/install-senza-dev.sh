#!/usr/bin/env bash
# 从本地 ../Senza 仓库 editable 安装 senza-sdk 到当前 venv。
#
# 用途：开发期依赖本地 Senza 源码，改 Rust/Python 后重跑此脚本即可更新。
# 不修改 Senza 仓库（PLACEHOLDER 替换在备份-恢复中完成）。
#
# 用法：
#   ./scripts/install-senza-dev.sh          # 用 .venv
#   VENV=/path/to/venv ./scripts/install-senza-dev.sh
#
# 前提：
#   - ../Senza 是 Senza 仓库 checkout
#   - 能联网 fetch runtime（Senza 的 Cargo.toml 用 git rev 锁定 runtime commit，从 GitHub fetch）
#   - 当前 venv 已装 maturin
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SENZA_DIR="$(cd "$REPO_ROOT/../Senza" && pwd)"

VENV="${VENV:-$REPO_ROOT/.venv}"
PYTHON="$VENV/bin/python"

if [ ! -d "$SENZA_DIR" ]; then
    echo "ERROR: Senza 仓库不在 $SENZA_DIR" >&2
    exit 1
fi
if [ ! -f "$VENV/bin/maturin" ] && ! "$VENV/bin/pip" show maturin >/dev/null 2>&1; then
    echo "==> 安装 maturin ..."
    "$VENV/bin/pip" install --quiet maturin
fi

LOCK_FILE="$SENZA_DIR/senza-pkg/runtime.lock"
CARGO_TOML="$SENZA_DIR/Cargo.toml"
SHA=$(cat "$LOCK_FILE")
echo "==> Senza: $SENZA_DIR"
echo "==> Runtime pin: $SHA"
echo "==> Venv: $VENV"

# 临时替换 PLACEHOLDER，构建后恢复（不污染 Senza 仓库）
cp "$CARGO_TOML" "$CARGO_TOML.bak"
trap 'mv "$CARGO_TOML.bak" "$CARGO_TOML" 2>/dev/null || true' EXIT
perl -pi -e "s/PLACEHOLDER/$SHA/g" "$CARGO_TOML"

cd "$SENZA_DIR"
# 激活目标 venv，让 maturin develop 装到正确位置
source "$VENV/bin/activate"
echo "==> maturin develop --release ..."
maturin develop --release

echo ""
echo "==> 完成。senza 已 editable 安装到 $VENV"
echo "    改 Senza Rust 源码后重跑此脚本即可更新。"
