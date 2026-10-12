#!/usr/bin/env python3
"""快速拉取红利基金净值并计算 RSI(14)"""

import sys
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, 'lib')
sys.path.insert(0, LIB_DIR)

from data_fetcher import fetch_cn_fund_history, calculate_rsi

# 10只红利基金代码
FUNDS = {
    '007467': '华泰柏瑞中证红利低波ETF联接C',
    '008164': '南方标普红利低波50ETF联接C',
    '007606': '嘉实沪深300红利低波动ETF联接C',
    '012644': '招商中证红利ETF联接C',
    '021735': '景顺长城沪港深红利成长低波指数E',
    '005125': '华宝标普中国A股红利机会ETF联接C',
    '020467': '华泰柏瑞中证中央企业红利ETF发起式联接C',
    '008115': '天弘中证红利低波动100联接C',
    '021702': '国泰上证国企红利ETF联接C',
    '021962': '景顺长城中证国新港股通央企红利ETF联接C',
}

results = {}

for code, name in FUNDS.items():
    print(f"\n{'='*60}")
    print(f"处理: {code} {name}")
    try:
        ret = fetch_cn_fund_history(code)
        if ret is None:
            print(f"  ❌ 获取失败")
            continue
        df, fetched_name = ret
        if df is None or len(df) < 20:
            print(f"  ❌ 数据不足")
            continue

        # 使用累计净值计算 RSI
        price_col = 'adj_nav'
        prices = df[price_col].values
        dates = df['date'].dt.strftime('%Y-%m-%d').values

        # 计算 RSI(14)
        rsi_values = calculate_rsi(prices, period=14)

        latest_rsi = rsi_values[-1]
        latest_price = prices[-1]
        latest_date = dates[-1]

        # 计算 RSI 分位
        valid_rsi = [r for r in rsi_values if r is not None and not (isinstance(r, float) and (r != r))]
        sorted_rsi = sorted(valid_rsi)
        percentile = sum(1 for r in sorted_rsi if r <= latest_rsi) / len(sorted_rsi) * 100

        # 近5日RSI趋势
        recent_rsi = [r for r in rsi_values[-5:] if r is not None]
        rsi_5d_ago = recent_rsi[0] if len(recent_rsi) >= 5 else None

        # 近5日涨跌幅
        recent_prices = prices[-5:] if len(prices) >= 5 else prices
        pct_5d = (recent_prices[-1] / recent_prices[0] - 1) * 100 if len(recent_prices) >= 2 else 0

        results[code] = {
            'name': name,
            'latest_date': latest_date,
            'latest_price': round(float(latest_price), 4),
            'rsi_14': round(latest_rsi, 2),
            'rsi_percentile': round(percentile, 1),
            'rsi_5d_ago': round(rsi_5d_ago, 2) if rsi_5d_ago else None,
            'pct_5d': round(pct_5d, 2),
            'data_points': len(df),
            'rsi_min': round(min(valid_rsi), 2),
            'rsi_max': round(max(valid_rsi), 2),
            'rsi_mean': round(sum(valid_rsi) / len(valid_rsi), 2),
        }

        print(f"  ✅ {latest_date} | 净值={latest_price:.4f} | RSI(14)={latest_rsi:.1f} | 分位={percentile:.1f}%")

    except Exception as e:
        print(f"  ❌ 异常: {e}")

# 输出汇总
print("\n" + "="*60)
print("汇总结果")
print("="*60)

for code in FUNDS:
    if code in results:
        r = results[code]
        status = '超卖' if r['rsi_14'] < 30 else ('超买' if r['rsi_14'] > 70 else '中性')
        print(f"{code} {r['name']:20s} | RSI={r['rsi_14']:5.1f} | 分位={r['rsi_percentile']:5.1f}% | {status} | 5日涨跌={r['pct_5d']:+.2f}%")

# 保存 JSON
output_path = os.path.join(SCRIPT_DIR, 'result', 'dividend_rsi_summary.json')
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n结果已保存: {output_path}")