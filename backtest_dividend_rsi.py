#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
红利波段 RSI 策略回测脚本（Pine Script 风格）
模拟方案中的四档加仓 + 三档卖出逻辑

策略规则：
- 以 008164 南方标普红利低波50 RSI(14) 为信号
- RSI <35 启动加仓 6万, <32 加9万, <30 加15万, <25 加9万
- RSI >65 卖<35仓位, >70 卖<32仓位, >75 卖<30+<25仓位
- 底仓 18万始终保留
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

import pandas as pd
import numpy as np
from data_fetcher import fetch_cn_fund_history, calculate_rsi

# ============================================================
# 配置
# ============================================================

SIGNAL_FUND = '008164'  # 信号基金
TOTAL_CAPITAL = 600_000
BASE_POSITION = 180_000  # 底仓 30%

# 加仓档位 (RSI阈值, 加仓金额)
BUY_TIERS = [
    (35, 60_000),
    (32, 90_000),
    (30, 150_000),
    (25, 90_000),
]

# 卖出档位 (RSI阈值, 对应卖出的买入档位索引)
SELL_TIERS = [
    (65, 0),   # >65 卖 <35 买的
    (70, 1),   # >70 卖 <32 买的
    (75, 2),   # >75 卖 <30 买的
    # <25 的也在 >75 时一起卖
]

# ============================================================
# 回测引擎
# ============================================================

def run_backtest(df):
    """
    Pine Script 风格回测
    返回: trades 列表, 每日持仓序列, 统计摘要
    """
    closes = df['adj_nav'].values
    dates = df['date'].values
    rsi = calculate_rsi(closes, period=14)

    # 状态变量
    position = BASE_POSITION  # 当前总持仓
    cash = TOTAL_CAPITAL - BASE_POSITION  # 可用现金
    tier_filled = [False, False, False, False]  # 各档是否已加仓
    tier_cost = [0, 0, 0, 0]  # 各档成本

    trades = []
    daily_positions = []
    signal_log = []

    for i in range(len(closes)):
        rsi_val = rsi[i]
        date_str = str(dates[i])[:10]
        price = closes[i]

        if rsi_val is None:
            daily_positions.append({
                'date': date_str, 'price': price, 'rsi': None,
                'position': position, 'cash': cash, 'total': position + cash
            })
            continue

        # ---- 卖出逻辑 ----
        for sell_rsi, tier_idx in SELL_TIERS:
            if rsi_val > sell_rsi and tier_filled[tier_idx]:
                sell_amount = tier_cost[tier_idx]
                position -= sell_amount
                cash += sell_amount
                trades.append({
                    'date': date_str, 'action': 'SELL', 'tier': tier_idx,
                    'rsi': rsi_val, 'price': price,
                    'amount': sell_amount, 'position': position, 'cash': cash
                })
                tier_filled[tier_idx] = False
                tier_cost[tier_idx] = 0

        # RSI >75 同时卖 tier 2 和 tier 3
        if rsi_val > 75:
            for tier_idx in [2, 3]:
                if tier_filled[tier_idx]:
                    sell_amount = tier_cost[tier_idx]
                    position -= sell_amount
                    cash += sell_amount
                    trades.append({
                        'date': date_str, 'action': 'SELL', 'tier': tier_idx,
                        'rsi': rsi_val, 'price': price,
                        'amount': sell_amount, 'position': position, 'cash': cash
                    })
                    tier_filled[tier_idx] = False
                    tier_cost[tier_idx] = 0

        # ---- 买入逻辑 ----
        for tier_idx, (threshold, amount) in enumerate(BUY_TIERS):
            if rsi_val < threshold and not tier_filled[tier_idx] and cash >= amount:
                position += amount
                cash -= amount
                tier_filled[tier_idx] = True
                tier_cost[tier_idx] = amount
                trades.append({
                    'date': date_str, 'action': 'BUY', 'tier': tier_idx,
                    'rsi': rsi_val, 'price': price,
                    'amount': amount, 'position': position, 'cash': cash
                })

        # 记录 RSI 信号区间
        if rsi_val < 25:
            signal = '满仓区'
        elif rsi_val < 30:
            signal = '重仓区'
        elif rsi_val < 32:
            signal = '加仓区'
        elif rsi_val < 35:
            signal = '启动区'
        elif rsi_val <= 65:
            signal = '不动区'
        elif rsi_val <= 70:
            signal = '卖出1区'
        elif rsi_val <= 75:
            signal = '卖出2区'
        else:
            signal = '卖出3区'

        signal_log.append({
            'date': date_str, 'rsi': round(rsi_val, 2), 'signal': signal,
            'price': round(price, 4)
        })

        daily_positions.append({
            'date': date_str, 'price': round(price, 4), 'rsi': round(rsi_val, 2),
            'position': round(position, 2), 'cash': round(cash, 2),
            'total': round(position + cash, 2)
        })

    return trades, daily_positions, signal_log


# ============================================================
# 统计
# ============================================================

def compute_stats(trades, daily_positions, df):
    """计算回测统计"""
    if not trades:
        return {'error': '没有产生任何交易'}

    buys = [t for t in trades if t['action'] == 'BUY']
    sells = [t for t in trades if t['action'] == 'SELL']

    # 按档位统计
    tier_stats = {}
    for tier_idx in range(4):
        tier_buys = [t for t in buys if t['tier'] == tier_idx]
        tier_sells = [t for t in sells if t['tier'] == tier_idx]
        tier_stats[f'tier_{tier_idx}'] = {
            'threshold': BUY_TIERS[tier_idx][0],
            'amount': BUY_TIERS[tier_idx][1],
            'buy_count': len(tier_buys),
            'sell_count': len(tier_sells),
            'buy_dates': [t['date'] for t in tier_buys],
            'sell_dates': [t['date'] for t in tier_sells],
        }

    # 信号区间分布
    dp = pd.DataFrame(daily_positions)
    dp_valid = dp[dp['rsi'].notna()].copy()
    signal_dist = {
        '满仓区 (<25)': int((dp_valid['rsi'] < 25).sum()),
        '重仓区 (25-30)': int(((dp_valid['rsi'] >= 25) & (dp_valid['rsi'] < 30)).sum()),
        '加仓区 (30-32)': int(((dp_valid['rsi'] >= 30) & (dp_valid['rsi'] < 32)).sum()),
        '启动区 (32-35)': int(((dp_valid['rsi'] >= 32) & (dp_valid['rsi'] < 35)).sum()),
        '不动区 (35-65)': int(((dp_valid['rsi'] >= 35) & (dp_valid['rsi'] <= 65)).sum()),
        '卖出区 (>65)': int((dp_valid['rsi'] > 65).sum()),
    }
    total_days = len(dp_valid)
    signal_pct = {k: f'{v}/{total_days} ({v/total_days*100:.1f}%)' for k, v in signal_dist.items()}

    # 最终状态
    final = daily_positions[-1]
    start = daily_positions[0]

    return {
        'data_period': f"{daily_positions[0]['date']} ~ {daily_positions[-1]['date']}",
        'total_trading_days': total_days,
        'total_trades': len(trades),
        'total_buys': len(buys),
        'total_sells': len(sells),
        'final_position': final['position'],
        'final_cash': final['cash'],
        'final_total': final['total'],
        'signal_distribution': signal_pct,
        'tier_stats': tier_stats,
        'trades': trades[-20:] if len(trades) > 20 else trades,  # 最近20笔
    }


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("  红利波段 RSI 策略回测（Pine Script 风格）")
    print("=" * 60)
    print()

    # 获取数据
    print(f"[1/3] 获取 {SIGNAL_FUND} 历史净值数据...")
    result = fetch_cn_fund_history(SIGNAL_FUND)
    if result is None:
        print("ERROR: 无法获取基金数据")
        return
    df, name = result
    print(f"  基金名称: {name}")
    print(f"  数据范围: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    print(f"  数据条数: {len(df)}")
    print()

    # 运行回测
    print("[2/3] 运行回测...")
    trades, daily_positions, signal_log = run_backtest(df)
    print(f"  产生交易: {len(trades)} 笔")
    print()

    # 统计
    print("[3/3] 生成统计...")
    stats = compute_stats(trades, daily_positions, df)
    print()

    # ========================================
    # 输出报告
    # ========================================
    print("=" * 60)
    print("  回测报告")
    print("=" * 60)
    print()
    print(f"数据周期: {stats['data_period']}")
    print(f"交易天数: {stats['total_trading_days']}")
    print(f"总交易数: {stats['total_trades']} (买入 {stats['total_buys']} / 卖出 {stats['total_sells']})")
    print()

    print("--- 信号区间分布 ---")
    for k, v in stats['signal_distribution'].items():
        print(f"  {k}: {v}")
    print()

    print("--- 各档位交易统计 ---")
    for tier_name, tier_data in stats['tier_stats'].items():
        t = tier_data
        print(f"  {tier_name} (RSI<{t['threshold']}, 金额{t['amount']:,}):")
        print(f"    买入 {t['buy_count']} 次, 卖出 {t['sell_count']} 次")
        if t['buy_dates']:
            print(f"    买入日期: {', '.join(t['buy_dates'][:5])}{'...' if len(t['buy_dates'])>5 else ''}")
        if t['sell_dates']:
            print(f"    卖出日期: {', '.join(t['sell_dates'][:5])}{'...' if len(t['sell_dates'])>5 else ''}")
    print()

    print("--- 最终状态 ---")
    print(f"  持仓: {stats['final_position']:,.0f}")
    print(f"  现金: {stats['final_cash']:,.0f}")
    print(f"  总资产: {stats['final_total']:,.0f}")
    print()

    # 最近交易
    if stats['trades']:
        print("--- 最近交易 ---")
        for t in stats['trades']:
            emoji = '🟢' if t['action'] == 'BUY' else '🔴'
            print(f"  {t['date']} {emoji} {t['action']} Tier{t['tier']} RSI={t['rsi']:.1f} 金额={t['amount']:,} 持仓={t['position']:,.0f}")
    print()

    # 保存结果
    output_dir = os.path.join(os.path.dirname(__file__), 'result')
    os.makedirs(output_dir, exist_ok=True)

    # 保存完整回测数据
    result = {
        'config': {
            'signal_fund': SIGNAL_FUND,
            'total_capital': TOTAL_CAPITAL,
            'base_position': BASE_POSITION,
            'buy_tiers': BUY_TIERS,
            'sell_tiers': SELL_TIERS,
        },
        'stats': {k: v for k, v in stats.items() if k != 'trades'},
        'trades': trades,
        'daily_positions': daily_positions[-100:],  # 最近100天
        'signal_log': signal_log[-100:],
    }

    result_path = os.path.join(output_dir, 'backtest_dividend_rsi.json')
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"结果已保存: {result_path}")


if __name__ == '__main__':
    main()