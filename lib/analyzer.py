#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSI 分析器 - 核心分析逻辑"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime

# 兼容直接运行和模块导入
try:
    from .data_fetcher import detect_type, fetch_data
except ImportError:
    from data_fetcher import detect_type, fetch_data


class RSIAnalyzer:
    """RSI 分析器"""

    def __init__(self, symbol):
        self.symbol = symbol.strip().upper()
        self.data_type, self.symbol = detect_type(self.symbol)
        self.type_labels = {
            'us_stock': '美股',
            'cn_stock': 'A股',
            'cn_fund': 'A股基金',
            'hk_fund': '香港基金',
            'private_fund': '私募基金'
        }
        # 保留原始 df 用于生成图表
        self._df = None
        self._price_col = None

    def analyze(self, fetched=None):
        """执行完整分析"""
        # 批量任务传入同一份快照，确保 RSI 与技术指标使用同一截止日的数据。
        df, price_col, asset_name = fetched or fetch_data(self.symbol, self.data_type)
        if df is None:
            return None

        # 校验数据量：RSI(14) 至少需要 15 条数据
        valid_rsi = df[df['RSI_14'].notna()]
        if len(valid_rsi) < 1:
            print(f"[错误] {self.symbol} 有效 RSI 数据不足（需要至少 15 条历史数据）", file=sys.stderr)
            return None

        # 保留引用，供 save_files 时生成图表
        self._df = df
        self._price_col = price_col

        # 获取最新数据
        latest = df[df['RSI_14'].notna()].iloc[-1]
        cur_rsi = latest['RSI_14']
        cur_price = latest[price_col]

        # 当日涨跌幅（展示用：基于累计净值，避免分红除息跳跌）
        display_nav = None
        cumulative_nav = None
        display_daily_change = None
        if self.data_type in ('cn_fund', 'hk_fund', 'cn_auto', 'private_fund') and 'unit_nav' in df.columns:
            display_nav = round(float(latest['unit_nav']), 4)
        if self.data_type in ('cn_fund', 'hk_fund', 'cn_auto', 'private_fund') and 'acc_nav' in df.columns:
            cumulative_nav = round(float(latest['acc_nav']), 4)
        if 'adj_nav' in df.columns:
            valid_df = df[df['RSI_14'].notna()]
            if len(valid_df) >= 2:
                prev_adj = float(valid_df.iloc[-2]['adj_nav'])
                cur_adj = float(latest['adj_nav'])
                if prev_adj and prev_adj > 0:
                    display_daily_change = round((cur_adj - prev_adj) / prev_adj * 100, 2)
        elif self.data_type in ('cn_fund', 'hk_fund', 'cn_auto', 'private_fund') and 'unit_nav' in df.columns:
            valid_df = df[df['RSI_14'].notna()]
            if len(valid_df) >= 2:
                prev_unit = float(valid_df.iloc[-2]['unit_nav'])
                cur_unit = float(latest['unit_nav'])
                if prev_unit and prev_unit > 0:
                    display_daily_change = round((cur_unit - prev_unit) / prev_unit * 100, 2)

        # 当日涨跌幅（RSI/回测用：基于累计净值）
        daily_change = None
        if 'daily_change' in df.columns:
            daily_change = latest.get('daily_change')
            if daily_change is not None and (isinstance(daily_change, float) or hasattr(daily_change, 'item')):
                daily_change = round(float(daily_change), 2)
        if daily_change is None and len(df) >= 2:
            prev_price = df[df['RSI_14'].notna()].iloc[-2][price_col]
            if prev_price and prev_price > 0:
                daily_change = round((cur_price - prev_price) / prev_price * 100, 2)

        # 最近 7 天 RSI 分位
        recent_rsi = self._calc_recent_rsi_percentile(df)

        # RSI 分布统计
        stats = self._analyze_distribution(df, cur_rsi)

        # 极值点
        extremes = self._find_extremes(df, price_col)

        # 回测（超卖 + 超买）
        backtest_results = self._backtest(df, price_col)

        # 布林带计算：统一使用 price_col (adj_nav)，避免分红日 unit_nav 跳跌导致布林带失真
        boll_price_col = price_col
        bollinger = self._calc_bollinger(df, boll_price_col)

        # 状态判断
        status, suggestion = self._get_status_suggestion(cur_rsi)

        # 计算基金成立时长（基于净值数据第一天）
        first_date = df['date'].min()
        latest_date = df['date'].max()
        days_diff = (latest_date - first_date).days
        fund_years = round(days_diff / 365.25, 1)

        result = {
            'symbol': self.symbol,
            'asset_name': asset_name,
            'data_type': self.data_type,
            'data_type_label': self.type_labels.get(self.data_type, '未知'),
            'total_records': len(df),
            'date_range': {
                'start': first_date.strftime('%Y-%m-%d'),
                'end': latest_date.strftime('%Y-%m-%d')
            },
            'fund_years': fund_years,
            'data_quality': {
                'data_source': df.attrs.get('data_source', 'unknown'),
                'price_basis': df.attrs.get('price_basis', price_col),
                'as_of': latest_date.strftime('%Y-%m-%d'),
                'latest_verified': df.attrs.get('latest_verified'),
                'expected_records': df.attrs.get('reference_total_count') or df.attrs.get('expected_records'),
                'parsed_records': len(df),
                'max_gap_days': df.attrs.get('max_gap_days'),
                'analysis_start_override': df.attrs.get('analysis_start_override'),
                'source_history_start': df.attrs.get('source_history_start'),
                'source_history_records': df.attrs.get('source_history_records'),
            },
            'latest': {
                'date': latest['date'].strftime('%Y-%m-%d'),
                'price': round(cur_price, 4),
                'display_nav': display_nav,
                'cumulative_nav': cumulative_nav,
                'display_daily_change': display_daily_change,
                'rsi': round(cur_rsi, 1),
                'rsi_7': round(latest.get('RSI_7', 0), 1),
                'percentile': stats['current_percentile'],
                'status': status,
                'suggestion': suggestion,
                'daily_change': daily_change,
            },
            'recent_rsi': recent_rsi,
            'stats': stats,
            'extremes': extremes,
            'backtest': backtest_results,
            'bollinger': bollinger
        }

        # 只有美股才计算 predict
        if self.data_type == 'us_stock':
            prices = df[price_col].dropna().tolist()
            predict_results = self._predict(prices, cur_price, cur_rsi, stats)
            result['predict'] = predict_results

        # 移除 rsi_series，无法 JSON 序列化
        stats.pop('rsi_series', None)

        # v2.0: 多时间框架 RSI 分析
        result['multi_tf_rsi'] = self._multi_timeframe_rsi(df, price_col)

        # v2.0: 增强回测（含滚动窗口回测）
        result['rolling_backtest'] = self._rolling_backtest(df, price_col)

        # v3.0: 周线RSI（仅展示参考，不含回测）
        result['weekly_rsi'] = self._weekly_rsi(df, price_col)

        return result

    def _calc_bollinger(self, df, price_col, period=20, std_dev=2):
        """计算布林带指标"""
        valid = df[df[price_col].notna()].copy()
        if len(valid) < period:
            return None

        # 计算中轨(MA20)、上轨、下轨
        valid['ma20'] = valid[price_col].rolling(window=period).mean()
        # 与全面技术分析/TA-Lib 口径一致：窗口总体标准差 (ddof=0)。
        valid['std20'] = valid[price_col].rolling(window=period).std(ddof=0)
        valid['upper'] = valid['ma20'] + std_dev * valid['std20']
        valid['lower'] = valid['ma20'] - std_dev * valid['std20']

        # 最新值
        latest = valid.iloc[-1]
        cur_price = latest[price_col]
        ma20 = latest['ma20']
        upper = latest['upper']
        lower = latest['lower']

        # %B位置: (当前-下轨)/(上轨-下轨), 0=下轨, 0.5=中轨, 1=上轨
        if upper != lower:
            percent_b = (cur_price - lower) / (upper - lower)
        else:
            percent_b = 0.5

        # 带宽: (上轨-下轨)/中轨
        bandwidth = (upper - lower) / ma20 if ma20 != 0 else 0

        # 距离上下轨的百分比
        dist_to_lower = (cur_price - lower) / lower * 100 if lower != 0 else 0
        dist_to_upper = (cur_price - upper) / upper * 100 if upper != 0 else 0

        # 位置状态
        if cur_price <= lower:
            position = '触及下轨'
        elif cur_price >= upper:
            position = '触及上轨'
        elif cur_price < ma20:
            position = '中轨下方'
        elif cur_price > ma20:
            position = '中轨上方'
        else:
            position = '中轨'

        # 结合RSI的信号
        cur_rsi = latest.get('RSI_14', 50)
        if cur_price <= lower and cur_rsi < 35:
            signal = '强烈买入'
        elif cur_price <= lower and cur_rsi < 40:
            signal = '买入'
        elif cur_price >= upper and cur_rsi > 65:
            signal = '强烈卖出'
        elif cur_price >= upper and cur_rsi > 60:
            signal = '卖出'
        elif cur_price < ma20:
            signal = '偏弱'
        else:
            signal = '中性'

        return {
            'ma20': round(ma20, 4),
            'upper': round(upper, 4),
            'lower': round(lower, 4),
            'current_price': round(cur_price, 4),
            'percent_b': round(percent_b * 100, 1),  # 转为0-100%
            'bandwidth': round(bandwidth * 100, 2),  # 带宽百分比
            'dist_to_lower': round(dist_to_lower, 2),
            'dist_to_upper': round(dist_to_upper, 2),
            'position': position,
            'signal': signal,
            'period': period
        }

    def _calc_recent_rsi_percentile(self, df, days=14):
        """计算最近 N 天每天的 RSI 及其历史分位"""
        rsi_col = 'RSI_14'
        valid = df[df[rsi_col].notna()].copy()
        total = len(valid)
        if total == 0:
            return []

        recent = valid.tail(days)
        result = []
        prev_price = None
        for _, row in recent.iterrows():
            rsi_val = row[rsi_col]
            pct = round((valid[rsi_col] <= rsi_val).sum() / total * 100, 1)
            # 计算当日涨跌幅（基金基于累计净值，避免分红除息导致虚假跳跌）
            daily_chg = None
            cur_price = None
            if 'adj_nav' in row.index and row['adj_nav'] is not None and not pd.isna(row['adj_nav']):
                cur_price = float(row['adj_nav'])
            elif 'acc_nav' in row.index and row['acc_nav'] is not None and not pd.isna(row['acc_nav']):
                cur_price = float(row['acc_nav'])
            elif 'price' in row.index and row['price'] is not None and not pd.isna(row['price']):
                cur_price = float(row['price'])
            if cur_price is not None:
                if prev_price is not None and prev_price > 0:
                    daily_chg = round((cur_price - prev_price) / prev_price * 100, 2)
                prev_price = cur_price
            entry = {
                'date': row['date'].strftime('%Y-%m-%d'),
                'rsi': round(rsi_val, 1),
                'percentile': pct,
            }
            if daily_chg is not None:
                entry['daily_change'] = daily_chg
            result.append(entry)
        return result

    def _analyze_distribution(self, df, cur_rsi):
        """RSI 分布统计"""
        rsi_col = 'RSI_14'
        rsi_series = df[df[rsi_col].notna()][rsi_col]
        total = len(rsi_series)

        if total == 0:
            return {
                'mean': 0, 'median': 0, 'min': 0, 'max': 0,
                'total': 0, 'oversold_pct': 0, 'overbought_pct': 0,
                'percentile_values': {}, 'current_percentile': 0,
                'distribution': [], 'rsi_series': rsi_series,
            }

        # 分布
        bins = list(range(0, 105, 5))
        labels = [f'{i}-{i+5}' for i in range(0, 100, 5)]
        rsi_binned = pd.cut(rsi_series, bins=bins, labels=labels, include_lowest=True)
        distribution = rsi_binned.value_counts().sort_index()

        # 分位值 - 改成 5% 为单位
        percentiles = list(range(5, 100, 5))  # 5%, 10%, 15%, ..., 95%
        percentile_values = {p: round(np.percentile(rsi_series, p), 1) for p in percentiles}

        # 当前分位
        current_percentile = round((rsi_series <= cur_rsi).sum() / total * 100, 1)

        # 分布详情
        distribution_detail = []
        for label in labels:
            count = distribution.get(label, 0)
            if count > 0:
                distribution_detail.append({
                    'range': label,
                    'count': int(count),
                    'percent': round(count / total * 100, 1)
                })

        return {
            'mean': round(rsi_series.mean(), 1),
            'median': round(rsi_series.median(), 1),
            'min': round(rsi_series.min(), 1),
            'max': round(rsi_series.max(), 1),
            'total': total,
            'oversold_pct': round((rsi_series <= 30).sum() / total * 100, 1),
            'overbought_pct': round((rsi_series >= 70).sum() / total * 100, 1),
            'percentile_values': percentile_values,
            'current_percentile': current_percentile,
            'distribution': distribution_detail,
            'rsi_series': rsi_series  # 保留用于 predict
        }

    def _find_extremes(self, df, price_col, top_n=10):
        """找出 RSI 极值点"""
        rsi_col = 'RSI_14'
        valid = df[df[rsi_col].notna()].copy()
        lowest = valid.nsmallest(top_n, rsi_col)

        extremes = []
        for _, row in lowest.iterrows():
            item = {
                'date': row['date'].strftime('%Y-%m-%d'),
                'rsi': round(row[rsi_col], 1),
                'price': round(row[price_col], 4),
            }
            for days in [30, 60, 90]:
                future = df[df['date'] > row['date']].head(days)
                ret = None
                # 只有未来数据真正满 days 个交易日，才算该持有期收益；
                # 不足（极值点距今太近，未来收益尚未产生）则留 None(显示 N/A)，
                # 避免用部分数据冒充完整持有期收益误导判断。
                if len(future) >= days:
                    ret = round((future[price_col].iloc[-1] - row[price_col]) / row[price_col] * 100, 1)
                item[f'return_{days}d'] = ret
            extremes.append(item)

        return extremes

    def _backtest(self, df, price_col):
        """多阈值回测（超卖抄底 + 超买卖出）"""
        rsi_col = 'RSI_14'
        valid = df[df[rsi_col].notna()].copy()

        # 超卖回测：RSI <= threshold 时买入
        oversold_results = {}
        for threshold in [40, 35, 30, 25, 22]:
            oversold_results[threshold] = {}
            for hold_days in [30, 60, 90]:
                mask = valid[rsi_col] <= threshold
                signals = valid[mask & ~mask.shift(fill_value=False)]
                profits = []
                drawdowns = []
                for _, row in signals.iterrows():
                    future = df[df['date'] > row['date']].head(hold_days)
                    if len(future) == hold_days:
                        buy_price = row[price_col]
                        profits.append((future[price_col].iloc[-1] - buy_price) / buy_price * 100)
                        # 持有期间最大回撤：相对买入价的最低点
                        min_price = future[price_col].min()
                        drawdowns.append((min_price - buy_price) / buy_price * 100)

                if profits:
                    wins = [p for p in profits if p > 0]
                    oversold_results[threshold][hold_days] = {
                        'signals': len(profits),
                        'win_rate': round(len(wins) / len(profits) * 100, 1),
                        'avg_profit': round(np.mean(profits), 1),
                        'max_profit': round(max(profits), 1),
                        'max_loss': round(min(profits), 1),
                        'avg_drawdown': round(np.mean(drawdowns), 1),
                        'max_drawdown': round(min(drawdowns), 1),
                    }

        # 超买回测：RSI >= threshold 时卖出（观察后续跌幅）
        overbought_results = {}
        for threshold in [60, 65, 70, 75, 80]:
            overbought_results[threshold] = {}
            for hold_days in [5, 10, 20, 30]:
                mask = valid[rsi_col] >= threshold
                signals = valid[mask & ~mask.shift(fill_value=False)]
                returns = []
                drawdowns = []
                for _, row in signals.iterrows():
                    future = df[df['date'] > row['date']].head(hold_days)
                    if len(future) == hold_days:
                        buy_price = row[price_col]
                        ret = (future[price_col].iloc[-1] - buy_price) / buy_price * 100
                        returns.append(ret)
                        # 持有期间最大回撤
                        min_price = future[price_col].min()
                        drawdowns.append((min_price - buy_price) / buy_price * 100)

                if returns:
                    drops = [r for r in returns if r < 0]  # 回撤
                    overbought_results[threshold][hold_days] = {
                        'signals': len(returns),
                        'drop_rate': round(len(drops) / len(returns) * 100, 1),  # 回撤概率
                        'avg_return': round(np.mean(returns), 1),
                        'max_rise': round(max(returns), 1),
                        'max_drop': round(min(returns), 1),
                        'avg_drop': round(np.mean(drops), 1) if drops else 0,  # 平均回撤幅度
                        'avg_drawdown': round(np.mean(drawdowns), 1),
                        'max_drawdown': round(min(drawdowns), 1),
                    }

        return {'oversold': oversold_results, 'overbought': overbought_results}

    def _predict(self, prices, cur_price, cur_rsi, stats):
        """目标价位预测 - Sell Put 期权策略辅助"""
        period = 14

        # 提取 Wilder 状态
        s = pd.Series(prices)
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.iloc[1:period+1].mean()
        avg_loss = loss.iloc[1:period+1].mean()

        for i in range(period+1, len(prices)):
            avg_gain = (avg_gain * (period-1) + gain.iloc[i]) / period
            avg_loss = (avg_loss * (period-1) + loss.iloc[i]) / period

        def calc_rsi(ag, al):
            if al == 0:
                return 100.0
            return 100 - 100 / (1 + ag / al)

        def simulate_decline(target_rsi, days):
            """模拟连续等比例下跌 N 天后 RSI 达到目标值"""
            lo, hi = 0.0, 0.50
            for _ in range(200):
                mid = (lo + hi) / 2
                g, l, p = avg_gain, avg_loss, cur_price
                for _ in range(days):
                    drop = p * mid
                    p -= drop
                    g = (g * (period-1)) / period
                    l = (l * (period-1) + drop) / period
                if calc_rsi(g, l) > target_rsi:
                    lo = mid
                else:
                    hi = mid

            # 最终模拟
            g, l, p = avg_gain, avg_loss, cur_price
            for _ in range(days):
                drop = p * lo
                p -= drop
                g = (g * (period-1)) / period
                l = (l * (period-1) + drop) / period

            return {
                'price': round(p, 2),
                'daily_drop': round(lo * 100, 2),
                'total_drop': round((cur_price - p) / cur_price * 100, 1)
            }

        # 目标 RSI
        all_targets = [35, 30, 25, 22, 20, 15]
        targets = [t for t in all_targets if t < cur_rsi]
        if not targets:
            targets = all_targets

        # 历史频率
        rsi_series = stats['rsi_series']
        total_n = len(rsi_series)

        predict_results = {
            'avg_gain': round(avg_gain, 4),
            'avg_loss': round(avg_loss, 4),
            'targets': {}
        }

        for t in targets:
            cnt = (rsi_series <= t).sum()
            hist_pct = round(cnt / total_n * 100, 1)
            safe_pct = round(100 - hist_pct, 0)

            scenarios = {}
            for d in [1, 3, 5, 10, 20]:
                scenarios[d] = simulate_decline(t, d)

            predict_results['targets'][t] = {
                'hist_count': int(cnt),
                'hist_pct': hist_pct,
                'safe_pct': safe_pct,
                'scenarios': scenarios
            }

        return predict_results

    def _get_status_suggestion(self, cur_rsi):
        """获取状态判断和建议"""
        if cur_rsi >= 70:
            return "超买区（风险较高）", "谨慎追高，可考虑分批减仓"
        elif cur_rsi >= 50:
            return "强势区", "可继续持有，关注回调机会"
        elif cur_rsi >= 30:
            return "弱势区", "可开始关注，等待更好入场点"
        else:
            return "超卖区（机会较大）", "历史经验显示是较好抄底时机"


    def _multi_timeframe_rsi(self, df, price_col):
        """v2.0: 多时间框架 RSI 分析 (RSI7/RSI14/RSI28)"""
        rsi_cols = {'RSI_7': 7, 'RSI_14': 14}
        # 计算 RSI28
        if 'RSI_28' not in df.columns:
            from data_fetcher import calculate_rsi
            df = df.copy()
            df['RSI_28'] = calculate_rsi(df[price_col].tolist(), 28)
        rsi_cols['RSI_28'] = 28
        
        result = {}
        for col, period in rsi_cols.items():
            if col not in df.columns:
                continue
            valid = df[df[col].notna()]
            if len(valid) == 0:
                continue
            latest = valid.iloc[-1]
            cur = latest[col]
            total = len(valid)
            pct = round((valid[col] <= cur).sum() / total * 100, 1)
            
            # 超买超卖判断
            if cur < 25:
                zone = '极度超卖'
            elif cur < 30:
                zone = '超卖'
            elif cur > 75:
                zone = '极度超买'
            elif cur > 70:
                zone = '超买'
            elif cur > 50:
                zone = '偏强'
            else:
                zone = '偏弱'
            
            result[col] = {
                'period': period,
                'value': round(cur, 1),
                'percentile': pct,
                'zone': zone,
                'mean': round(valid[col].mean(), 1),
                'min': round(valid[col].min(), 1),
                'max': round(valid[col].max(), 1),
            }
        
        # 多时间框架一致性判断
        if len(result) >= 2:
            zones = [v['zone'] for v in result.values()]
            if all(z in ('超卖', '极度超卖') for z in zones):
                result['consensus'] = '多周期超卖共振 (强看涨)'
            elif all(z in ('超买', '极度超买') for z in zones):
                result['consensus'] = '多周期超买共振 (强看跌)'
            elif all(z in ('偏弱', '超卖', '极度超卖') for z in zones):
                result['consensus'] = '多周期偏弱 (看涨潜力)'
            elif all(z in ('偏强', '超买', '极度超买') for z in zones):
                result['consensus'] = '多周期偏强 (看跌风险)'
            else:
                result['consensus'] = '多周期不一致 (震荡)'
        
        return result

    def _weekly_rsi(self, df, price_col):
        """计算周线RSI(14)：日线数据 resample 成周线后算 Wilder RSI"""
        try:
            valid = df[df[price_col].notna()].copy()
            if len(valid) < 100:
                return None

            # resample 成周线（周一为一周起始），取收盘价
            valid = valid.set_index('date')
            weekly = valid[price_col].resample('W-FRI').last().dropna()
            if len(weekly) < 15:
                return None

            from data_fetcher import calculate_rsi
            weekly_rsi_list = calculate_rsi(weekly.tolist(), 14)
            weekly_rsi_series = pd.Series(weekly_rsi_list, index=weekly.index)
            valid_rsi = weekly_rsi_series.dropna()
            if len(valid_rsi) == 0:
                return None

            cur_rsi = valid_rsi.iloc[-1]
            total = len(valid_rsi)
            pct = round((valid_rsi <= cur_rsi).sum() / total * 100, 1)

            if cur_rsi < 25:
                zone = '极度超卖'
            elif cur_rsi < 30:
                zone = '超卖'
            elif cur_rsi > 75:
                zone = '极度超买'
            elif cur_rsi > 70:
                zone = '超买'
            elif cur_rsi > 50:
                zone = '偏强'
            else:
                zone = '偏弱'

            return {
                'value': round(cur_rsi, 1),
                'percentile': pct,
                'zone': zone,
                'mean': round(valid_rsi.mean(), 1),
                'min': round(valid_rsi.min(), 1),
                'max': round(valid_rsi.max(), 1),
                'total_weeks': total,
                'as_of': valid_rsi.index[-1].strftime('%Y-%m-%d'),
            }
        except Exception as e:
            print(f"[周线RSI] 计算失败: {e}", file=sys.stderr)
            return None

    def _rolling_backtest(self, df, price_col, window=60):
        """v2.0: 滚动窗口回测 - 评估不同RSI区间的近期表现"""
        rsi_col = 'RSI_14'
        valid = df[df[rsi_col].notna()].copy()
        total = len(valid)
        if total < window:
            return None
        
        # 只分析最近 window 天的数据
        recent = valid.tail(window)
        current_rsi = recent[rsi_col].iloc[-1]
        
        # 按RSI区间分组统计近期表现
        bins = [(0, 25, '极度超卖'), (25, 30, '超卖'), (30, 35, '接近超卖'),
                (35, 45, '偏弱'), (45, 55, '中性'), (55, 65, '偏强'),
                (65, 70, '接近超买'), (70, 80, '超买'), (80, 100, '极度超买')]
        
        result = {'window_days': window, 'current_rsi': round(current_rsi, 1)}
        for low, high, label in bins:
            group = recent[(recent[rsi_col] >= low) & (recent[rsi_col] < high)]
            if len(group) < 2:
                continue
            # 计算该区间出现后的5日平均收益
            returns = []
            for idx in group.index:
                pos = valid.index.get_loc(idx)
                if pos + 5 < total:
                    future = valid.iloc[pos+1:pos+6]
                    if len(future) == 5:
                        ret = (future[price_col].iloc[-1] / valid[price_col].iloc[pos] - 1) * 100
                        returns.append(ret)
            if returns:
                result[label] = {
                    'count': len(group),
                    'avg_5d_return': round(np.mean(returns), 2),
                    'win_rate': round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
                }
        
        return result

    def _make_table(self, headers, rows, col_widths=None):
        """生成 Markdown 表格"""
        header_row = '| ' + ' | '.join(headers) + ' |'
        separator = '| ' + ' | '.join(['---'] * len(headers)) + ' |'
        data_rows = []
        for row in rows:
            data_row = '| ' + ' | '.join(str(v) for v in row) + ' |'
            data_rows.append(data_row)
        return header_row + '\n' + separator + '\n' + '\n'.join(data_rows)

    def format_report(self, result):
        """生成格式化报告"""
        lines = []
        L = lines.append

        # 标题
        L(f"# {result['symbol']} RSI 指标分析报告")
        L("")

        # ========== 一、当前状态 ==========
        L("## 一、当前状态")
        L("")

        # 基金基本信息（非美股）
        if result['data_type'] == 'cn_stock':
            headers = ['指标', '数值']
            rows = [
                ['股票名称', f"**{result['asset_name']}**"],
                ['股票代码', result['symbol']],
                ['上市时长', f"约 **{result['fund_years']}** 年（数据起始：{result['date_range']['start']}）"],
                ['数据量', f"{result['total_records']} 个交易日"],
                ['最新日期', result['latest']['date']],
                ['当前价格', f"**{result['latest']['price']:.2f}**"],
                ['当前 RSI', f"**{result['latest']['rsi']}**"],
                ['RSI 历史分位', f"**{result['latest']['percentile']:.1f}%**（当前 RSI 高于历史上 {result['latest']['percentile']:.1f}% 的交易日）"],
                ['状态判断', result['latest']['status']],
            ]
            L(self._make_table(headers, rows))
        elif result['latest'].get('display_nav') is not None:
            headers = ['指标', '数值']
            rows = [
                ['基金名称', f"**{result['asset_name']}**"],
                ['基金代码', result['symbol']],
                ['成立时长', f"约 **{result['fund_years']}** 年（净值数据起始：{result['date_range']['start']}）"],
                ['数据量', f"{result['total_records']} 个交易日"],
                ['最新日期', result['latest']['date']],
                ['单位净值', f"**{result['latest'].get('display_nav', result['latest']['price']):.4f}**"],
                ['累计净值', f"**{result['latest']['cumulative_nav']:.4f}**" if result['latest'].get('cumulative_nav') is not None else '-'],
                ['当前 RSI', f"**{result['latest']['rsi']}**"],
                ['RSI 历史分位', f"**{result['latest']['percentile']:.1f}%**（当前 RSI 高于历史上 {result['latest']['percentile']:.1f}% 的交易日）"],
                ['状态判断', result['latest']['status']],
            ]
            L(self._make_table(headers, rows))
        else:
            headers = ['指标', '数值']
            rows = [
                ['最新日期', result['latest']['date']],
                ['最新净值', f"**{result['latest']['display_nav']:.4f}**" if result['latest'].get('display_nav') else f"**{result['latest']['price']:.4f}**"],
                ['当前 RSI', f"**{result['latest']['rsi']}**"],
                ['RSI 历史分位', f"**{result['latest']['percentile']:.1f}%**（当前 RSI 高于历史上 {result['latest']['percentile']:.1f}% 的交易日）"],
                ['状态判断', result['latest']['status']],
            ]
            L(self._make_table(headers, rows))
        L("")
        L(f"> **建议：{result['latest']['suggestion']}**")
        L("")

        # ========== 1.5、RSI 历史统计 ==========
        L("### RSI 历史统计")
        L("")
        stats = result['stats']
        headers = ['统计项', 'RSI(14) 值']
        rows = [
            ['平均值', f"**{stats['mean']}**"],
            ['中位值', f"**{stats['median']}**"],
            ['最小值', f"**{stats['min']}**"],
            ['最大值', f"**{stats['max']}**"],
            ['超卖占比（≤30）', f"{stats['oversold_pct']}%"],
            ['超买占比（≥70）', f"{stats['overbought_pct']}%"],
            ['样本数', f"{stats['total']} 个交易日"],
        ]
        L(self._make_table(headers, rows))
        L("")

        # ========== 二、RSI 分位值对照表 ==========
        L("## 二、RSI 分位值对照表")
        L("")
        headers = ['分位', 'RSI 值', '说明']
        pv = result['stats']['percentile_values']
        cur_rsi = result['latest']['rsi']
        rows = []
        for p in range(5, 100, 5):
            v = pv.get(p, 0)
            if p <= 10:
                desc = f"极度超卖，仅{p}%时间低于此"
            elif p <= 20:
                desc = "深度超卖"
            elif p <= 30:
                desc = "超卖线"
            elif p <= 40:
                desc = "偏低"
            elif p <= 50:
                desc = "多空分界" if p == 50 else "偏低"
            elif p <= 60:
                desc = "偏高"
            elif p <= 70:
                desc = "超买线"
            elif p <= 80:
                desc = "深度超买"
            else:
                desc = f"极度超卖，仅{100-p}%时间高于此"
            mark = " ← **当前位置**" if abs(v - cur_rsi) < 2 else ""
            rows.append([f"{p}%", f"{v:.1f}", desc + mark])
        L(self._make_table(headers, rows))
        L("")

        # ========== 三、分布详情 + ASCII 柱状图 ==========
        L("## 三、分布详情")
        L("")
        headers = ['区间', '次数', '占比', '分布']
        rows = []
        for d in result['stats']['distribution']:
            pct = d['percent']
            bar_len = max(1, int(pct / 1.5))
            rsi_low = int(d['range'].split('-')[0])
            if rsi_low < 30:
                bar = '▓' * bar_len
            elif rsi_low >= 70:
                bar = '▓' * bar_len
            else:
                bar = '░' * bar_len
            rows.append([d['range'], str(d['count']), f"{d['percent']:.1f}%", bar])
        L(self._make_table(headers, rows))
        L("")
        L("> ▓ = 超买/超卖区  ░ = 正常区间")
        L("")

        # ========== 四、抄底策略回测 ==========
        L("## 四、抄底策略回测")
        L("")
        L("> 策略：当 RSI 低于阈值时买入，持有指定天数后卖出")
        L("")

        for threshold in [40, 35, 30, 25, 22]:
            bt_oversold = result['backtest']['oversold']
            if threshold in bt_oversold and bt_oversold[threshold]:
                L(f"### RSI ≤ {threshold}")
                L("")
                headers = ['持有天数', '信号次数', '胜率', '平均收益', '最大盈利', '最大亏损', '平均回撤', '最大回撤']
                rows = []
                for hold_days in [30, 60, 90]:
                    if hold_days in bt_oversold[threshold]:
                        r = bt_oversold[threshold][hold_days]
                        rows.append([
                            f"{hold_days}天",
                            str(r['signals']),
                            f"{r['win_rate']:.1f}%",
                            f"{r['avg_profit']:+.1f}%",
                            f"{r['max_profit']:+.1f}%",
                            f"{r['max_loss']:+.1f}%",
                            f"{r['avg_drawdown']:+.1f}%",
                            f"{r['max_drawdown']:+.1f}%"
                        ])
                L(self._make_table(headers, rows))
                L("")

        L("> **最大亏损**：持有到期卖出时的实际最大亏损 | **平均/最大回撤**：持有期间相对买入价的最低浮亏（即使到期涨回来，中间可能经历的幅度）")
        L("")

        # ========== 4.5、止盈策略回测 ==========
        L("## 五、止盈策略回测")
        L("")
        L("> 策略：当 RSI 高于阈值时已持仓，观察后续 N 天的回撤情况")
        L("")

        bt_overbought = result['backtest']['overbought']
        for threshold in [60, 65, 70, 75, 80]:
            if threshold in bt_overbought and bt_overbought[threshold]:
                L(f"### RSI ≥ {threshold}")
                L("")
                headers = ['持有天数', '信号次数', '回撤概率', '平均收益', '平均回撤', '最大上涨', '最大下跌', '期间最大回撤']
                rows = []
                for hold_days in [5, 10, 20, 30]:
                    if hold_days in bt_overbought[threshold]:
                        r = bt_overbought[threshold][hold_days]
                        rows.append([
                            f"{hold_days}天",
                            str(r['signals']),
                            f"{r['drop_rate']:.1f}%",
                            f"{r['avg_return']:+.1f}%",
                            f"{r['avg_drop']:+.1f}%",
                            f"{r['max_rise']:+.1f}%",
                            f"{r['max_drop']:+.1f}%",
                            f"{r['max_drawdown']:+.1f}%"
                        ])
                L(self._make_table(headers, rows))
                L("")

        # ========== 止盈快速参考 ==========
        L("### 【止盈快速参考】")
        L("")
        headers = ['RSI 阈值', '10天回撤概率', '10天平均收益', '20天回撤概率', '20天平均收益', '建议']
        rows = []
        for threshold in [60, 65, 70, 75, 80]:
            if threshold in bt_overbought:
                r10 = bt_overbought[threshold].get(10, {})
                r20 = bt_overbought[threshold].get(20, {})
                if r10 and r20:
                    if r10['drop_rate'] >= 70:
                        grade = "建议减仓"
                    elif r10['drop_rate'] >= 60:
                        grade = "可考虑止盈"
                    elif r10['drop_rate'] >= 50:
                        grade = "开始关注"
                    else:
                        grade = "可继续持有"
                    rows.append([
                        f"≥ {threshold}",
                        f"{r10['drop_rate']:.1f}%",
                        f"{r10['avg_return']:+.1f}%",
                        f"{r20['drop_rate']:.1f}%",
                        f"{r20['avg_return']:+.1f}%",
                        grade
                    ])
        L(self._make_table(headers, rows))
        L("")

        # ========== 六、历史最佳抄底点 TOP 10 ==========
        L("## 六、历史最佳抄底点 TOP 10")
        L("")
        headers = ['排名', '日期', 'RSI', '价格', '30天收益', '60天收益', '90天收益']
        rows = []
        for i, e in enumerate(result['extremes'], 1):
            ret30 = f"{e['return_30d']:+.1f}%" if e.get('return_30d') is not None else "N/A"
            ret60 = f"{e['return_60d']:+.1f}%" if e.get('return_60d') is not None else "N/A"
            ret90 = f"{e['return_90d']:+.1f}%" if e.get('return_90d') is not None else "N/A"
            rows.append([str(i), e['date'], f"{e['rsi']:.1f}", f"{e['price']:.4f}", ret30, ret60, ret90])
        L(self._make_table(headers, rows))
        L("")

        # ========== 七、目标价位预测（仅美股）==========
        if 'predict' in result:
            predict = result['predict']
            L("## 七、Sell Put 目标价位预测")
            L("")
            L(f"基于 RSI(14)={cur_rsi:.1f} 模拟持续下跌场景，预测各目标 RSI 对应的价位")
            L(f"- avg_gain / avg_loss: `{predict['avg_gain']:.4f} / {predict['avg_loss']:.4f}`")
            L("")

            for t, data in predict['targets'].items():
                L(f"### RSI → {t}（历史触发 {data['hist_pct']:.1f}% / 安全概率 {data['safe_pct']:.0f}%）")
                L("")
                headers = ['持续下跌', '目标价格', '每日跌幅', '总跌幅']
                rows = []
                for d in [1, 3, 5, 10, 20]:
                    s = data['scenarios'][d]
                    rows.append([f"{d}天", f"${s['price']:.2f}", f"{s['daily_drop']:.2f}%", f"{s['total_drop']:.1f}%"])
                L(self._make_table(headers, rows))
                L("")

            # 快速参考表
            L("### 【Sell Put 快速参考表】")
            L("")
            headers = ['目标RSI', '历史概率', '安全概率', '5天暴跌价', '10天阴跌价', '20天慢跌价', '建议']
            rows = []
            for t, data in predict['targets'].items():
                safe = data['safe_pct']
                if safe >= 95:
                    grade = "极安全"
                elif safe >= 90:
                    grade = "很安全"
                elif safe >= 80:
                    grade = "较安全"
                elif safe >= 70:
                    grade = "一般"
                else:
                    grade = "需谨慎"
                s5 = data['scenarios'][5]
                s10 = data['scenarios'][10]
                s20 = data['scenarios'][20]
                rows.append([
                    str(t),
                    f"{data['hist_pct']:.1f}%",
                    f"{safe:.0f}%",
                    f"${s5['price']:.2f}",
                    f"${s10['price']:.2f}",
                    f"${s20['price']:.2f}",
                    grade
                ])
            L(self._make_table(headers, rows))
            L("")
            L("> • **5天暴跌价**: 连续5天大跌达到目标RSI（极端场景）")
            L("> • **10天阴跌价**: 连续10天阴跌达到目标RSI（较现实场景）")
            L("> • **20天慢跌价**: 连续20天缓跌达到目标RSI（最可能场景）")
            L("")

        # ========== 综合建议 ==========
        section_num = "八" if 'predict' in result else "七"
        L(f"## {section_num}、综合建议")
        L("")
        cur_rsi = result['latest']['rsi']
        percentile = result['latest']['percentile']

        if cur_rsi >= 60:
            L(f"当前 RSI({cur_rsi:.1f}) 处于中高位，历史分位 {percentile:.1f}%。")
            L("")
            L("**操作建议：**")
            L("- 当前不适合抄底，距超卖区有充足缓冲")
            if self.data_type == 'us_stock':
                L("- 可选 RSI 30~35 对应的价格区间做 Sell Put 行权价，安全边际大")
            else:
                L("- 等待 RSI 跌到 35 以下再考虑入场")
        elif cur_rsi >= 45:
            L(f"当前 RSI({cur_rsi:.1f}) 处于中性偏弱区域，历史分位 {percentile:.1f}%。")
            L("")
            L("**操作建议：**")
            L("- 现在可以开始关注，但还不是最佳入场点")
            L("- 理想抄底区间：RSI ≤ 30（历史胜率高）")
            if self.data_type == 'us_stock':
                L("- Sell Put 可选 RSI 25~30 对应的行权价，留出安全边际")
        elif cur_rsi >= 35:
            L(f"当前 RSI({cur_rsi:.1f}) 已进入弱势区，历史分位 {percentile:.1f}%。")
            L("")
            L("**操作建议：**")
            L("- 接近超卖区域，可以开始分批建仓")
            if self.data_type == 'us_stock':
                L("- Sell Put 选 RSI 20~25 对应的行权价，控制仓位")
        elif cur_rsi >= 25:
            L(f"当前 RSI({cur_rsi:.1f}) 接近超卖，历史分位 {percentile:.1f}%。")
            L("")
            L("**操作建议：**")
            L("- 历史上属于较好的支撑区域")
            L("- 抄底安全性较高，但需控制仓位")
        else:
            L(f"当前 RSI({cur_rsi:.1f}) 深度超卖，历史分位 {percentile:.1f}%。")
            L("")
            L("**操作建议：**")
            L("- 历史上极为罕见，风险收益比好")
            L("- 需防范极端行情持续，分批入场")

        L("")
        L("---")
        L("")
        L("⚠️ **风险提示：** 基于 RSI 历史统计，不构成投资建议。")

        return '\n'.join(lines)

    def save_files(self, result):
        """保存结果到文件"""
        result_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'result')
        result_dir = os.path.normpath(result_dir)
        os.makedirs(result_dir, exist_ok=True)

        prefix = {
            'us_stock': 'us_stock',
            'cn_stock': 'cn_stock',
            'cn_fund': 'fund',
            'cn_auto': 'fund',
            'private_fund': 'fund',
            'hk_fund': 'hk_fund',
        }.get(self.data_type, 'asset')

        # JSON
        json_path = os.path.join(result_dir, f"{prefix}_{self.symbol}_rsi.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # Report (md 格式)
        report = self.format_report(result)
        report_path = os.path.join(result_dir, f"{prefix}_{self.symbol}_rsi_report.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        # Chart (png)
        chart_path = None
        if self._df is not None and self._price_col is not None:
            try:
                from chart_generator import generate_chart
                chart_path = os.path.join(result_dir, f"{prefix}_{self.symbol}_rsi_chart.png")
                generate_chart(self._df, self._price_col, self.data_type,
                               self.symbol, result, chart_path)
                print(f"[图表] {chart_path}", file=sys.stderr)
            except Exception as e:
                print(f"[警告] 图表生成失败: {e}", file=sys.stderr)
                chart_path = None

        return json_path, report_path, chart_path

    @staticmethod
    def _recover_fallback_name(symbol, current_name):
        """如果 asset_name 是 fallback 格式（如 '基金501029'），尝试重新获取真实名称。
        返回 (recovered_name, was_recovered)。"""
        import re as _re
        if not current_name or not _re.match(r'^(基金|香港基金)\d+$', current_name):
            return current_name, False
        try:
            from data_fetcher import get_cn_fund_info, get_hk_fund_name
            # 港股基金 968 开头或 5 位数字
            if current_name.startswith('香港基金') or (len(symbol) == 5 and symbol.isdigit()):
                new_name = get_hk_fund_name(symbol)
            else:
                new_name = get_cn_fund_info(symbol)
            if new_name and not _re.match(r'^(基金|香港基金)\d+$', new_name):
                return new_name, True
        except Exception:
            pass
        return current_name, False

    @staticmethod
    def update_manifest(result_dir):
        """更新 manifest.json（记录所有已分析的基金）"""
        manifest_path = os.path.join(result_dir, 'manifest.json')
        manifest = []
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
            except Exception:
                manifest = []

        existing_symbols = {m.get('symbol') for m in manifest}
        import glob as glob_mod
        # 排除 scenario 文件，只加载完整分析结果
        def is_full_analysis(f):
            return '_scenario_' not in os.path.basename(f)

        # 优先级：fund_ > cn_fund_ > asset_ > cn_stock_ > us_stock_ > hk_fund_
        def sort_key(f):
            name = os.path.basename(f)
            for i, prefix in enumerate(['fund_', 'cn_fund_', 'asset_', 'cn_stock_', 'us_stock_', 'hk_fund_']):
                if name.startswith(prefix):
                    return (i, name)
            return (99, name)

        all_json_files = sorted(
            glob_mod.glob(os.path.join(result_dir, '*_rsi.json')),
            key=sort_key
        )

        for json_file in all_json_files:
            if not is_full_analysis(json_file):
                continue
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                sym = data.get('symbol', '')
                # 修复 fallback 名称（曾因 API 临时失败被写入"基金XXX"）
                recovered, ok = RSIAnalyzer._recover_fallback_name(sym, data.get('asset_name', ''))
                if ok:
                    data['asset_name'] = recovered
                    try:
                        with open(json_file, 'w', encoding='utf-8') as wf:
                            json.dump(data, wf, ensure_ascii=False, indent=2, default=str)
                    except Exception:
                        pass
                if sym and sym not in existing_symbols:
                    existing_symbols.add(sym)
                    manifest.append({
                        'symbol': sym,
                        'asset_name': data.get('asset_name', ''),
                        'json_file': os.path.basename(json_file),
                    })
            except Exception:
                pass

        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # Generate data.js for index.html (works with file:// protocol)
        # 保留 embedded_data.js 中已有的 TA/LLM 字段(full_ta_summary/full_ta_llm/full_ta_report/bollinger),
        # 否则每次 update_manifest 都会把 inject_ta_summary 注入的字段擦掉
        embedded_path = os.path.join(result_dir, 'embedded_data.js')
        existing_ta = {}
        if os.path.exists(embedded_path):
            try:
                _content = open(embedded_path, 'r', encoding='utf-8').read()
                _existing = json.loads(_content.split('var EMBEDDED_FUNDS = ', 1)[1].rstrip().rstrip(';'))
                _carry_keys = ('full_ta_summary', 'full_ta_llm', 'full_ta_report', 'bollinger', 'morningstar_holders', 'holders_updated')
                for _f in _existing:
                    _sym = _f.get('symbol')
                    if _sym:
                        existing_ta[_sym] = {k: _f[k] for k in _carry_keys if k in _f}
            except Exception:
                existing_ta = {}

        all_data = []
        seen_syms = set()
        for json_file in all_json_files:
            if not is_full_analysis(json_file):
                continue
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                sym = data.get('symbol', '')
                if sym and sym not in seen_syms:
                    seen_syms.add(sym)
                    # 合并已有技术分析扩展字段
                    if sym in existing_ta:
                        data.update(existing_ta[sym])
                    all_data.append(data)
            except Exception:
                pass
        data_js_path = os.path.join(result_dir, 'data.js')
        js_content = '// Auto-generated by RSI analyzer - DO NOT EDIT\nvar EMBEDDED_FUNDS = '
        js_content += json.dumps(all_data, ensure_ascii=False)
        js_content += ';\n'
        with open(data_js_path, 'w', encoding='utf-8') as f:
            f.write(js_content)

        # 同步更新 embedded_data.js（index.html 最后加载此文件，会覆盖 data.js）
        with open(embedded_path, 'w', encoding='utf-8') as f:
            f.write(js_content)

        return manifest

    # ========== 场景分析：指定 RSI 值的历史表现 ==========

    def analyze_scenario(self, rsi_value):
        """分析指定 RSI 值的历史场景"""
        rsi_value = round(float(rsi_value), 1)

        # 获取数据
        df, price_col, asset_name = fetch_data(self.symbol, self.data_type)
        if df is None:
            return None

        rsi_col = 'RSI_14'
        valid = df[df[rsi_col].notna()].copy()
        total = len(valid)

        if total < 1:
            print(f"[错误] {self.symbol} 有效 RSI 数据不足（需要至少 15 条历史数据）", file=sys.stderr)
            return None

        # 历史匹配：RSI 在 ±2 范围内
        match_mask = abs(valid[rsi_col] - rsi_value) <= 2
        matched = valid[match_mask & ~match_mask.shift(fill_value=False)].copy()
        match_count = len(matched)

        if match_count == 0:
            return {
                'symbol': self.symbol,
                'asset_name': asset_name,
                'data_type': self.data_type,
                'data_type_label': self.type_labels.get(self.data_type, '未知'),
                'target_rsi': rsi_value,
                'match_count': 0,
                'total_records': total,
                'message': f'历史数据中未找到 RSI 在 {rsi_value}±2 范围内的交易日'
            }

        # 分位定位
        percentile = round((valid[rsi_col] <= rsi_value).sum() / total * 100, 1)

        # 状态判断
        status, status_desc = self._scenario_status(rsi_value, percentile)

        # 后续收益回测
        backtest = self._scenario_backtest(valid, df, price_col, rsi_col, rsi_value)

        # 最近匹配详情
        recent = self._scenario_recent_matches(matched, df, price_col, rsi_col, limit=10)

        # 操作建议
        suggestion = self._scenario_suggestion(rsi_value, backtest, match_count, total)

        # 最新价格
        latest = df[df[rsi_col].notna()].iloc[-1]

        result = {
            'symbol': self.symbol,
            'asset_name': asset_name,
            'data_type': self.data_type,
            'data_type_label': self.type_labels.get(self.data_type, '未知'),
            'target_rsi': rsi_value,
            'match_count': match_count,
            'total_records': total,
            'match_pct': round(match_count / total * 100, 1),
            'percentile': percentile,
            'status': status,
            'status_desc': status_desc,
            'latest_date': latest['date'].strftime('%Y-%m-%d'),
            'latest_price': round(latest[price_col], 4),
            'latest_rsi': round(latest[rsi_col], 1),
            'backtest': backtest,
            'recent_matches': recent,
            'suggestion': suggestion,
        }

        return result

    def _scenario_status(self, rsi_value, percentile):
        """场景状态判断"""
        if rsi_value >= 70:
            return '超买', '极度强势，历史中很少处于此水平，回调风险大'
        elif rsi_value >= 60:
            return '强势', '偏强区域，追高风险增加'
        elif rsi_value >= 50:
            return '中性偏强', '多空分界上方，趋势尚可'
        elif rsi_value >= 40:
            return '中性偏弱', '开始走弱，可关注但不急'
        elif rsi_value >= 30:
            return '弱势', '接近超卖，历史上往往是较好的关注区间'
        elif rsi_value >= 25:
            return '深度弱势', '已进入超卖区域，历史上胜率较高'
        else:
            return '极度超卖', '历史罕见，风险收益比非常好，但需防范极端行情'

    def _scenario_backtest(self, valid, df, price_col, rsi_col, rsi_value):
        """指定 RSI 值的历史回测"""
        match_mask = abs(valid[rsi_col] - rsi_value) <= 2
        matched = valid[match_mask & ~match_mask.shift(fill_value=False)].copy()
        hold_days_list = [5, 10, 20, 30, 60, 90]
        results = {}

        for hold_days in hold_days_list:
            profits = []
            drawdowns = []
            for _, row in matched.iterrows():
                future = df[df['date'] > row['date']].head(hold_days)
                if len(future) == hold_days:
                    buy_price = row[price_col]
                    ret = (future[price_col].iloc[-1] - buy_price) / buy_price * 100
                    profits.append(ret)
                    # 持有期间最大回撤
                    min_price = future[price_col].min()
                    drawdowns.append((min_price - buy_price) / buy_price * 100)

            if profits:
                wins = [p for p in profits if p > 0]
                results[hold_days] = {
                    'signals': len(profits),
                    'win_rate': round(len(wins) / len(profits) * 100, 1),
                    'avg_profit': round(np.mean(profits), 1),
                    'median_profit': round(np.median(profits), 1),
                    'max_profit': round(max(profits), 1),
                    'max_loss': round(min(profits), 1),
                    'avg_drawdown': round(np.mean(drawdowns), 1),
                    'max_drawdown': round(min(drawdowns), 1),
                }

        return results

    def _scenario_recent_matches(self, matched, df, price_col, rsi_col, limit=10):
        """最近 N 次匹配的详细表现"""
        recent = matched.sort_values('date', ascending=False).head(limit)
        records = []
        for _, row in recent.iterrows():
            item = {
                'date': row['date'].strftime('%Y-%m-%d'),
                'rsi': round(row[rsi_col], 1),
                'price': round(row[price_col], 4),
            }
            for days in [10, 30, 60]:
                future = df[df['date'] > row['date']].head(days)
                if len(future) == days:
                    ret = (future[price_col].iloc[-1] - row[price_col]) / row[price_col] * 100
                    item[f'return_{days}d'] = round(ret, 1)
                else:
                    item[f'return_{days}d'] = None
            records.append(item)
        return records

    def _scenario_suggestion(self, rsi_value, backtest, match_count, total):
        """基于回测数据生成操作建议"""
        lines = []

        if match_count < 5:
            lines.append(f'历史中仅 {match_count} 次匹配，样本过少，建议参考完整 RSI 分析报告')
            return lines

        # 看 30 天回测
        bt30 = backtest.get(30, {})
        bt60 = backtest.get(60, {})
        bt90 = backtest.get(90, {})

        if not bt30:
            lines.append('30 天回测样本不足，建议谨慎参考')
            return lines

        lines.append(f'历史共 {match_count} 次匹配（占总交易日 {match_count/total*100:.1f}%）')

        if bt30['win_rate'] >= 70 and bt30['avg_profit'] > 0:
            lines.append(f'30 天胜率 {bt30["win_rate"]:.0f}%，平均收益 {bt30["avg_profit"]:+.1f}%，历史上在此 RSI 水平买入表现较好')
            if bt60.get('win_rate', 0) >= 65:
                lines.append(f'60 天胜率 {bt60["win_rate"]:.0f}%，中期持有也有不错表现')
        elif bt30['win_rate'] >= 55:
            lines.append(f'30 天胜率 {bt30["win_rate"]:.0f}%，平均收益 {bt30["avg_profit"]:+.1f}%，表现中规中矩')
            lines.append('可以考虑小仓位介入，但需关注后续走势')
        else:
            lines.append(f'30 天胜率仅 {bt30["win_rate"]:.0f}%，平均收益 {bt30["avg_profit"]:+.1f}%，历史上在此水平买入表现不佳')
            lines.append('建议等待 RSI 进一步走低后再考虑')

        if bt90.get('win_rate'):
            lines.append(f'90 天胜率 {bt90["win_rate"]:.0f}%，平均收益 {bt90["avg_profit"]:+.1f}%')

        return lines

    def format_scenario_report(self, result):
        """生成场景分析的 Markdown 报告"""
        lines = []
        L = lines.append

        if result.get('match_count', 0) == 0:
            L(f"# {result['symbol']} RSI={result['target_rsi']} 场景分析")
            L("")
            L(f"**{result.get('message', '无匹配数据')}**")
            return '\n'.join(lines)

        target_rsi = result['target_rsi']
        symbol = result['symbol']
        asset_name = result.get('asset_name', symbol)

        L(f"# {symbol} RSI={target_rsi} 历史场景分析")
        L("")

        # 一、定位
        L("## 一、RSI 定位")
        L("")
        headers = ['指标', '数值']
        rows = [
            ['资产名称', f"**{asset_name}**"],
            ['目标 RSI', f"**{target_rsi}**"],
            ['历史分位', f"**{result['percentile']:.1f}%**（历史上有 {result['percentile']:.1f}% 的交易日 RSI 低于此值）"],
            ['状态', f"**{result['status']}** — {result['status_desc']}"],
            ['最新日期', result['latest_date']],
            ['最新价格', f"{result['latest_price']:.4f}"],
            ['最新 RSI(14)', f"{result['latest_rsi']}"],
        ]
        L(self._make_table(headers, rows))
        L("")

        # 二、历史匹配统计
        L("## 二、历史匹配统计")
        L("")
        headers = ['指标', '数值']
        rows = [
            ['匹配范围', f"RSI {target_rsi-2} ~ {target_rsi+2}（±2）"],
            ['匹配次数', f"**{result['match_count']}** 次"],
            ['总交易日', f"{result['total_records']} 天"],
            ['出现频率', f"{result['match_pct']:.1f}%"],
        ]
        L(self._make_table(headers, rows))
        L("")

        # 三、后续收益回测
        L("## 三、后续收益回测")
        L("")
        L(f"> 在 RSI={target_rsi}±2 时买入，持有指定天数后的历史表现")
        L("")
        headers = ['持有天数', '信号数', '胜率', '平均收益', '中位收益', '最大盈利', '最大亏损', '平均回撤', '最大回撤']
        rows = []
        for hold_days in [5, 10, 20, 30, 60, 90]:
            bt = result['backtest'].get(hold_days)
            if bt:
                rows.append([
                    f"{hold_days}天",
                    str(bt['signals']),
                    f"{bt['win_rate']:.1f}%",
                    f"{bt['avg_profit']:+.1f}%",
                    f"{bt['median_profit']:+.1f}%",
                    f"{bt['max_profit']:+.1f}%",
                    f"{bt['max_loss']:+.1f}%",
                    f"{bt['avg_drawdown']:+.1f}%",
                    f"{bt['max_drawdown']:+.1f}%",
                ])
            else:
                rows.append([f"{hold_days}天", "—", "—", "—", "—", "—", "—", "—", "—"])
        L(self._make_table(headers, rows))
        L("")

        # 四、最近匹配记录
        L("## 四、最近匹配记录")
        L("")
        if result.get('recent_matches'):
            headers = ['日期', 'RSI', '价格', '10天收益', '30天收益', '60天收益']
            rows = []
            for m in result['recent_matches']:
                ret10 = f"{m['return_10d']:+.1f}%" if m.get('return_10d') is not None else "N/A"
                ret30 = f"{m['return_30d']:+.1f}%" if m.get('return_30d') is not None else "N/A"
                ret60 = f"{m['return_60d']:+.1f}%" if m.get('return_60d') is not None else "N/A"
                rows.append([m['date'], f"{m['rsi']:.1f}", f"{m['price']:.4f}", ret10, ret30, ret60])
            L(self._make_table(headers, rows))
        else:
            L("*无匹配记录*")
        L("")

        # 五、操作建议
        L("## 五、操作建议")
        L("")
        for line in result.get('suggestion', []):
            L(f"- {line}")
        L("")

        L("---")
        L("")
        L("⚠️ **风险提示：** 基于 RSI 历史统计，不构成投资建议。")

        return '\n'.join(lines)

    def save_scenario_files(self, result):
        """保存场景分析文件"""
        result_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'result')
        result_dir = os.path.normpath(result_dir)
        os.makedirs(result_dir, exist_ok=True)

        prefix = {
            'us_stock': 'us_stock',
            'cn_stock': 'cn_stock',
            'cn_fund': 'fund',
            'cn_auto': 'fund',
            'private_fund': 'fund',
            'hk_fund': 'hk_fund',
        }.get(self.data_type, 'asset')

        rsi_val = int(result['target_rsi'])

        # JSON
        json_path = os.path.join(result_dir, f"{prefix}_{self.symbol}_scenario_{rsi_val}_rsi.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # Report (md)
        report = self.format_scenario_report(result)
        report_path = os.path.join(result_dir, f"{prefix}_{self.symbol}_scenario_{rsi_val}_rsi_report.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        return json_path, report_path
