#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"

# 单一入口保证 RSI 与技术指标复用同一批数据快照；此流程不调用 LLM。
"$PYTHON" update_all.py --force --no-open "$@"

# VIX 是独立展示模块，失败不影响主批次结果。
"$PYTHON" lib/vix_distribution.py || echo "⚠️ VIX 分布刷新失败，主分析已完成" >&2
