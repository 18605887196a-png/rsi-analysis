#!/bin/bash
set -euo pipefail

# 每日定时更新 RSI 分析数据
# 红利/固收/QDII 走 --symbols(批次 43 只,红利 18 含金信智能混合A 002849);
# 私募/大宗/A股 走 --categories 动态纳入(private/commodity/cn_stock tab),
#   新增标的加到 index.html 对应 tab 的 CODES 集合或 watchlist 声明 cn_stock 即自动更新,无需改本脚本。

cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"

# === 三类基金代码 ===
DIVIDEND_SYMS="004815 005125 007751 159209 159220 159355 161907 510720 512890 515100 515300 515450 520990 560570 561580 563700 968048 002849"
BOND_SYMS="000047 000973 001122 001235 003547 003591 004279 015736 110018 400030 510080 519753 006213 016872"
QDII_SYMS="007280 000043 000179 001668 003629 007729 019231 162415 163813 519696 519981 378546 096001"  # 378546=摩根全球天然资源混合(QDII),2026-09-14 从大宗tab迁入QDII;096001=大成标普500等权重指数(QDII)A人民币,2026-09-19 新增

ALL_SYMS="$DIVIDEND_SYMS $BOND_SYMS $QDII_SYMS"

echo "======================================================"
echo "每日更新: 红利 + 固收 + QDII  ($(echo $ALL_SYMS | wc -w | tr -d ' ') 只基金)"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================"

# 红利/固收/QDII 用 --symbols(批次 44 只);私募/大宗/A股/宽基指数/质量因子 用 --categories 动态纳入
# (private/commodity/cn_stock/broad/quality)
# 新增标的加到 index.html 对应 tab 的 CODES 集合或 watchlist 声明即自动进 --categories,无需改本脚本
"$PYTHON" update_all.py --force --no-open --symbols $ALL_SYMS --categories commodity private cn_stock broad quality

# === 全量多维评分 + 重建 embedded_data.js (首页"今日机会"条依赖 scoring) ===
# update_all 只刷新三类数据;评分扫描 result/ 下全量 *_rsi.json,算出 action/opportunity_score
# 并 update_manifest 重建 embedded_data.js,使首页"今日机会"条在出现买入信号时自动亮起。
# run_scoring 末尾会尝试 open 网页(无头环境快速失败,不影响退出码);用 `|| echo` 容错,
# 失败不中断后续 VIX/红利估值/副本同步。
"$PYTHON" main.py --score || echo "⚠️ 评分步骤失败,首页今日机会条可能缺 scoring" >&2

# VIX 是独立展示模块，失败不影响主批次结果
"$PYTHON" lib/vix_distribution.py || echo "⚠️ VIX 分布刷新失败，主分析已完成" >&2

# 核心关注"超卖距离表"(距 RSI 35/30/25/22 还需跌多少+触达价, OVERSOLD_DISTANCE 注入 index.html)
# 独立展示模块，失败不影响主批次结果
"$PYTHON" lib/oversold_distance.py || echo "⚠️ 超卖距离刷新失败，主分析已完成" >&2

# === 重新生成 红利估值结论.html (dividend-valuation 技能,独立于人机) ===
# 网页入口 /dividend-valuation/result/红利估值结论.html 依赖此报告;它靠理杏仁数据重建,
# 收盘日取当天最新(如 8-12)。失败(如 token 过期)不影响主表,保留旧版。
DIV_DIR="/home/admin/.codefuse/engine/cc/skills/dividend-valuation"
echo "--- 重新生成红利估值结论报告 (dividend-valuation) ---"
if [ -d "$DIV_DIR" ]; then
  if ( cd "$DIV_DIR" && "$PYTHON" main.py --hongli ); then
    echo "  OK -> $DIV_DIR/result/红利估值结论.html"
  else
    echo "  ⚠️ 红利估值报告重生成失败(可能理杏仁 token 过期),已保留旧版" >&2
  fi
else
  echo "  ⚠️ 跳过(未找到 dividend-valuation 技能): $DIV_DIR" >&2
fi

# === 同步结果到其它 skill 副本，消除多副本漂移 ===
# 本目录(engine/cc)是每日定时任务的权威输出;其余副本(fuse/engine-codex/.codex)
# 的 rsi-analysis/result 若不同步会成为旧数据,导致打开网址仍见旧日期。
echo "--- 同步 result/ 到其余 rsi-analysis 副本 ---"
SYNC_TARGETS=(
  "/home/admin/.codefuse/engine/codex/skills/rsi-analysis"
  "/home/admin/.codefuse/fuse/skills/rsi-analysis"
  "/home/admin/.codex/skills/rsi-analysis"
)
for t in "${SYNC_TARGETS[@]}"; do
  if [ -d "$t/result" ]; then
    if rsync -a --delete result/ "$t/result/" 2>/dev/null; then
      echo "  OK -> $t/result/"
    else
      echo "  ⚠️ 同步失败: $t" >&2
    fi
  else
    echo "  ⚠️ 跳过(无 result 目录): $t" >&2
  fi
done

echo "======================================================"
echo "更新完成: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================"
