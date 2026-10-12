#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金多维评分系统 - 综合RSI、布林带、回测、动量等维度评分"""

import os
import json
import glob
from datetime import datetime


def _score_rsi_percentile_opportunity(percentile):
    """RSI分位 → 机会分 (低分位=高机会)"""
    if percentile <= 10:
        return 100
    if percentile <= 20:
        return 80
    if percentile <= 30:
        return 60
    if percentile <= 40:
        return 40
    if percentile <= 50:
        return 20
    return 0


def _score_rsi_percentile_risk(percentile):
    """RSI分位 → 风险分 (高分位=高风险)"""
    if percentile >= 90:
        return 100
    if percentile >= 80:
        return 80
    if percentile >= 70:
        return 60
    if percentile >= 60:
        return 40
    if percentile >= 50:
        return 20
    return 0


def _score_bollinger_opportunity(signal):
    """布林带信号 → 机会分"""
    if signal == '强烈买入':
        return 100
    if signal == '买入':
        return 80
    if signal == '偏弱':
        return 40
    if signal == '中性':
        return 20
    return 0


def _score_bollinger_risk(signal):
    """布林带信号 → 风险分"""
    if signal == '强烈卖出':
        return 100
    if signal == '卖出':
        return 80
    if signal == '触及上轨':
        return 60
    if signal == '中性':
        return 20
    return 0


def _get_backtest_oversold_winrate(backtest, current_rsi):
    """获取当前RSI水平对应的超卖回测胜率

    逻辑：找到≤当前RSI的最大阈值（即当前RSI已经跌入该超卖区间）
    例如 RSI=42 → 取 RSI≤40 的回测胜率（当前已处于该超卖条件内）
    如果当前RSI低于所有阈值，取最低阈值（最保守估计）
    如果当前RSI高于所有阈值（如RSI>40），说明未进入超卖区间，回测胜率不适用
    """
    if not backtest or 'oversold' not in backtest:
        return None, 0
    oversold = backtest['oversold']

    # 阈值从大到小：40, 35, 30, 25, 22
    # 找到当前RSI已经跌入的最大阈值（threshold >= current_rsi 时不适用，因为还没跌到那个程度）
    # 正确逻辑：找 threshold <= current_rsi 的最大值，表示"当前RSI已经低于该阈值的历史信号"
    # 不对，超卖回测的含义是 RSI <= threshold 时买入
    # 所以如果 RSI=42，它不在 RSI<=40 的区间内，但接近
    # 正确逻辑：找最接近当前RSI且 <= 当前RSI的阈值
    #   如 RSI=42 → 没有阈值<=42（最小是40但40<42不满足<=），所以不算超卖区间
    #   如 RSI=38 → RSI<=40 的回测适用（已处于超卖信号中）
    #   如 RSI=28 → RSI<=30 和 RSI<=35 和 RSI<=40 都适用，取最大的30（最接近当前水平）

    # 但如果当前RSI还没进入任何超卖区间，回测胜率就不太适用
    # 此时返回 None 让调用方给默认分

    best_threshold = None
    for threshold in [40, 35, 30, 25, 22]:
        t = str(threshold) if str(threshold) in oversold else threshold
        if t not in oversold:
            continue
        # 当前RSI已经低于该阈值，说明已处于该超卖信号中
        if current_rsi <= threshold:
            best_threshold = t
            break  # 从大到小遍历，第一个满足的就是最接近的超卖阈值

    if best_threshold is None:
        # 当前RSI未进入任何超卖区间，回测胜率不直接适用
        return None, 0

    data = oversold[best_threshold]
    hold60 = data.get('60', data.get(60))
    if hold60:
        return hold60.get('win_rate', 0), int(best_threshold) if isinstance(best_threshold, str) else best_threshold
    for period in ['30', '90', 30, 90]:
        if period in data:
            return data[period].get('win_rate', 0), int(best_threshold) if isinstance(best_threshold, str) else best_threshold
    return None, 0


def _get_backtest_overbought_droprate(backtest, current_rsi):
    """获取当前RSI水平对应的超买回测回撤率

    逻辑：找到≥当前RSI的最小阈值（即当前RSI已经超过该超买区间）
    例如 RSI=76 → 取 RSI≥75 的回测回撤率（当前已处于该超买条件内）
    如果当前RSI高于所有阈值，取最高阈值
    如果当前RSI低于所有阈值（如RSI<60），说明未进入超买区间，回测回撤率不适用
    """
    if not backtest or 'overbought' not in backtest:
        return None, 0
    overbought = backtest['overbought']

    # 阈值从小到大：60, 65, 70, 75, 80
    # 找最接近当前RSI且 >= 当前RSI的阈值
    #   如 RSI=76 → RSI>=75 适用（已处于超买信号中）
    #   如 RSI=42 → 没有阈值>=42（最小是60），不算超买区间

    best_threshold = None
    for threshold in [60, 65, 70, 75, 80]:
        t = str(threshold) if str(threshold) in overbought else threshold
        if t not in overbought:
            continue
        # 当前RSI已经高于该阈值，说明已处于该超买信号中
        if current_rsi >= threshold:
            best_threshold = t
            # 继续找更大的阈值，取最接近当前RSI的

    # best_threshold 是当前RSI已超过的最大阈值（最接近当前水平的超买信号）

    if best_threshold is None:
        # 当前RSI未进入任何超买区间，回测回撤率不直接适用
        return None, 0

    data = overbought[best_threshold]
    hold10 = data.get('10', data.get(10))
    if hold10:
        return hold10.get('drop_rate', 0), int(best_threshold) if isinstance(best_threshold, str) else best_threshold
    for period in ['5', '20', '30', 5, 20, 30]:
        if period in data:
            return data[period].get('drop_rate', 0), int(best_threshold) if isinstance(best_threshold, str) else best_threshold
    return None, 0


def _score_backtest_winrate(win_rate):
    """回测胜率 → 机会分

    win_rate=None 表示当前RSI未进入超卖区间，回测不直接适用，给低分（不构成买入理由）
    """
    if win_rate is None:
        return 20
    if win_rate >= 70:
        return 100
    if win_rate >= 60:
        return 80
    if win_rate >= 55:
        return 60
    if win_rate >= 50:
        return 40
    return 20


def _score_backtest_droprate(drop_rate):
    """回测回撤率 → 风险分

    drop_rate=None 表示当前RSI未进入超买区间，回测不直接适用，给低分（不构成卖出理由）
    """
    if drop_rate is None:
        return 20
    if drop_rate >= 50:
        return 100
    if drop_rate >= 40:
        return 80
    if drop_rate >= 30:
        return 60
    if drop_rate >= 20:
        return 40
    return 20


def _score_momentum_opportunity(recent_rsi):
    """动量趋势 → 机会分 (RSI连续下降=超卖加速→加分)"""
    if not recent_rsi or len(recent_rsi) < 3:
        return 50
    rsi_values = [r.get('rsi', r.get('RSI', 50)) for r in recent_rsi[-5:]]
    rsi_values = [r for r in rsi_values if r is not None]
    if len(rsi_values) < 3:
        return 50
    # 计算趋势: 从最新数据回看连续下降天数
    declining = 0
    for i in range(len(rsi_values) - 1, 0, -1):
        if rsi_values[i] < rsi_values[i - 1]:
            declining += 1
        else:
            break
    # RSI在下降且处于低位→机会
    avg_rsi = sum(rsi_values) / len(rsi_values)
    if declining >= 3 and avg_rsi < 40:
        return 90
    if declining >= 2 and avg_rsi < 45:
        return 70
    if declining >= 2:
        return 55
    if avg_rsi < 35:
        return 65
    return 40


def _score_momentum_risk(recent_rsi):
    """动量趋势 → 风险分 (RSI连续上升=超买加速→加分)"""
    if not recent_rsi or len(recent_rsi) < 3:
        return 50
    rsi_values = [r.get('rsi', r.get('RSI', 50)) for r in recent_rsi[-5:]]
    rsi_values = [r for r in rsi_values if r is not None]
    if len(rsi_values) < 3:
        return 50
    rising = 0
    for i in range(len(rsi_values) - 1, 0, -1):
        if rsi_values[i] > rsi_values[i - 1]:
            rising += 1
        else:
            break
    avg_rsi = sum(rsi_values) / len(rsi_values)
    if rising >= 3 and avg_rsi > 60:
        return 90
    if rising >= 2 and avg_rsi > 55:
        return 70
    if rising >= 2:
        return 55
    if avg_rsi > 65:
        return 65
    return 40


def _score_extremes_opportunity(current_rsi, stats_min):
    """距历史最低RSI的距离 → 机会分"""
    if stats_min is None or current_rsi is None:
        return 50
    distance = current_rsi - stats_min
    if distance <= 5:
        return 100
    if distance <= 10:
        return 80
    if distance <= 15:
        return 60
    if distance <= 20:
        return 40
    return 20


def _score_overbought_duration(recent_rsi):
    """超买时长占比 → 风险分"""
    if not recent_rsi:
        return 30
    rsi_values = [r.get('rsi', r.get('RSI', 50)) for r in recent_rsi]
    rsi_values = [r for r in rsi_values if r is not None]
    if not rsi_values:
        return 30
    overbought_count = sum(1 for r in rsi_values if r >= 70)
    ratio = overbought_count / len(rsi_values)
    if ratio >= 0.7:
        return 100
    if ratio >= 0.5:
        return 80
    if ratio >= 0.3:
        return 60
    if ratio >= 0.1:
        return 40
    return 10


def _score_multi_tf_opportunity(multi_tf):
    """多时间框架RSI一致性 → 机会分"""
    if not multi_tf:
        return 50
    consensus = multi_tf.get('consensus', '')
    if '超卖共振' in consensus:
        return 100
    if '偏弱' in consensus:
        return 70
    if '不一致' in consensus:
        return 40
    return 30


def _score_multi_tf_risk(multi_tf):
    """多时间框架RSI一致性 → 风险分"""
    if not multi_tf:
        return 50
    consensus = multi_tf.get('consensus', '')
    if '超买共振' in consensus:
        return 100
    if '偏强' in consensus:
        return 70
    if '不一致' in consensus:
        return 40
    return 30


def _score_trend_strength_opportunity(trend):
    """趋势强度 → 机会分 (下跌趋势中寻找反转机会)"""
    if not trend:
        return 50
    direction = trend.get('direction', '横盘')
    strength = trend.get('strength', '无')
    deviation = abs(trend.get('deviation_pct', 0))
    if direction == '下跌' and strength in ('强', '极端') and deviation > 10:
        return 90  # 极端下跌 → 反弹机会大
    if direction == '下跌' and strength == '中等':
        return 70
    if direction == '横盘':
        return 50
    return 30


def _score_trend_strength_risk(trend):
    """趋势强度 → 风险分 (上涨趋势中追高风险)"""
    if not trend:
        return 50
    direction = trend.get('direction', '横盘')
    strength = trend.get('strength', '无')
    deviation = abs(trend.get('deviation_pct', 0))
    if direction == '上涨' and strength in ('强', '极端') and deviation > 10:
        return 90  # 极端上涨 → 追高风险大
    if direction == '上涨' and strength == '中等':
        return 70
    if direction == '横盘':
        return 50
    return 30


def score_fund(data):
    """对单只基金进行多维评分

    Args:
        data: 从JSON加载的基金分析数据

    Returns:
        dict: 评分结果
    """
    latest = data.get('latest', {})
    stats = data.get('stats', {})
    bollinger = data.get('bollinger', {})
    backtest = data.get('backtest', {})
    recent_rsi = data.get('recent_rsi', [])

    percentile = latest.get('percentile', 50)
    current_rsi = latest.get('rsi', 50)
    bollinger_signal = bollinger.get('signal', '中性')
    stats_min = stats.get('min')

    # ===== 机会分 =====
    s_rsi_opp = _score_rsi_percentile_opportunity(percentile)
    s_boll_opp = _score_bollinger_opportunity(bollinger_signal)
    win_rate, bt_threshold = _get_backtest_oversold_winrate(backtest, current_rsi)
    s_bt_opp = _score_backtest_winrate(win_rate)
    s_mom_opp = _score_momentum_opportunity(recent_rsi)
    s_ext_opp = _score_extremes_opportunity(current_rsi, stats_min)
    multi_tf = data.get('multi_tf_rsi', {})
    s_mtf_opp = _score_multi_tf_opportunity(multi_tf)
    trend = data.get('trend_strength', {})
    s_trend_opp = _score_trend_strength_opportunity(trend)

    opportunity_score = round(
        s_rsi_opp * 0.25 +
        s_boll_opp * 0.15 +
        s_bt_opp * 0.20 +
        s_mom_opp * 0.10 +
        s_ext_opp * 0.10 +
        s_mtf_opp * 0.10 +
        s_trend_opp * 0.10,
        1
    )

    # ===== 风险分 =====
    s_rsi_risk = _score_rsi_percentile_risk(percentile)
    s_boll_risk = _score_bollinger_risk(bollinger_signal)
    drop_rate, bt_risk_threshold = _get_backtest_overbought_droprate(backtest, current_rsi)
    s_bt_risk = _score_backtest_droprate(drop_rate)
    s_mom_risk = _score_momentum_risk(recent_rsi)
    s_ob_duration = _score_overbought_duration(recent_rsi)
    s_mtf_risk = _score_multi_tf_risk(multi_tf)
    s_trend_risk = _score_trend_strength_risk(trend)

    risk_score = round(
        s_rsi_risk * 0.25 +
        s_boll_risk * 0.15 +
        s_bt_risk * 0.20 +
        s_mom_risk * 0.10 +
        s_ob_duration * 0.10 +
        s_mtf_risk * 0.10 +
        s_trend_risk * 0.10,
        1
    )

    # ===== 操作建议 =====
    if opportunity_score >= 70 and risk_score <= 30:
        action = 'strong_buy'
        action_label = '⭐ 强力买入'
    elif opportunity_score >= 55 and risk_score <= 40:
        action = 'buy'
        action_label = '🟢 买入'
    elif opportunity_score >= 40 and risk_score <= 50:
        action = 'watch'
        action_label = '👀 关注'
    elif risk_score >= 70 and opportunity_score <= 35:
        action = 'strong_sell'
        action_label = '🔴 强力减仓'
    elif risk_score >= 55 and opportunity_score <= 50:
        action = 'reduce'
        action_label = '🟡 减仓'
    else:
        action = 'hold'
        action_label = '⏸ 持有'

    return {
        'opportunity_score': opportunity_score,
        'risk_score': risk_score,
        'action': action,
        'action_label': action_label,
        'details': {
            'opportunity': {
                'rsi_percentile': {'score': s_rsi_opp, 'weight': 0.25, 'value': percentile},
                'bollinger': {'score': s_boll_opp, 'weight': 0.15, 'value': bollinger_signal},
                'backtest_winrate': {'score': s_bt_opp, 'weight': 0.20, 'value': win_rate, 'threshold': bt_threshold},
                'momentum': {'score': s_mom_opp, 'weight': 0.10},
                'extremes': {'score': s_ext_opp, 'weight': 0.10, 'value': stats_min},
                'multi_tf_rsi': {'score': s_mtf_opp, 'weight': 0.10, 'value': multi_tf.get('consensus', '') if multi_tf else ''},
                'trend_strength': {'score': s_trend_opp, 'weight': 0.10, 'value': trend.get('direction', '') + trend.get('strength', '') if trend else ''},
            },
            'risk': {
                'rsi_percentile': {'score': s_rsi_risk, 'weight': 0.25, 'value': percentile},
                'bollinger': {'score': s_boll_risk, 'weight': 0.15, 'value': bollinger_signal},
                'backtest_droprate': {'score': s_bt_risk, 'weight': 0.20, 'value': drop_rate, 'threshold': bt_risk_threshold},
                'momentum': {'score': s_mom_risk, 'weight': 0.10},
                'overbought_duration': {'score': s_ob_duration, 'weight': 0.10},
                'multi_tf_rsi': {'score': s_mtf_risk, 'weight': 0.10, 'value': multi_tf.get('consensus', '') if multi_tf else ''},
                'trend_strength': {'score': s_trend_risk, 'weight': 0.10, 'value': trend.get('direction', '') + trend.get('strength', '') if trend else ''},
            }
        }
    }


def score_all_funds(result_dir):
    """对 result/ 目录下所有基金进行评分

    Returns:
        list: 评分结果列表，按操作建议分组排序
    """
    result_dir = os.path.abspath(result_dir)
    json_files = glob.glob(os.path.join(result_dir, '*_rsi.json'))
    # 排除 scenario 文件
    json_files = [f for f in json_files if '_scenario_' not in f]

    if not json_files:
        print("未找到分析数据文件")
        return []

    results = []
    for jf in json_files:
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            scoring = score_fund(data)
            results.append({
                'symbol': data.get('symbol', ''),
                'asset_name': data.get('asset_name', ''),
                'data_type': data.get('data_type', ''),
                'data_type_label': data.get('data_type_label', ''),
                'latest': data.get('latest', {}),
                'bollinger': data.get('bollinger', {}),
                'scoring': scoring,
            })
        except Exception as e:
            print(f"  评分失败 {os.path.basename(jf)}: {e}")

    return results


def get_action_order(action):
    """操作建议排序权重"""
    order = {'strong_buy': 0, 'buy': 1, 'watch': 2, 'hold': 3, 'reduce': 4, 'strong_sell': 5}
    return order.get(action, 3)


def format_console_output(results):
    """格式化控制台输出"""
    # 按操作建议分组
    action_groups = {}
    for r in results:
        action = r['scoring']['action']
        if action not in action_groups:
            action_groups[action] = []
        action_groups[action].append(r)

    # 组内排序: 买入组按机会分降序，卖出组按风险分降序
    for action, group in action_groups.items():
        if action in ('strong_buy', 'buy', 'watch'):
            group.sort(key=lambda x: x['scoring']['opportunity_score'], reverse=True)
        else:
            group.sort(key=lambda x: x['scoring']['risk_score'], reverse=True)

    # 按操作建议排序
    sorted_actions = sorted(action_groups.keys(), key=get_action_order)

    lines = []
    lines.append("=" * 90)
    lines.append(f"  基金多维评分报告  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 90)

    for action in sorted_actions:
        group = action_groups[action]
        label = group[0]['scoring']['action_label']
        lines.append(f"\n{'─' * 90}")
        lines.append(f"  {label}  ({len(group)}只)")
        lines.append(f"{'─' * 90}")
        lines.append(f"  {'代码':<8} {'名称':<16} {'机会分':>6} {'风险分':>6} {'RSI':>6} {'分位':>6} {'布林信号':<10}")
        lines.append(f"  {'─' * 72}")
        for r in group:
            s = r['scoring']
            l = r['latest']
            b = r.get('bollinger', {})
            lines.append(
                f"  {r['symbol']:<8} "
                f"{(r['asset_name'] or '')[:14]:<16} "
                f"{s['opportunity_score']:>6.1f} "
                f"{s['risk_score']:>6.1f} "
                f"{l.get('rsi', '-'):>6} "
                f"{l.get('percentile', '-'):>5}% "
                f"{b.get('signal', '-'):<10}"
            )

    lines.append(f"\n{'=' * 90}")
    lines.append(f"  总计: {len(results)} 只基金")
    lines.append("")

    return '\n'.join(lines)


def generate_markdown_report(results, output_path):
    """生成 Markdown 评分报告"""
    action_groups = {}
    for r in results:
        action = r['scoring']['action']
        if action not in action_groups:
            action_groups[action] = []
        action_groups[action].append(r)

    for action, group in action_groups.items():
        if action in ('strong_buy', 'buy', 'watch'):
            group.sort(key=lambda x: x['scoring']['opportunity_score'], reverse=True)
        else:
            group.sort(key=lambda x: x['scoring']['risk_score'], reverse=True)

    sorted_actions = sorted(action_groups.keys(), key=get_action_order)

    lines = []
    lines.append(f"# 基金多维评分报告")
    lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 共 {len(results)} 只基金")
    lines.append("")

    # 概览统计
    lines.append("## 概览")
    lines.append("")
    summary = {}
    for action in sorted_actions:
        label = action_groups[action][0]['scoring']['action_label']
        summary[label] = len(action_groups[action])
    lines.append("| 建议 | 数量 |")
    lines.append("|------|------|")
    for action in sorted_actions:
        label = action_groups[action][0]['scoring']['action_label']
        lines.append(f"| {label} | {len(action_groups[action])} |")
    lines.append("")

    # 评分说明
    lines.append("## 评分维度")
    lines.append("")
    lines.append("### 机会分 (0-100, 越高越好)")
    lines.append("| 维度 | 权重 | 说明 |")
    lines.append("|------|------|------|")
    lines.append("| RSI分位 | 30% | 分位越低机会越大 |")
    lines.append("| 布林带信号 | 20% | 买入信号越强分越高 |")
    lines.append("| 回测胜率 | 25% | 历史超卖后60天胜率 |")
    lines.append("| 动量趋势 | 15% | RSI连续下降=超卖加速 |")
    lines.append("| 历史极值 | 10% | 距历史最低RSI越近分越高 |")
    lines.append("")
    lines.append("### 风险分 (0-100, 越高越危险)")
    lines.append("| 维度 | 权重 | 说明 |")
    lines.append("|------|------|------|")
    lines.append("| RSI分位 | 30% | 分位越高风险越大 |")
    lines.append("| 布林带信号 | 20% | 卖出信号越强分越高 |")
    lines.append("| 回测回撤率 | 25% | 历史超买后10天回撤率 |")
    lines.append("| 动量趋势 | 15% | RSI连续上升=超买加速 |")
    lines.append("| 超买时长 | 10% | 近期RSI≥70的天数占比 |")
    lines.append("")

    # 分组详情
    for action in sorted_actions:
        group = action_groups[action]
        label = group[0]['scoring']['action_label']
        lines.append(f"## {label} ({len(group)}只)")
        lines.append("")
        lines.append("| 代码 | 名称 | 机会分 | 风险分 | RSI | 分位 | 布林信号 | 净值 | 日涨跌 |")
        lines.append("|------|------|--------|--------|-----|------|----------|------|--------|")
        for r in group:
            s = r['scoring']
            l = r['latest']
            b = r.get('bollinger', {})
            nav = l.get('display_nav', l.get('price', '-'))
            change = l.get('display_daily_change', l.get('daily_change', '-'))
            if change != '-':
                change_str = f"{change:+.2f}%" if isinstance(change, (int, float)) else str(change)
            else:
                change_str = '-'
            lines.append(
                f"| {r['symbol']} | {r['asset_name'] or '-'} | "
                f"{s['opportunity_score']:.1f} | {s['risk_score']:.1f} | "
                f"{l.get('rsi', '-')} | {l.get('percentile', '-')}% | "
                f"{b.get('signal', '-')} | {nav} | {change_str} |"
            )
        lines.append("")

    report = '\n'.join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    return output_path


def update_fund_json_with_scoring(result_dir, results):
    """将评分信息写回各基金的 JSON 文件"""
    for r in results:
        symbol = r['symbol']
        # 查找对应的JSON文件
        patterns = [
            os.path.join(result_dir, f'asset_{symbol}_rsi.json'),
            os.path.join(result_dir, f'fund_{symbol}_rsi.json'),
            os.path.join(result_dir, f'hk_fund_{symbol}_rsi.json'),
            os.path.join(result_dir, f'cn_stock_{symbol}_rsi.json'),
            os.path.join(result_dir, f'cn_fund_{symbol}_rsi.json'),
            os.path.join(result_dir, f'us_stock_{symbol}_rsi.json'),
        ]
        json_path = None
        for p in patterns:
            if os.path.exists(p):
                json_path = p
                break
        if not json_path:
            continue

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            data['scoring'] = {
                'opportunity_score': r['scoring']['opportunity_score'],
                'risk_score': r['scoring']['risk_score'],
                'action': r['scoring']['action'],
                'action_label': r['scoring']['action_label'],
                'details': r['scoring']['details'],
            }

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  更新评分失败 {symbol}: {e}")