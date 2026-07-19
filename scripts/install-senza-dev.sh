#!/usr/bin/env bash
# Editable-install the local Senza source into this project's venv.
#
# Intended for eda-studio (or any downstream project) that depends on
# senza-sdk and wants to hack on Senza's Rust source alongside. Run
# from this project; Senza must be checked out at ../Senza (override
# with SENZA_DIR=...).
#
# Uses `maturin develop --release` so edits to Senza's Rust code are
# picked up on re-run. Senza's Cargo.toml rev=PLACEHOLDER is injected
# from runtime.lock and restored on exit — Senza's working tree is
# never polluted.
#
# The venv lives at .venv/ and is created on demand by Senza's
# _venv.sh helper (which picks a linkable base Python — Homebrew /
# python.org — skipping the Xcode-bundled Python3.framework that
# cannot link libpython for maturin's build step).
#
# Usage:
#   ./scripts/install-senza-dev.sh
#   VENV=/path/to/venv ./scripts/install-senza-dev.sh
#   SENZA_DIR=/path/to/Senza ./scripts/install-senza-dev.sh
#   BASE_PYTHON=/opt/homebrew/bin/python3.12 ./scripts/install-senza-dev.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SENZA_DIR="${SENZA_DIR:-$(cd "$REPO_ROOT/../Senza" && pwd)}"

if [ ! -d "$SENZA_DIR" ]; then
    echo "ERROR: Senza 仓库不在 $SENZA_DIR" >&2
    echo "       设置 SENZA_DIR=/path/to/Senza 或把 Senza checkout 到 ../Senza" >&2
    exit 1
fi
if [ ! -f "$SENZA_DIR/scripts/_venv.sh" ]; then
    echo "ERROR: $SENZA_DIR/scripts/_venv.sh 不存在（Senza 版本太旧，需要 >=0.4.3）" >&2
    exit 1
fi

# Reuse Senza's venv helper. REPO_ROOT points at THIS project so the
# venv is created here, not inside the Senza checkout.
# shellcheck source=/dev/null
. "$SENZA_DIR/scripts/_venv.sh"
ensure_venv

# Ensure maturin is present in the venv.
if ! "$PYTHON" -c "import maturin" >/dev/null 2>&1; then
    echo "==> 安装 maturin ..."
    "$PYTHON" -m pip install --quiet "maturin>=1.7"
fi

LOCK_FILE="$SENZA_DIR/senza-pkg/runtime.lock"
CARGO_TOML="$SENZA_DIR/Cargo.toml"
SHA=$(cat "$LOCK_FILE")
echo "==> Senza: $SENZA_DIR"
echo "==> Runtime pin: $SHA"
echo "==> Venv: $VENV"

# Temporarily inject the runtime SHA into Senza's Cargo.toml, restore
# on exit — never pollute Senza's working tree.
cp "$CARGO_TOML" "$CARGO_TOML.bak"
trap 'mv "$CARGO_TOML.bak" "$CARGO_TOML" 2>/dev/null || true' EXIT
perl -pi -e "s/PLACEHOLDER/$SHA/g" "$CARGO_TOML"

cd "$SENZA_DIR"
# maturin develop installs into the active venv. ensure_venv exported
# PYTHON/PYO3_PYTHON; activating makes maturin pick the right venv
# regardless of how it resolves the interpreter.
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "==> maturin develop --release ..."
maturin develop --release

echo ""
echo "==> 完成。senza 已 editable 安装到 $VENV"
echo "    改 Senza Rust 源码后重跑此脚本即可更新。"
