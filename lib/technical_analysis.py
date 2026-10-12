#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全面技术分析模块 v2.0 - MACD/KDJ/ATR/OBV/CCI/Williams/ADX/MFI/RSI背离/斐波那契/均线系统/量价分析

v2.0 更新:
  - 新增 ADX (平均趋向指数) 趋势强度判断
  - 新增 MFI (资金流量指数) 量价结合指标
  - 新增 RSI 背离检测 (顶背离/底背离)
  - 新增 量价关系分析 (放量上涨/缩量下跌等)
  - 改进综合信号打分系统 (加权评分)
  - 新增 趋势强度评估
  - 新增 支撑/阻力位自动识别 (基于局部极值)
"""

import os

import numpy as np
import pandas as pd


def ema(series, period):
    values = series if isinstance(series, list) else series.tolist()
    result = [values[0]]
    k = 2 / (period + 1)
    for i in range(1, len(values)):
        result.append(values[i] * k + result[-1] * (1 - k))
    return result


def indicator_ema(series, period):
    """TA-Lib style EMA: seed with the first period's simple average."""
    values = series if isinstance(series, list) else series.tolist()
    if len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1) + [sum(values[:period]) / period]
    k = 2 / (period + 1)
    for value in values[period:]:
        result.append(value * k + result[-1] * (1 - k))
    return result


def sma(series, period):
    values = pd.Series(series)
    return values.rolling(window=period).mean().tolist()


def calc_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = ema(dif, signal)
    hist = [(dif[i] - dea[i]) * 2 for i in range(len(closes))]
    return dif, dea, hist


def calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    k_vals = [50.0]
    d_vals = [50.0]
    j_vals = [50.0]
    for i in range(1, len(closes)):
        start = max(0, i - n + 1)
        hh = max(highs[start:i+1])
        ll = min(lows[start:i+1])
        if hh == ll:
            rsv = 50.0
        else:
            rsv = (closes[i] - ll) / (hh - ll) * 100
        k = (m1 - 1) / m1 * k_vals[-1] + 1 / m1 * rsv
        d = (m2 - 1) / m2 * d_vals[-1] + 1 / m2 * k
        j = 3 * k - 2 * d
        k_vals.append(k)
        d_vals.append(d)
        j_vals.append(j)
    return k_vals, d_vals, j_vals


def calc_atr(highs, lows, closes, period=14):
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    if len(tr_list) < period:
        return [None] * len(closes)
    atr_vals = [sum(tr_list[:period]) / period]
    for i in range(period, len(tr_list)):
        atr_vals.append((atr_vals[-1] * (period - 1) + tr_list[i]) / period)
    return [None] * (len(closes) - len(atr_vals)) + atr_vals


def calc_obv(closes, volumes):
    if volumes is None:
        return None
    obv = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i-1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def calc_cci(highs, lows, closes, period=14):
    tps = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cci = []
    for i in range(period - 1, len(tps)):
        tp_slice = tps[i - period + 1:i + 1]
        tp_mean = sum(tp_slice) / period
        md = sum(abs(tp - tp_mean) for tp in tp_slice) / period
        if md == 0:
            cci.append(0)
        else:
            cci.append((tps[i] - tp_mean) / (0.015 * md))
    return [None] * (period - 1) + cci


def calc_williams_r(highs, lows, closes, period=14):
    wr = []
    for i in range(period - 1, len(closes)):
        hh = max(highs[i - period + 1:i + 1])
        ll = min(lows[i - period + 1:i + 1])
        if hh == ll:
            wr.append(-50)
        else:
            wr.append((hh - closes[i]) / (hh - ll) * -100)
    return [None] * (period - 1) + wr


def calc_stochastic(highs, lows, closes, fastk_n=14, slowk_n=3, slowd_n=3):
    raw_k = []
    for i in range(fastk_n - 1, len(closes)):
        hh = max(highs[i - fastk_n + 1:i + 1])
        ll = min(lows[i - fastk_n + 1:i + 1])
        if hh == ll:
            raw_k.append(50)
        else:
            raw_k.append((closes[i] - ll) / (hh - ll) * 100)
    raw_k_full = [None] * (fastk_n - 1) + raw_k
    slow_k = sma([x for x in raw_k_full if x is not None], slowk_n)
    slow_k_full = [None] * (fastk_n - 1) + slow_k
    valid_sk = [x for x in slow_k_full if x is not None]
    slow_d = sma(valid_sk, slowd_n)
    slow_d_full = [None] * (len(slow_k_full) - len(slow_d)) + slow_d
    return slow_k_full, slow_d_full


def calc_bollinger(closes, period=20, std_dev=2):
    ma = sma(closes, period)
    upper = []
    lower = []
    for i in range(len(closes)):
        if i < period - 1 or ma[i] is None or np.isnan(ma[i]):
            upper.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            std = np.std(window, ddof=0)
            upper.append(ma[i] + std_dev * std)
            lower.append(ma[i] - std_dev * std)
    return ma, upper, lower


# ============================================================
# v2.0 新增指标
# ============================================================

def calc_adx(highs, lows, closes, period=14):
    """ADX 趋势强度: >25趋势明显, >40强趋势, <20无趋势"""
    n = len(closes)
    if n < period + 1:
        return [None] * n, [None] * n, [None] * n
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
    atr_vals = [sum(tr[:period]) / period]
    plus_di_vals = [sum(plus_dm[:period]) / period]
    minus_di_vals = [sum(minus_dm[:period]) / period]
    for i in range(period, len(tr)):
        atr_vals.append((atr_vals[-1] * (period - 1) + tr[i]) / period)
        plus_di_vals.append((plus_di_vals[-1] * (period - 1) + plus_dm[i]) / period)
        minus_di_vals.append((minus_di_vals[-1] * (period - 1) + minus_dm[i]) / period)
    plus_di = [None] + [100 * p / a if a > 0 else 0 for p, a in zip(plus_di_vals, atr_vals)]
    minus_di = [None] + [100 * m / a if a > 0 else 0 for m, a in zip(minus_di_vals, atr_vals)]
    dx_vals = []
    for i in range(len(plus_di)):
        if plus_di[i] is None or minus_di[i] is None:
            dx_vals.append(None)
        else:
            denom = plus_di[i] + minus_di[i]
            dx_vals.append(100 * abs(plus_di[i] - minus_di[i]) / denom if denom > 0 else 0)
    valid_dx = [x for x in dx_vals if x is not None]
    if len(valid_dx) < period:
        return [None] * n, [None] * n, [None] * n
    adx_vals = [sum(valid_dx[:period]) / period]
    for i in range(period, len(valid_dx)):
        adx_vals.append((adx_vals[-1] * (period - 1) + valid_dx[i]) / period)
    adx_full = [None] * (n - len(adx_vals)) + adx_vals
    return adx_full, plus_di, minus_di


def calc_mfi(highs, lows, closes, volumes, period=14):
    """MFI 资金流量指数: <20超卖, >80超买"""
    if volumes is None:
        return None
    n = len(closes)
    if n < period + 1:
        return None
    typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    money_flows = [tp * v for tp, v in zip(typical_prices, volumes)]
    positive_flow, negative_flow = [], []
    for i in range(1, n):
        if typical_prices[i] > typical_prices[i-1]:
            positive_flow.append(money_flows[i]); negative_flow.append(0)
        elif typical_prices[i] < typical_prices[i-1]:
            positive_flow.append(0); negative_flow.append(money_flows[i])
        else:
            positive_flow.append(0); negative_flow.append(0)
    mfi_vals = [None] * period
    for i in range(period, len(positive_flow)):
        pos_sum = sum(positive_flow[i-period:i])
        neg_sum = sum(negative_flow[i-period:i])
        mfi_vals.append(100 - 100 / (1 + pos_sum / neg_sum) if neg_sum > 0 else 100.0)
    return mfi_vals


def detect_rsi_divergence(df, price_col, rsi_col='RSI_14', lookback=20):
    """RSI背离检测: 顶背离看跌, 底背离看涨"""
    if rsi_col not in df.columns:
        return None
    valid = df[[price_col, rsi_col]].dropna()
    if len(valid) < lookback:
        return None
    prices = valid[price_col].values
    rsis = valid[rsi_col].values
    recent_n = min(lookback, len(prices))
    recent_prices = prices[-recent_n:]
    recent_rsis = rsis[-recent_n:]
    result = {'bearish': None, 'bullish': None}
    # 底背离
    price_lows, rsi_lows = [], []
    for i in range(1, recent_n - 1):
        if recent_prices[i] < recent_prices[i-1] and recent_prices[i] < recent_prices[i+1]:
            price_lows.append((i, recent_prices[i]))
        if recent_rsis[i] < recent_rsis[i-1] and recent_rsis[i] < recent_rsis[i+1]:
            rsi_lows.append((i, recent_rsis[i]))
    if len(price_lows) >= 2 and price_lows[-1][1] < price_lows[-2][1]:
        rsi_at_lows = [recent_rsis[p[0]] for p in price_lows[-2:]]
        if rsi_at_lows[-1] > rsi_at_lows[-2]:
            result['bullish'] = {'type': '底背离', 'signal': '看涨',
                'price_low1': round(price_lows[-2][1], 4), 'price_low2': round(price_lows[-1][1], 4),
                'rsi_low1': round(rsi_at_lows[-2], 1), 'rsi_low2': round(rsi_at_lows[-1], 1)}
    # 顶背离
    price_highs, rsi_highs = [], []
    for i in range(1, recent_n - 1):
        if recent_prices[i] > recent_prices[i-1] and recent_prices[i] > recent_prices[i+1]:
            price_highs.append((i, recent_prices[i]))
        if recent_rsis[i] > recent_rsis[i-1] and recent_rsis[i] > recent_rsis[i+1]:
            rsi_highs.append((i, recent_rsis[i]))
    if len(price_highs) >= 2 and price_highs[-1][1] > price_highs[-2][1]:
        rsi_at_highs = [recent_rsis[p[0]] for p in price_highs[-2:]]
        if rsi_at_highs[-1] < rsi_at_highs[-2]:
            result['bearish'] = {'type': '顶背离', 'signal': '看跌',
                'price_high1': round(price_highs[-2][1], 4), 'price_high2': round(price_highs[-1][1], 4),
                'rsi_high1': round(rsi_at_highs[-2], 1), 'rsi_high2': round(rsi_at_highs[-1], 1)}
    return result if (result['bearish'] or result['bullish']) else None


def analyze_volume_price(closes, volumes, lookback=20):
    """量价关系分析"""
    if volumes is None:
        return None
    n = len(closes)
    if n < lookback:
        return None
    recent_prices = closes[-lookback:]
    recent_volumes = volumes[-lookback:]
    price_change = (recent_prices[-1] / recent_prices[0] - 1) * 100
    vol_first_half = sum(recent_volumes[:lookback//2]) / (lookback//2)
    vol_second_half = sum(recent_volumes[lookback//2:]) / (lookback - lookback//2)
    vol_change = (vol_second_half / vol_first_half - 1) * 100 if vol_first_half > 0 else 0
    last_5_volumes = recent_volumes[-5:]
    avg_vol_20 = sum(recent_volumes) / lookback
    avg_vol_5 = sum(last_5_volumes) / 5
    result = {'price_change_20d': round(price_change, 2), 'volume_change_20d': round(vol_change, 2),
              'vol_ratio_5vs20': round(avg_vol_5 / avg_vol_20, 2) if avg_vol_20 > 0 else 0}
    if price_change > 5 and vol_change > 10:
        result['pattern'] = '放量上涨 (强势)'; result['signal'] = 'bullish'
    elif price_change > 5 and vol_change < -10:
        result['pattern'] = '缩量上涨 (动能衰减)'; result['signal'] = 'caution'
    elif price_change < -5 and vol_change > 10:
        result['pattern'] = '放量下跌 (恐慌抛售)'; result['signal'] = 'bearish'
    elif price_change < -5 and vol_change < -10:
        result['pattern'] = '缩量下跌 (抛压减弱)'; result['signal'] = 'potential_bottom'
    elif abs(price_change) < 3 and vol_change > 10:
        result['pattern'] = '放量横盘 (多空争夺)'; result['signal'] = 'neutral'
    else:
        result['pattern'] = '量价正常'; result['signal'] = 'neutral'
    return result


def find_support_resistance(closes, lookback=60, min_distance_pct=3):
    """自动识别支撑阻力位"""
    n = len(closes)
    if n < lookback:
        lookback = n
    recent = closes[-lookback:]
    supports, resistances = [], []
    for i in range(2, len(recent) - 2):
        if recent[i] < recent[i-1] and recent[i] < recent[i-2] and recent[i] < recent[i+1] and recent[i] < recent[i+2]:
            supports.append(recent[i])
        if recent[i] > recent[i-1] and recent[i] > recent[i-2] and recent[i] > recent[i+1] and recent[i] > recent[i+2]:
            resistances.append(recent[i])
    def merge_levels(levels, min_pct):
        if not levels:
            return []
        levels = sorted(set(levels))
        merged = [levels[0]]
        for l in levels[1:]:
            if (l / merged[-1] - 1) * 100 > min_pct:
                merged.append(l)
        return [round(x, 4) for x in merged]
    current_price = closes[-1]
    supports = merge_levels(supports, min_distance_pct)
    resistances = merge_levels(resistances, min_distance_pct)
    supports = [s for s in supports if s < current_price][-3:]
    resistances = [r for r in resistances if r > current_price][:3]
    return {'supports': supports, 'resistances': resistances, 'current_price': round(current_price, 4)}


def calc_trend_strength(closes, period=20):
    """趋势强度评估"""
    n = len(closes)
    if n < period:
        return None
    ma = sma(closes, period)
    valid_ma = [m for m in ma if m is not None]
    if not valid_ma:
        return None
    current_price = closes[-1]
    current_ma = valid_ma[-1]
    deviation = (current_price / current_ma - 1) * 100
    slope = (closes[-1] / closes[-10] - 1) * 100 if n >= 10 else 0
    if abs(deviation) > 15:
        strength = '极端'
    elif abs(deviation) > 10:
        strength = '强'
    elif abs(deviation) > 5:
        strength = '中等'
    elif abs(deviation) > 2:
        strength = '弱'
    else:
        strength = '无'
    direction = '上涨' if slope > 0.5 else '下跌' if slope < -0.5 else '横盘'
    return {'direction': direction, 'strength': strength, 'deviation_pct': round(deviation, 2),
            'slope_10d': round(slope, 2), 'ma_period': period, 'ma_value': round(current_ma, 4)}


# ============================================================
# 主分析函数
# ============================================================

def run_technical_analysis(df, price_col, data_type):
    is_fund = data_type in ('cn_fund', 'hk_fund', 'cn_auto', 'private_fund')
    has_ohlc = all(c in df.columns for c in ['open', 'high', 'low'])
    has_volume = 'volume' in df.columns
    closes = df[price_col].dropna().tolist()
    n = len(closes)
    if n < 30:
        return {'error': f'数据量不足 (仅{n}条), 需要至少30条'}
    display_price = round(df['unit_nav'].dropna().iloc[-1], 4) if is_fund and 'unit_nav' in df.columns else round(closes[-1], 4)
    cumulative_nav = round(df['acc_nav'].dropna().iloc[-1], 4) if is_fund and 'acc_nav' in df.columns else None
    analysis_price = round(closes[-1], 4)
    result = {'data_type': data_type, 'is_fund': is_fund, 'total_records': n,
              'date_range': {'start': df['date'].min().strftime('%Y-%m-%d'), 'end': df['date'].max().strftime('%Y-%m-%d')},
              'latest_price': display_price, 'cumulative_nav': cumulative_nav, 'analysis_price': analysis_price,
              'latest_date': df['date'].max().strftime('%Y-%m-%d'),
              'data_quality': {
                  'source': df.attrs.get('data_source', 'unknown'),
                  'price_basis': df.attrs.get('price_basis', price_col),
                  'as_of': df['date'].max().strftime('%Y-%m-%d'),
                  'latest_verified': df.attrs.get('latest_verified'),
                  'expected_records': df.attrs.get('reference_total_count') or df.attrs.get('expected_records'),
                  'parsed_records': len(df),
                  'max_gap_days': df.attrs.get('max_gap_days'),
                  'analysis_start_override': df.attrs.get('analysis_start_override'),
                  'source_history_start': df.attrs.get('source_history_start'),
                  'source_history_records': df.attrs.get('source_history_records'),
              }}

    # 1. 均线系统
    ema_result = {}
    for period in [5, 10, 20, 50, 60, 100, 200]:
        if n >= period:
            vals = indicator_ema(closes, period)
            ema_result[f'EMA{period}'] = round(vals[-1], 4)
            if n >= period + 1:
                ema_result[f'EMA{period}_prev'] = round(vals[-2], 4)
    result['ema'] = ema_result
    ema_keys = [f'EMA{p}' for p in [5, 10, 20, 50, 60, 100, 200] if f'EMA{p}' in ema_result]
    if len(ema_keys) >= 3:
        ema_vals = [ema_result[k] for k in ema_keys]
        if all(ema_vals[i] >= ema_vals[i+1] for i in range(len(ema_vals)-1)):
            result['ma_alignment'] = '多头排列'
        elif all(ema_vals[i] <= ema_vals[i+1] for i in range(len(ema_vals)-1)):
            result['ma_alignment'] = '空头排列'
        else:
            result['ma_alignment'] = '均线缠绕'
    else:
        result['ma_alignment'] = '数据不足'
    price = closes[-1]
    result['price_vs_ma'] = {}
    for k, v in ema_result.items():
        if k.endswith('_prev'):
            continue
        pos = '上方' if price > v else '下方'
        pct = round((price - v) / v * 100, 2) if v != 0 else 0
        result['price_vs_ma'][k] = {'position': pos, 'pct': pct}

    # 1.5 EMA60。技术指标始终使用 price_col 对应的同一价格口径。
    ema60_value = ema_result.get('EMA60')
    ema60_info = {
        'price': round(price, 4) if ema60_value is not None else None,
        'value': ema60_value,
        'distance_pct': round((price / ema60_value - 1) * 100, 2) if ema60_value else None,
        'price_source': price_col,
    }
    result['ema60'] = ema60_info
    # 兼容旧版前端/缓存读取；值已明确改为 EMA60，不再计算 SMA60。
    result['ma60'] = ema60_info

    # 2. MACD
    dif, dea, hist = calc_macd(closes)
    result['macd'] = {'DIF': round(dif[-1], 4), 'DEA': round(dea[-1], 4), 'MACD_hist': round(hist[-1], 4),
                      'DIF_prev': round(dif[-2], 4) if n > 1 else None, 'DEA_prev': round(dea[-2], 4) if n > 1 else None}
    if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
        result['macd']['signal'] = '金叉'
    elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
        result['macd']['signal'] = '死叉'
    elif dif[-1] > dea[-1]:
        result['macd']['signal'] = 'DIF>DEA多头'
    else:
        result['macd']['signal'] = 'DIF<DEA空头'
    result['macd']['trend'] = []
    for i in range(max(0, n-5), n):
        result['macd']['trend'].append({'DIF': round(dif[i], 4), 'DEA': round(dea[i], 4), 'hist': round(hist[i], 4)})

    # 3-7. OHLC 指标
    if has_ohlc:
        highs = df['high'].dropna().tolist()
        lows = df['low'].dropna().tolist()
        min_len = min(len(highs), len(lows), len(closes))
        k_vals, d_vals, j_vals = calc_kdj(highs[:min_len], lows[:min_len], closes[:min_len])
        result['kdj'] = {'K': round(k_vals[-1], 2), 'D': round(d_vals[-1], 2), 'J': round(j_vals[-1], 2),
                         'K_prev': round(k_vals[-2], 2), 'D_prev': round(d_vals[-2], 2)}
        if k_vals[-1] > d_vals[-1] and k_vals[-2] <= d_vals[-2]:
            result['kdj']['signal'] = '金叉'
        elif k_vals[-1] < d_vals[-1] and k_vals[-2] >= d_vals[-2]:
            result['kdj']['signal'] = '死叉'
        elif k_vals[-1] > d_vals[-1]:
            result['kdj']['signal'] = 'K>D'
        else:
            result['kdj']['signal'] = 'K<D'
        j = j_vals[-1]
        if j < 0: result['kdj']['zone'] = '极度超卖'
        elif j < 20: result['kdj']['zone'] = '超卖区'
        elif j > 100: result['kdj']['zone'] = '极度超买'
        elif j > 80: result['kdj']['zone'] = '超买区'
        else: result['kdj']['zone'] = '正常'

        slow_k, slow_d = calc_stochastic(highs[:min_len], lows[:min_len], closes[:min_len])
        result['stoch'] = {'SlowK': round(slow_k[-1], 2) if slow_k[-1] is not None else None,
                           'SlowD': round(slow_d[-1], 2) if slow_d[-1] is not None else None}
        sk_val = slow_k[-1]
        if sk_val is not None:
            result['stoch']['zone'] = '超卖' if sk_val < 20 else '超买' if sk_val > 80 else '正常'

        atr_vals = calc_atr(highs[:min_len], lows[:min_len], closes[:min_len])
        atr_now = atr_vals[-1]
        if atr_now is not None:
            result['atr'] = {'value': round(atr_now, 4), 'pct_of_price': round(atr_now / price * 100, 2)}

        cci_vals = calc_cci(highs[:min_len], lows[:min_len], closes[:min_len])
        cci_now = cci_vals[-1]
        result['cci'] = {'value': round(cci_now, 2)}
        result['cci']['zone'] = '超卖' if cci_now < -100 else '超买' if cci_now > 100 else '正常'

        wr_vals = calc_williams_r(highs[:min_len], lows[:min_len], closes[:min_len])
        wr_now = wr_vals[-1]
        result['williams_r'] = {'value': round(wr_now, 2)}
        result['williams_r']['zone'] = '超卖' if wr_now < -80 else '超买' if wr_now > -20 else '正常'

        # ADX
        adx_vals, plus_di, minus_di = calc_adx(highs[:min_len], lows[:min_len], closes[:min_len])
        adx_now = adx_vals[-1]
        if adx_now is not None:
            result['adx'] = {'value': round(adx_now, 2), 'plus_di': round(plus_di[-1], 2) if plus_di[-1] is not None else None,
                             'minus_di': round(minus_di[-1], 2) if minus_di[-1] is not None else None}
            if adx_now > 40: result['adx']['trend_strength'] = '强趋势'
            elif adx_now > 25: result['adx']['trend_strength'] = '趋势明显'
            elif adx_now > 20: result['adx']['trend_strength'] = '弱趋势'
            else: result['adx']['trend_strength'] = '无趋势/震荡'
            result['adx']['direction'] = '多头' if (plus_di[-1] or 0) > (minus_di[-1] or 0) else '空头'
        else:
            result['adx'] = None

        # MFI
        if has_volume:
            volumes = df['volume'].tolist()
            mfi_vals = calc_mfi(highs[:min_len], lows[:min_len], closes[:min_len], volumes[:min_len])
            if mfi_vals is not None and mfi_vals[-1] is not None:
                mfi_now = mfi_vals[-1]
                result['mfi'] = {'value': round(mfi_now, 2)}
                if mfi_now < 20: result['mfi']['zone'] = '超卖'
                elif mfi_now > 80: result['mfi']['zone'] = '超买'
                elif mfi_now < 35: result['mfi']['zone'] = '偏低'
                elif mfi_now > 65: result['mfi']['zone'] = '偏高'
                else: result['mfi']['zone'] = '正常'
            else:
                result['mfi'] = None
        else:
            result['mfi'] = None
    else:
        result['kdj'] = None; result['stoch'] = None; result['atr'] = None
        result['cci'] = None; result['williams_r'] = None
        result['adx'] = None; result['mfi'] = None

    # 8. 布林带 (统一使用 price_col 即 adj_nav，避免分红日 unit_nav 跳跌导致布林带失真)
    boll_closes = df[price_col].dropna().tolist()
    boll_ma, boll_upper, boll_lower = calc_bollinger(boll_closes)
    boll_ma_now = boll_ma[-1]; boll_upper_now = boll_upper[-1]; boll_lower_now = boll_lower[-1]
    if all(v is not None for v in [boll_ma_now, boll_upper_now, boll_lower_now]):
        boll_price = boll_closes[-1] if boll_closes else price
        result['bollinger'] = {'upper': round(boll_upper_now, 4), 'ma20': round(boll_ma_now, 4),
                               'lower': round(boll_lower_now, 4), 'current_price': round(boll_price, 4)}
        bw = boll_upper_now - boll_lower_now
        result['bollinger']['percent_b'] = round((boll_price - boll_lower_now) / bw * 100, 1) if bw != 0 else 50.0
        result['bollinger']['bandwidth'] = round(bw / boll_ma_now * 100, 2) if boll_ma_now != 0 else 0
        result['bollinger']['dist_to_lower'] = round((boll_price - boll_lower_now) / boll_lower_now * 100, 2) if boll_lower_now != 0 else 0
        result['bollinger']['dist_to_upper'] = round((boll_price - boll_upper_now) / boll_upper_now * 100, 2) if boll_upper_now != 0 else 0
        if boll_price <= boll_lower_now: result['bollinger']['position'] = '触及下轨'
        elif boll_price >= boll_upper_now: result['bollinger']['position'] = '触及上轨'
        elif boll_price < boll_ma_now: result['bollinger']['position'] = '中轨下方'
        else: result['bollinger']['position'] = '中轨上方'
        # 保存最近60天的布林带序列用于前端绘图
        boll_dates = df['date'].tolist() if 'date' in df.columns else []
        n = len(boll_closes)
        seq_len = min(60, n)
        _fmt_date = lambda d: str(d).split(' ')[0] if ' ' in str(d) else str(d)
        result['bollinger']['series'] = {
            'dates': [_fmt_date(boll_dates[i]) for i in range(n - seq_len, n) if i >= 0 and boll_ma[i] is not None],
            'upper': [round(float(boll_upper[i]), 4) for i in range(n - seq_len, n) if i >= 0 and boll_upper[i] is not None],
            'mid': [round(float(boll_ma[i]), 4) for i in range(n - seq_len, n) if i >= 0 and boll_ma[i] is not None],
            'lower': [round(float(boll_lower[i]), 4) for i in range(n - seq_len, n) if i >= 0 and boll_lower[i] is not None],
            'price': [round(float(boll_closes[i]), 4) for i in range(n - seq_len, n) if i >= 0 and boll_ma[i] is not None],
        }
    else:
        result['bollinger'] = None

    # 9. OBV
    if has_volume:
        volumes = df['volume'].tolist()
        obv_vals = calc_obv(closes, volumes)
        if obv_vals is not None:
            obv_ma5 = sum(obv_vals[-5:]) / 5; obv_ma10 = sum(obv_vals[-10:]) / 10
            result['obv'] = {'value': obv_vals[-1], 'ma5': round(obv_ma5), 'ma10': round(obv_ma10),
                             'trend': '资金流入' if obv_vals[-1] > obv_ma5 else '资金流出'}
    else:
        result['obv'] = None

    # 10. 成交量
    if has_volume:
        volumes = df['volume'].tolist()
        vol_ma5 = sum(volumes[-5:]) / 5; vol_ma10 = sum(volumes[-10:]) / 10; vol_ma20 = sum(volumes[-20:]) / 20
        result['volume'] = {'current': int(volumes[-1]), 'ma5': round(vol_ma5), 'ma10': round(vol_ma10),
                            'ma20': round(vol_ma20), 'ratio': round(volumes[-1] / vol_ma5, 2) if vol_ma5 > 0 else 0}
    else:
        result['volume'] = None

    # 10.5 量价关系
    if has_volume:
        result['volume_price'] = analyze_volume_price(closes, volumes)
    else:
        result['volume_price'] = None

    # 11. 涨跌幅
    result['change_stats'] = {}
    for days in [5, 10, 20, 50, 100, 200]:
        if n > days:
            result['change_stats'][f'{days}d'] = round((closes[-1] / closes[-1 - days] - 1) * 100, 2)
    peak = closes[0]; max_dd = 0
    for c in closes:
        if c > peak: peak = c
        dd = (c - peak) / peak
        if dd < max_dd: max_dd = dd
    result['change_stats']['max_drawdown'] = round(max_dd * 100, 2)

    # 12. 支撑/阻力 + 斐波那契
    recent_n = min(30, n)
    recent_highs = closes[-recent_n:]; recent_lows = closes[-recent_n:]
    swing_high = max(recent_highs); swing_low = min(recent_lows)
    diff = swing_high - swing_low
    result['support_resistance'] = {'swing_high': round(swing_high, 4), 'swing_low': round(swing_low, 4),
                                    'range_pct': round(diff / swing_low * 100, 2) if swing_low != 0 else 0}
    if diff > 0:
        result['fibonacci'] = {'23.6%': round(swing_low + diff * 0.236, 4), '38.2%': round(swing_low + diff * 0.382, 4),
                               '50.0%': round(swing_low + diff * 0.500, 4), '61.8%': round(swing_low + diff * 0.618, 4),
                               '78.6%': round(swing_low + diff * 0.786, 4)}

    # 12.5 自动支撑阻力
    result['auto_sr'] = find_support_resistance(closes)

    # 12.6 趋势强度
    result['trend_strength'] = calc_trend_strength(closes)

    # 12.7 RSI背离
    if 'RSI_14' in df.columns:
        result['rsi_divergence'] = detect_rsi_divergence(df, price_col)
    else:
        result['rsi_divergence'] = None

    # 13. 综合信号打分
    bull = 0; bear = 0; signals = []
    if 'RSI_14' in df.columns:
        rsi_val = df['RSI_14'].dropna().iloc[-1] if len(df['RSI_14'].dropna()) > 0 else None
        if rsi_val is not None:
            if rsi_val < 25: bull += 3; signals.append(f'RSI={rsi_val:.1f} 极度超卖')
            elif rsi_val < 30: bull += 2; signals.append(f'RSI={rsi_val:.1f} 超卖')
            elif rsi_val > 75: bear += 3; signals.append(f'RSI={rsi_val:.1f} 极度超买')
            elif rsi_val > 70: bear += 2; signals.append(f'RSI={rsi_val:.1f} 超买')
    macd_sig = result['macd']['signal']
    if '金叉' in macd_sig: bull += 2; signals.append(f'MACD {macd_sig}')
    elif '死叉' in macd_sig: bear += 2; signals.append(f'MACD {macd_sig}')
    elif '空头' in macd_sig: bear += 1
    else: bull += 1
    if result['macd']['trend']:
        hists = [t['hist'] for t in result['macd']['trend']]
        if all(h < 0 for h in hists) and abs(hists[-1]) < abs(hists[0]):
            signals.append('MACD绿柱收敛(空头动能衰减)'); bull += 1
        elif all(h > 0 for h in hists) and abs(hists[-1]) < abs(hists[0]):
            signals.append('MACD红柱收敛(多头动能衰减)'); bear += 1
    if result.get('kdj'):
        if result['kdj']['signal'] == '金叉': bull += 1; signals.append(f'KDJ金叉 J={result["kdj"]["J"]:.1f}')
        elif result['kdj']['signal'] == '死叉': bear += 1; signals.append('KDJ死叉')
        if result['kdj']['zone'] in ('极度超卖', '超卖区'): bull += 1; signals.append(f'KDJ {result["kdj"]["zone"]}')
        elif result['kdj']['zone'] in ('极度超买', '超买区'): bear += 1; signals.append(f'KDJ {result["kdj"]["zone"]}')
    if result.get('bollinger'):
        if result['bollinger']['position'] == '触及下轨': bull += 1; signals.append('价格触及布林带下轨')
        elif result['bollinger']['position'] == '触及上轨': bear += 1; signals.append('价格触及布林带上轨')
    if result['ma_alignment'] == '多头排列': bull += 2; signals.append('均线多头排列')
    elif result['ma_alignment'] == '空头排列': bear += 2; signals.append('均线空头排列')
    if result.get('cci'):
        if result['cci']['zone'] == '超卖': bull += 1; signals.append(f'CCI={result["cci"]["value"]:.1f} 超卖')
        elif result['cci']['zone'] == '超买': bear += 1; signals.append(f'CCI={result["cci"]["value"]:.1f} 超买')
    if result.get('williams_r'):
        if result['williams_r']['zone'] == '超卖': bull += 1; signals.append(f'W%R={result["williams_r"]["value"]:.1f} 超卖')
        elif result['williams_r']['zone'] == '超买': bear += 1; signals.append(f'W%R={result["williams_r"]["value"]:.1f} 超买')
    if result.get('obv'):
        if result['obv']['trend'] == '资金流出': bear += 1; signals.append('OBV资金流出')
        else: bull += 1
    if result.get('adx'):
        if result['adx']['trend_strength'] == '强趋势':
            if result['adx']['direction'] == '多头': bull += 1; signals.append(f'ADX={result["adx"]["value"]:.1f} 强多头趋势')
            else: bear += 1; signals.append(f'ADX={result["adx"]["value"]:.1f} 强空头趋势')
    if result.get('mfi'):
        if result['mfi']['zone'] == '超卖': bull += 1; signals.append(f'MFI={result["mfi"]["value"]:.1f} 超卖')
        elif result['mfi']['zone'] == '超买': bear += 1; signals.append(f'MFI={result["mfi"]["value"]:.1f} 超买')
    if result.get('rsi_divergence'):
        if result['rsi_divergence'].get('bullish'): bull += 2; signals.append('RSI底背离(看涨)')
        if result['rsi_divergence'].get('bearish'): bear += 2; signals.append('RSI顶背离(看跌)')
    if result.get('volume_price'):
        vp = result['volume_price']
        if vp['signal'] == 'bullish': bull += 1; signals.append(f'量价: {vp["pattern"]}')
        elif vp['signal'] == 'bearish': bear += 1; signals.append(f'量价: {vp["pattern"]}')
        elif vp['signal'] == 'potential_bottom': bull += 1; signals.append(f'量价: {vp["pattern"]}')
    total = bull + bear
    if total == 0: overall = '中性'
    elif bull > bear * 1.5: overall = '偏多'
    elif bear > bull * 1.5: overall = '偏空'
    else: overall = '多空交织'
    # 基金类资产无 OHLC/量价数据，KDJ/MACD/布林带/ADX/MFI 等指标自动跳过，
    # 信号明细会偏少，补充说明基金类资产的正常情况。
    if not signals:
        signals = ['基金类资产无OHLC/量价数据，以净值RSI+均线趋势为主，信号项较少属正常']
    result['signal_summary'] = {'bull': bull, 'bear': bear, 'overall': overall, 'details': signals}
    return result


# ============================================================
# 报告格式化
# ============================================================

def format_technical_report(result, asset_name=''):
    lines = []
    L = lines.append
    symbol = result.get('symbol', '')
    L(f'# {symbol} 全面技术分析报告')
    if asset_name:
        L(f'**{asset_name}** | {result["date_range"]["start"]} ~ {result["date_range"]["end"]} | {result["total_records"]}个数据点')
    L(f'最新展示价: **{result["latest_price"]}** ({result["latest_date"]})')
    if result.get('is_fund'):
        quality = result.get('data_quality', {})
        if result.get('cumulative_nav') is not None:
            L(f'官方累计净值: **{result["cumulative_nav"]}**')
        if quality.get('price_basis') == 'cumulative_nav':
            L(f'技术指标输入: **官方累计净值 {result.get("analysis_price", result["latest_price"])}** '
              f'(来源: {quality.get("source", "unknown")})')
        else:
            L(f'技术指标计算价格: **{result.get("analysis_price", result["latest_price"])}** '
              f'(口径: {quality.get("price_basis", "unknown")}, 来源: {quality.get("source", "unknown")})')
        verified = quality.get('latest_verified')
        L(f'数据完整性: **{"已与 F10 核验" if verified else "主源内部校验通过，F10 未核验"}** '
          f'| 记录数: {quality.get("parsed_records", result["total_records"])}'
          f'/{quality.get("expected_records") or quality.get("parsed_records", result["total_records"])}')
        if quality.get('analysis_start_override'):
            L(f'分析制度起点: **{quality["analysis_start_override"]}** '
              f'(原始历史自 {quality.get("source_history_start", "unknown")}，按配置主动截断)')
    L('')
    if result.get('is_fund'):
        L('> 基金类资产无 OHLC/成交量数据，KDJ/ATR/CCI/Williams/ADX/MFI/OBV 等指标已自动跳过')
        L('')
    L('## 一、涨跌幅统计')
    L('')
    changes = result.get('change_stats', {})
    row1 = []
    for k in ['5d', '10d', '20d', '50d', '100d', '200d']:
        if k in changes:
            v = changes[k]; emoji = '+' if v > 0 else ''
            row1.append(f'{k}: {emoji}{v}%')
    L(' | '.join(row1))
    if 'max_drawdown' in changes: L(f'最大回撤: {changes["max_drawdown"]}%')
    L('')
    L('## 二、均线系统')
    L('')
    ema_data = result.get('ema', {}); pv = result.get('price_vs_ma', {})
    L('| 均线 | 值 | 价格位置 | 偏离度 |')
    L('|------|-----|---------|--------|')
    for k in ['EMA5', 'EMA10', 'EMA20', 'EMA50', 'EMA60', 'EMA100', 'EMA200']:
        if k in ema_data:
            v = ema_data[k]; pos_info = pv.get(k, {})
            pos = pos_info.get('position', '-'); pct = pos_info.get('pct', 0)
            L(f'| {k} | {v} | {pos} | {pct:+.2f}% |')
    L(f'**均线排列: {result.get("ma_alignment", "N/A")}**')
    L('')
    if result.get('trend_strength'):
        L('### 趋势强度')
        L('')
        ts = result['trend_strength']
        L(f'- 方向: **{ts["direction"]}** | 强度: **{ts["strength"]}**')
        L(f'- 偏离MA{ts["ma_period"]}: {ts["deviation_pct"]:+.2f}%')
        L(f'- 10日斜率: {ts["slope_10d"]:+.2f}%')
        L('')
    L('## 三、MACD (12,26,9)')
    L('')
    macd = result.get('macd', {})
    L(f'- DIF: {macd.get("DIF", "N/A")}')
    L(f'- DEA: {macd.get("DEA", "N/A")}')
    L(f'- MACD柱: {macd.get("MACD_hist", "N/A")}')
    L(f'- 信号: **{macd.get("signal", "N/A")}**')
    if macd.get('trend'):
        L(''); L('近期趋势:')
        for t in macd['trend']:
            L(f'  DIF={t["DIF"]}, DEA={t["DEA"]}, 柱={t["hist"]}')
    L('')
    if result.get('kdj'):
        L('## 四、KDJ (9,3,3)')
        L('')
        kdj = result['kdj']
        L(f'- K: {kdj["K"]}, D: {kdj["D"]}, J: {kdj["J"]}')
        L(f'- 信号: **{kdj.get("signal", "N/A")}** | 区域: {kdj.get("zone", "N/A")}')
        L('')
    if result.get('stoch'):
        L('## 五、Stochastic (14,3,3)')
        L('')
        stoch = result['stoch']
        L(f'- SlowK: {stoch.get("SlowK", "N/A")}, SlowD: {stoch.get("SlowD", "N/A")}')
        L(f'- 区域: {stoch.get("zone", "N/A")}')
        L('')
    if result.get('bollinger'):
        L('## 六、布林带 (20,2)')
        L('')
        boll = result['bollinger']
        L(f'- 上轨: {boll["upper"]}')
        L(f'- 中轨: {boll.get("ma20") or boll.get("middle", "-")}')
        L(f'- 下轨: {boll["lower"]}')
        L(f'- %B: {boll["percent_b"]}%')
        L(f'- 带宽: {boll["bandwidth"]}%')
        L(f'- 位置: **{boll["position"]}**')
        L('')
    if result.get('atr'):
        L('## 七、ATR (14) 波动率')
        L('')
        atr = result['atr']
        L(f'- ATR: {atr["value"]}'); L(f'- 占价格比: {atr["pct_of_price"]}%')
        L('')
    if result.get('cci'):
        L('## 八、CCI (14)')
        L('')
        L(f'- CCI: {result["cci"]["value"]} | 区域: {result["cci"]["zone"]}')
        L('')
    if result.get('williams_r'):
        L('## 九、Williams %R (14)')
        L('')
        L(f'- %R: {result["williams_r"]["value"]} | 区域: {result["williams_r"]["zone"]}')
        L('')
    if result.get('adx'):
        L('## 十、ADX (14) 趋势强度')
        L('')
        adx = result['adx']
        L(f'- ADX: {adx["value"]} | 趋势: **{adx["trend_strength"]}**')
        L(f'- +DI: {adx.get("plus_di", "N/A")} | -DI: {adx.get("minus_di", "N/A")}')
        L(f'- 方向: **{adx.get("direction", "N/A")}**')
        L('')
    if result.get('mfi'):
        L('## 十一、MFI (14) 资金流量指数')
        L('')
        L(f'- MFI: {result["mfi"]["value"]} | 区域: **{result["mfi"]["zone"]}**')
        L('')
    if result.get('obv'):
        L('## 十二、OBV 能量潮')
        L('')
        obv = result['obv']
        L(f'- OBV: {obv["value"]:,}')
        L(f'- 5日均: {obv["ma5"]:,}'); L(f'- 10日均: {obv["ma10"]:,}')
        L(f'- 趋势: **{obv["trend"]}**')
        L('')
    if result.get('volume'):
        L('## 十三、成交量')
        L('')
        vol = result['volume']
        L(f'- 当日: {vol["current"]:,}')
        L(f'- 5日均量: {vol["ma5"]:,}'); L(f'- 量比: {vol["ratio"]}')
        L('')
    if result.get('volume_price'):
        L('### 量价关系')
        L('')
        vp = result['volume_price']
        L(f'- 形态: **{vp["pattern"]}**')
        L(f'- 20日价格变化: {vp["price_change_20d"]:+.2f}%')
        L(f'- 20日量变化: {vp["volume_change_20d"]:+.2f}%')
        L(f'- 5日/20日均量比: {vp["vol_ratio_5vs20"]}')
        L('')
    if result.get('rsi_divergence'):
        L('## 十四、RSI 背离')
        L('')
        div = result['rsi_divergence']
        if div.get('bullish'):
            b = div['bullish']
            L(f'- **底背离(看涨)**: 价格 {b["price_low1"]}→{b["price_low2"]}(新低), RSI {b["rsi_low1"]}→{b["rsi_low2"]}(未新低)')
        if div.get('bearish'):
            br = div['bearish']
            L(f'- **顶背离(看跌)**: 价格 {br["price_high1"]}→{br["price_high2"]}(新高), RSI {br["rsi_high1"]}→{br["rsi_high2"]}(未新高)')
        L('')
    L('## 十五、关键价位')
    L('')
    sr = result.get('support_resistance', {})
    L(f'- 波段高: {sr.get("swing_high", "N/A")}')
    L(f'- 波段低: {sr.get("swing_low", "N/A")}')
    L(f'- 波幅: {sr.get("range_pct", "N/A")}%')
    if result.get('fibonacci'):
        L(''); L('**斐波那契回撤位:**')
        fib = result['fibonacci']
        L(f'- 23.6%: {fib["23.6%"]}'); L(f'- 38.2%: {fib["38.2%"]}')
        L(f'- 50.0%: {fib["50.0%"]}'); L(f'- 61.8%: {fib["61.8%"]}')
        L(f'- 78.6%: {fib["78.6%"]}')
    L('')
    if result.get('auto_sr'):
        auto = result['auto_sr']
        if auto.get('supports'):
            L(f'**自动识别支撑位:** {", ".join(str(s) for s in auto["supports"])}')
        if auto.get('resistances'):
            L(f'**自动识别阻力位:** {", ".join(str(r) for r in auto["resistances"])}')
        L('')
    L('## 十六、综合信号')
    L('')
    sig = result.get('signal_summary', {})
    L(f'**多空比: {sig.get("bull", 0)} : {sig.get("bear", 0)}**')
    L(f'**综合判断: {sig.get("overall", "N/A")}**')
    L('')
    if sig.get('details'):
        L('信号明细:')
        for s in sig['details']:
            L(f'- {s}')
    L('')
    L('---')
    L('*免责声明: 基于历史数据的技术指标计算，不构成投资建议。*')
    return '\n'.join(lines)


def build_dashboard_bollinger(ta_data, current_rsi=50):
    """Build dashboard fields without changing the analysis price basis."""
    boll = ta_data.get('bollinger') or {}
    if not boll:
        return None
    price = boll.get('current_price')
    lower = boll.get('lower')
    upper = boll.get('upper')
    middle = boll.get('ma20') or boll.get('middle')
    if any(v is None for v in (price, lower, upper, middle)):
        return None
    width = upper - lower
    percent_b = (price - lower) / width * 100 if width else 50.0
    position = boll.get('position', '')
    if '触及下轨' in position and current_rsi < 35:
        signal = '强烈买入'
    elif '触及下轨' in position and current_rsi < 40:
        signal = '买入'
    elif '触及上轨' in position and current_rsi > 65:
        signal = '强烈卖出'
    elif '触及上轨' in position and current_rsi > 60:
        signal = '卖出'
    elif '下轨' in position or '中轨下方' in position:
        signal = '偏弱'
    elif '上轨' in position or '中轨上方' in position:
        signal = '偏强'
    else:
        signal = '中性'
    return {
        'ma20': round(middle, 4),
        'upper': round(upper, 4),
        'lower': round(lower, 4),
        'current_price': round(price, 4),
        'percent_b': round(percent_b, 1),
        'bandwidth': round(width / middle * 100, 2) if middle else 0,
        'dist_to_lower': round((price - lower) / lower * 100, 2) if lower else 0,
        'dist_to_upper': round((price - upper) / upper * 100, 2) if upper else 0,
        'position': position,
        'signal': signal,
        'period': 20,
        'price_basis': (ta_data.get('data_quality') or {}).get('price_basis', 'unknown'),
        'series': boll.get('series'),
    }

