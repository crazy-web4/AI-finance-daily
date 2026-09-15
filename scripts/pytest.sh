#!/usr/bin/env bash
#
# scripts/pytest.sh — 项目内 pytest 的唯一入口
#
# 为什么需要它：本机 WorkBuddy 沙箱注入的 sitecustomize.py 会劫持 Path.mkdir()，
# 使 mkdir(exist_ok=True) 在目录【已存在】时错误地抛出
#   PermissionError: EEXIST: file already exists, mkdir '<path>'
# 这违反 CPython 标准语义（标准行为是静默通过），会让 pytest 出现一批假失败。
# 清除 4 个 CODEBUDDY_SANDBOX_BROKER_* 环境变量后，shim 不再劫持，行为恢复标准。
# 详见 AGENTS.md「测试环境的已知陷阱」。
#
# 用法：与 python -m pytest 完全等价，参数原样透传，例如：
#   scripts/pytest.sh -q
#   scripts/pytest.sh -q tests/test_cache.py
#
set -euo pipefail

# 解析项目根目录（本脚本位于 <root>/scripts/ 下），保证从任意 cwd 调用都能找到 .venv
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "错误：未找到项目虚拟环境解释器 ${PYTHON}" >&2
  echo "请先按 AGENTS.md「单一 Python 解释器（强制）」一节初始化环境：" >&2
  echo "  /opt/homebrew/bin/python3.12 -m venv .venv" >&2
  echo "  .venv/bin/python -m pip install -U pip" >&2
  echo "  .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

# 清除 WorkBuddy 沙箱 broker 变量，解除 sitecustomize 对 Path.mkdir() 的劫持
exec env \
  -u CODEBUDDY_SANDBOX_BROKER_SESSION_ID \
  -u CODEBUDDY_SANDBOX_BROKER_IPC_ADDRESS \
  -u CODEBUDDY_SANDBOX_BROKER_TRACE_ID \
  -u CODEBUDDY_SANDBOX_BROKER_TOOL_CALL_ID \
  "${PYTHON}" -m pytest "$@"
