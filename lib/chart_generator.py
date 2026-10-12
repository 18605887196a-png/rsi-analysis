#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSI 图表生成器 - 价格走势 + RSI走势 + 分布直方图"""

import os
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

# 中文字体
plt.rcParams['font.sans-serif'] = [
    'Noto Sans CJK TC', 'Noto Sans CJK SC', 'Noto Sans CJK HK',
    'Microsoft JhengHei', 'Microsoft YaHei', 'SimHei',
    'PingFang HK', 'STHeiti', 'Arial Unicode MS', 'Heiti TC', 'DejaVu Sans',
]
plt.rcParams['axes.unicode_minus'] = False


def generate_chart(df, price_col, data_type, symbol, result, output_path):
    """
    生成 RSI 分析图表（3个子图）

    Parameters:
        df: 原始 DataFrame（含 date, price_col, RSI_7, RSI_14）
        price_col: 价格列名
        data_type: 'us_stock' / 'cn_fund' / 'hk_fund'
        symbol: 代码
        result: analyzer 输出的 result dict
        output_path: 输出图片路径
    """
    rsi_col = 'RSI_14'
    df_plot = df[['date', price_col, rsi_col, 'RSI_7']].dropna(subset=[rsi_col]).copy()
    # 确保数值列为 float 类型，避免 fill_between 报 isfinite 错误
    for col in [price_col, rsi_col, 'RSI_7']:
        df_plot[col] = pd.to_numeric(df_plot[col], errors='coerce')
    df_plot = df_plot.dropna(subset=[price_col, rsi_col])

    type_labels = {'us_stock': symbol, 'cn_fund': f'基金{symbol}', 'hk_fund': result.get('asset_name', symbol), 'private_fund': result.get('asset_name', symbol)}
    title_prefix = type_labels.get(data_type, symbol)

    fig = plt.figure(figsize=(14, 14))
    gs = GridSpec(3, 1, height_ratios=[2, 1, 1], hspace=0.3)

    # ===== 子图1: 价格走势 + 超买超卖标记 =====
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(df_plot['date'], df_plot[price_col], color='#2563EB', linewidth=1)
    ax1.fill_between(df_plot['date'], df_plot[price_col], alpha=0.15, color='#3B82F6')
    ax1.set_ylabel('Price', fontsize=12)
    ax1.set_title(f'{title_prefix} - Price & RSI Analysis', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)

    # 标记超买超卖点
    oversold = df_plot[df_plot[rsi_col] <= 30]
    overbought = df_plot[df_plot[rsi_col] >= 70]
    ax1.scatter(oversold['date'], oversold[price_col], c='#16A34A', s=50,
                marker='^', label='Oversold (RSI<=30)', zorder=5, edgecolors='white', linewidths=0.5)
    ax1.scatter(overbought['date'], overbought[price_col], c='#DC2626', s=50,
                marker='v', label='Overbought (RSI>=70)', zorder=5, edgecolors='white', linewidths=0.5)
    ax1.legend(loc='upper left', fontsize=9)

    # 最新价格标注
    latest_row = df_plot.iloc[-1]
    ax1.annotate(f"{_fmt_price(latest_row[price_col], data_type)}",
                 xy=(latest_row['date'], latest_row[price_col]),
                 xytext=(10, 10), textcoords='offset points',
                 fontsize=10, fontweight='bold', color='#2563EB',
                 arrowprops=dict(arrowstyle='->', color='#2563EB', lw=1.5))

    # ===== 子图2: RSI 走势 =====
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.plot(df_plot['date'], df_plot[rsi_col], color='#7C3AED', linewidth=1.5, label='RSI(14)')

    # 超买超卖区间填充
    ax2.axhline(y=70, color='#DC2626', linestyle='--', alpha=0.5, linewidth=1)
    ax2.axhline(y=30, color='#16A34A', linestyle='--', alpha=0.5, linewidth=1)
    ax2.axhline(y=50, color='#9CA3AF', linestyle=':', alpha=0.4, linewidth=0.8)
    ax2.fill_between(df_plot['date'], 70, df_plot[rsi_col],
                     where=(df_plot[rsi_col] >= 70), color='#FCA5A5', alpha=0.4)
    ax2.fill_between(df_plot['date'], 30, df_plot[rsi_col],
                     where=(df_plot[rsi_col] <= 30), color='#86EFAC', alpha=0.4)
    ax2.set_ylabel('RSI', fontsize=12)
    ax2.set_ylim(0, 100)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.grid(True, alpha=0.3)

    # 当前 RSI 标注
    cur_rsi = latest_row[rsi_col]
    rsi_color = '#DC2626' if cur_rsi >= 70 else '#16A34A' if cur_rsi <= 30 else '#7C3AED'
    ax2.annotate(f"RSI: {cur_rsi:.1f}",
                 xy=(latest_row['date'], cur_rsi),
                 xytext=(10, -15), textcoords='offset points',
                 fontsize=10, fontweight='bold', color=rsi_color,
                 arrowprops=dict(arrowstyle='->', color=rsi_color, lw=1.5))

    # ===== 子图3: RSI 分布直方图 =====
    ax3 = fig.add_subplot(gs[2])
    rsi_values = df_plot[rsi_col]

    bins = list(range(0, 105, 5))
    n, bins_out, patches = ax3.hist(rsi_values, bins=bins, edgecolor='white', alpha=0.85, linewidth=0.5)

    # 着色
    for i, patch in enumerate(patches):
        if bins_out[i] < 30:
            patch.set_facecolor('#22C55E')
        elif bins_out[i] >= 70:
            patch.set_facecolor('#EF4444')
        else:
            patch.set_facecolor('#3B82F6')

    # 关键线
    ax3.axvline(x=30, color='#16A34A', linestyle='--', linewidth=2, label='Oversold (30)')
    ax3.axvline(x=70, color='#DC2626', linestyle='--', linewidth=2, label='Overbought (70)')
    mean_val = rsi_values.mean()
    ax3.axvline(x=mean_val, color='#F59E0B', linestyle='-', linewidth=2,
                label=f'Mean ({mean_val:.1f})')
    # 当前 RSI 线
    ax3.axvline(x=cur_rsi, color='#7C3AED', linestyle='-', linewidth=2.5,
                label=f'Current ({cur_rsi:.1f})')

    ax3.set_xlabel('RSI Value', fontsize=12)
    ax3.set_ylabel('Count', fontsize=12)
    ax3.set_title(f'RSI(14) Distribution Histogram', fontsize=12, fontweight='bold')
    ax3.legend(loc='upper left', fontsize=8)
    ax3.grid(True, alpha=0.3, axis='y')
    ax3.set_xticks(range(0, 105, 10))
    ax3.set_xlim(0, 100)

    # 柱子上标注数字
    for i in range(len(n)):
        if n[i] > 0:
            ax3.text(bins_out[i] + 2.5, n[i] + max(n) * 0.02, f'{int(n[i])}',
                     ha='center', fontsize=8, fontweight='bold')

    # 右侧统计信息框
    stats = result.get('stats', {})
    info_lines = [
        f"RSI Distribution\n",
        f"{'─' * 20}\n",
        f"  Mean:    {stats.get('mean', 0):.1f}\n",
        f"  Median:  {stats.get('median', 0):.1f}\n",
        f"  Min:     {stats.get('min', 0):.1f}\n",
        f"  Max:     {stats.get('max', 0):.1f}\n",
        f"{'─' * 20}\n",
        f"  Current: {cur_rsi:.1f}\n",
        f"  Percentile: {result.get('latest', {}).get('percentile', 0):.1f}%\n",
    ]
    info_text = ''.join(info_lines)

    ax3.text(0.98, 0.95, info_text, transform=ax3.transAxes, fontsize=9,
             verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFFDE7', alpha=0.9,
                       edgecolor='#E5E7EB', linewidth=1),
             family='monospace')

    # X 轴日期格式
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

    # ===== v2.0: 新增 MACD + KDJ + 布林带子图 =====
    # 重新创建图表，增加更多子图
    plt.close('all')
    fig2 = plt.figure(figsize=(16, 20))
    gs2 = GridSpec(6, 1, height_ratios=[2, 1, 1, 1, 1, 1], hspace=0.35)
    
    # 子图1: 价格走势 + 布林带
    ax_p = fig2.add_subplot(gs2[0])
    boll_col = 'unit_nav' if data_type in ('cn_fund', 'hk_fund', 'cn_auto', 'private_fund') and 'unit_nav' in df.columns else price_col
    boll_closes = pd.to_numeric(df[boll_col], errors='coerce').dropna()
    if len(boll_closes) >= 20:
        from technical_analysis import calc_bollinger
        boll_ma, boll_upper, boll_lower = calc_bollinger(boll_closes.tolist())
        # 将 None 替换为 NaN，避免 fill_between 的 isfinite 报错
        boll_ma = [np.nan if v is None else v for v in boll_ma]
        boll_upper = [np.nan if v is None else v for v in boll_upper]
        boll_lower = [np.nan if v is None else v for v in boll_lower]
        boll_dates = df['date'].iloc[-len(boll_closes):]
        ax_p.plot(boll_dates, boll_closes, color='#2563EB', linewidth=1.2, label='Price')
        ax_p.plot(boll_dates, boll_ma, color='#F59E0B', linewidth=0.8, linestyle='--', label='MA20')
        ax_p.plot(boll_dates, boll_upper, color='#EF4444', linewidth=0.6, alpha=0.6, label='Upper')
        ax_p.plot(boll_dates, boll_lower, color='#22C55E', linewidth=0.6, alpha=0.6, label='Lower')
        ax_p.fill_between(boll_dates, boll_upper, boll_lower, alpha=0.08, color='#94A3B8')
    else:
        ax_p.plot(df_plot['date'], df_plot[price_col], color='#2563EB', linewidth=1.2, label='Price')
    ax_p.set_ylabel('Price', fontsize=11)
    ax_p.set_title(f'{title_prefix} - Technical Analysis Dashboard', fontsize=14, fontweight='bold')
    ax_p.legend(loc='upper left', fontsize=8)
    ax_p.grid(True, alpha=0.3)
    
    # 子图2: RSI(14) + RSI(7)
    ax_r = fig2.add_subplot(gs2[1], sharex=ax_p)
    ax_r.plot(df_plot['date'], df_plot['RSI_14'], color='#7C3AED', linewidth=1.2, label='RSI(14)')
    if 'RSI_7' in df_plot.columns:
        ax_r.plot(df_plot['date'], df_plot['RSI_7'], color='#EC4899', linewidth=0.8, alpha=0.7, label='RSI(7)')
    ax_r.axhline(y=70, color='#DC2626', linestyle='--', alpha=0.4, linewidth=0.8)
    ax_r.axhline(y=30, color='#16A34A', linestyle='--', alpha=0.4, linewidth=0.8)
    ax_r.axhline(y=50, color='#9CA3AF', linestyle=':', alpha=0.3, linewidth=0.5)
    ax_r.fill_between(df_plot['date'], 70, df_plot['RSI_14'], where=(df_plot['RSI_14'] >= 70), color='#FCA5A5', alpha=0.3)
    ax_r.fill_between(df_plot['date'], 30, df_plot['RSI_14'], where=(df_plot['RSI_14'] <= 30), color='#86EFAC', alpha=0.3)
    ax_r.set_ylabel('RSI', fontsize=11)
    ax_r.set_ylim(0, 100)
    ax_r.legend(loc='upper left', fontsize=8)
    ax_r.grid(True, alpha=0.3)
    
    # 子图3: MACD - 仅当有足够数据时
    ax_m = fig2.add_subplot(gs2[2], sharex=ax_p)
    from technical_analysis import calc_macd
    closes_list = pd.to_numeric(df[price_col], errors='coerce').dropna().tolist()
    if len(closes_list) >= 26:
        dif, dea, hist = calc_macd(closes_list)
        macd_dates = df['date'].iloc[-len(dif):]
        ax_m.bar(macd_dates, hist, color=['#EF4444' if h >= 0 else '#22C55E' for h in hist], alpha=0.6, width=1)
        ax_m.plot(macd_dates, dif, color='#2563EB', linewidth=1, label='DIF')
        ax_m.plot(macd_dates, dea, color='#F59E0B', linewidth=1, label='DEA')
        ax_m.axhline(y=0, color='#9CA3AF', linestyle='-', alpha=0.3, linewidth=0.5)
        ax_m.set_ylabel('MACD', fontsize=11)
        ax_m.legend(loc='upper left', fontsize=8)
        ax_m.grid(True, alpha=0.3)
    
    # 子图4: KDJ - 仅当有OHLC数据时
    ax_k = fig2.add_subplot(gs2[3], sharex=ax_p)
    if data_type not in ('cn_fund', 'hk_fund', 'cn_auto', 'private_fund') and all(c in df.columns for c in ['high', 'low']):
        from technical_analysis import calc_kdj
        highs = df['high'].dropna().tolist()
        lows = df['low'].dropna().tolist()
        min_len = min(len(highs), len(lows), len(closes_list))
        k_vals, d_vals, j_vals = calc_kdj(highs[:min_len], lows[:min_len], closes_list[:min_len])
        kdj_dates = df['date'].iloc[-len(k_vals):]
        ax_k.plot(kdj_dates, k_vals, color='#2563EB', linewidth=1, label='K')
        ax_k.plot(kdj_dates, d_vals, color='#F59E0B', linewidth=1, label='D')
        ax_k.plot(kdj_dates, j_vals, color='#EC4899', linewidth=0.8, alpha=0.7, label='J')
        ax_k.axhline(y=80, color='#DC2626', linestyle='--', alpha=0.4, linewidth=0.8)
        ax_k.axhline(y=20, color='#16A34A', linestyle='--', alpha=0.4, linewidth=0.8)
        ax_k.set_ylabel('KDJ', fontsize=11)
        ax_k.set_ylim(0, 100)
        ax_k.legend(loc='upper left', fontsize=8)
        ax_k.grid(True, alpha=0.3)
    else:
        ax_k.text(0.5, 0.5, 'KDJ: 基金无OHLC数据', transform=ax_k.transAxes, ha='center', fontsize=10, color='#9CA3AF')
        ax_k.set_ylabel('KDJ', fontsize=11)
    
    # 子图5: 成交量 (如果有)
    ax_v = fig2.add_subplot(gs2[4], sharex=ax_p)
    if 'volume' in df.columns:
        vol_data = df[['date', 'volume']].dropna()
        colors = ['#EF4444' if df[price_col].iloc[i] >= df[price_col].iloc[i-1] else '#22C55E' 
                  for i in range(len(df)) if i < len(vol_data)]
        ax_v.bar(vol_data['date'], vol_data['volume'], color=colors[:len(vol_data)], alpha=0.6, width=1)
        ax_v.set_ylabel('Volume', fontsize=11)
        ax_v.grid(True, alpha=0.3, axis='y')
    else:
        ax_v.text(0.5, 0.5, 'Volume: 无数据', transform=ax_v.transAxes, ha='center', fontsize=10, color='#9CA3AF')
        ax_v.set_ylabel('Volume', fontsize=11)
    
    # 子图6: RSI分布直方图
    ax_h = fig2.add_subplot(gs2[5])
    rsi_values = df_plot['RSI_14']
    bins = list(range(0, 105, 5))
    n, bins_out, patches = ax_h.hist(rsi_values, bins=bins, edgecolor='white', alpha=0.85, linewidth=0.5)
    for i, patch in enumerate(patches):
        if bins_out[i] < 30: patch.set_facecolor('#22C55E')
        elif bins_out[i] >= 70: patch.set_facecolor('#EF4444')
        else: patch.set_facecolor('#3B82F6')
    ax_h.axvline(x=30, color='#16A34A', linestyle='--', linewidth=1.5, label='Oversold(30)')
    ax_h.axvline(x=70, color='#DC2626', linestyle='--', linewidth=1.5, label='Overbought(70)')
    ax_h.axvline(x=rsi_values.mean(), color='#F59E0B', linestyle='-', linewidth=1.5, label=f'Mean({rsi_values.mean():.1f})')
    ax_h.axvline(x=cur_rsi, color='#7C3AED', linestyle='-', linewidth=2, label=f'Current({cur_rsi:.1f})')
    ax_h.set_xlabel('RSI Value', fontsize=11)
    ax_h.set_ylabel('Count', fontsize=11)
    ax_h.legend(loc='upper left', fontsize=7)
    ax_h.grid(True, alpha=0.3, axis='y')
    ax_h.set_xlim(0, 100)
    
    # 日期格式
    ax_p.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax_p.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # 保存增强版图表
    enhanced_path = output_path.replace('_chart.png', '_dashboard.png')
    plt.tight_layout()
    plt.savefig(enhanced_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close('all')
    
    # 重新生成原来的简单图表
    fig = plt.figure(figsize=(14, 14))
    gs = GridSpec(3, 1, height_ratios=[2, 1, 1], hspace=0.3)
    
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(df_plot['date'], df_plot[price_col], color='#2563EB', linewidth=1)
    ax1.fill_between(df_plot['date'], df_plot[price_col], alpha=0.15, color='#3B82F6')
    ax1.set_ylabel('Price', fontsize=12)
    ax1.set_title(f'{title_prefix} - Price & RSI Analysis', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    oversold = df_plot[df_plot['RSI_14'] <= 30]
    overbought = df_plot[df_plot['RSI_14'] >= 70]
    ax1.scatter(oversold['date'], oversold[price_col], c='#16A34A', s=50, marker='^', label='Oversold', zorder=5, edgecolors='white', linewidths=0.5)
    ax1.scatter(overbought['date'], overbought[price_col], c='#DC2626', s=50, marker='v', label='Overbought', zorder=5, edgecolors='white', linewidths=0.5)
    ax1.legend(loc='upper left', fontsize=9)
    latest_row = df_plot.iloc[-1]
    ax1.annotate(f"{_fmt_price(latest_row[price_col], data_type)}", xy=(latest_row['date'], latest_row[price_col]),
                 xytext=(10, 10), textcoords='offset points', fontsize=10, fontweight='bold', color='#2563EB',
                 arrowprops=dict(arrowstyle='->', color='#2563EB', lw=1.5))
    
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.plot(df_plot['date'], df_plot['RSI_14'], color='#7C3AED', linewidth=1.5, label='RSI(14)')
    ax2.axhline(y=70, color='#DC2626', linestyle='--', alpha=0.5, linewidth=1)
    ax2.axhline(y=30, color='#16A34A', linestyle='--', alpha=0.5, linewidth=1)
    ax2.axhline(y=50, color='#9CA3AF', linestyle=':', alpha=0.4, linewidth=0.8)
    ax2.fill_between(df_plot['date'], 70, df_plot['RSI_14'], where=(df_plot['RSI_14'] >= 70), color='#FCA5A5', alpha=0.4)
    ax2.fill_between(df_plot['date'], 30, df_plot['RSI_14'], where=(df_plot['RSI_14'] <= 30), color='#86EFAC', alpha=0.4)
    ax2.set_ylabel('RSI', fontsize=12)
    ax2.set_ylim(0, 100)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.grid(True, alpha=0.3)
    cur_rsi = latest_row['RSI_14']
    rsi_color = '#DC2626' if cur_rsi >= 70 else '#16A34A' if cur_rsi <= 30 else '#7C3AED'
    ax2.annotate(f"RSI: {cur_rsi:.1f}", xy=(latest_row['date'], cur_rsi), xytext=(10, -15), textcoords='offset points',
                 fontsize=10, fontweight='bold', color=rsi_color, arrowprops=dict(arrowstyle='->', color=rsi_color, lw=1.5))
    
    ax3 = fig.add_subplot(gs[2])
    rsi_values = df_plot['RSI_14']
    bins = list(range(0, 105, 5))
    n, bins_out, patches = ax3.hist(rsi_values, bins=bins, edgecolor='white', alpha=0.85, linewidth=0.5)
    for i, patch in enumerate(patches):
        if bins_out[i] < 30: patch.set_facecolor('#22C55E')
        elif bins_out[i] >= 70: patch.set_facecolor('#EF4444')
        else: patch.set_facecolor('#3B82F6')
    ax3.axvline(x=30, color='#16A34A', linestyle='--', linewidth=2, label='Oversold (30)')
    ax3.axvline(x=70, color='#DC2626', linestyle='--', linewidth=2, label='Overbought (70)')
    mean_val = rsi_values.mean()
    ax3.axvline(x=mean_val, color='#F59E0B', linestyle='-', linewidth=2, label=f'Mean ({mean_val:.1f})')
    ax3.axvline(x=cur_rsi, color='#7C3AED', linestyle='-', linewidth=2.5, label=f'Current ({cur_rsi:.1f})')
    ax3.set_xlabel('RSI Value', fontsize=12)
    ax3.set_ylabel('Count', fontsize=12)
    ax3.set_title(f'RSI(14) Distribution Histogram', fontsize=12, fontweight='bold')
    ax3.legend(loc='upper left', fontsize=8)
    ax3.grid(True, alpha=0.3, axis='y')
    ax3.set_xticks(range(0, 105, 10))
    ax3.set_xlim(0, 100)
    for i in range(len(n)):
        if n[i] > 0:
            ax3.text(bins_out[i] + 2.5, n[i] + max(n) * 0.02, f'{int(n[i])}', ha='center', fontsize=8, fontweight='bold')
    stats = result.get('stats', {})
    info_lines = [f"RSI Distribution\n", f"{'─' * 20}\n", f"  Mean:    {stats.get('mean', 0):.1f}\n",
                  f"  Median:  {stats.get('median', 0):.1f}\n", f"  Min:     {stats.get('min', 0):.1f}\n",
                  f"  Max:     {stats.get('max', 0):.1f}\n", f"{'─' * 20}\n",
                  f"  Current: {cur_rsi:.1f}\n", f"  Percentile: {result.get('latest', {}).get('percentile', 0):.1f}%\n"]
    info_text = ''.join(info_lines)
    ax3.text(0.98, 0.95, info_text, transform=ax3.transAxes, fontsize=9, verticalalignment='top',
             horizontalalignment='right', bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFFDE7', alpha=0.9,
             edgecolor='#E5E7EB', linewidth=1), family='monospace')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()

    return output_path


def _fmt_price(price, data_type):
    """格式化价格"""
    if data_type == 'us_stock':
        return f"${price:.2f}"
    return f"{price:.4f}"
