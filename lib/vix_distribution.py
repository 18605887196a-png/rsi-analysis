#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VIX 恐慌指数 历史价位分布 —— 拉取最新数据、计算分布、更新 Dashboard。

被 batch_update.sh 作为"阶段四"调用。每次全量更新时:
  1. 从 Yahoo 拉取 ^VIX 最新 25 年日线数据
  2. 按价位分桶统计 + 高位累积稀有度
  3. 重新生成分布图表 PNG
  4. 用正则原地替换 index.html 里的 ``const VIX_DIST = {...};`` 一行
     (替换若失败则原地新增,不破坏 index.html 其他内容)

可单独运行:  python3 lib/vix_distribution.py
"""
import os
import re
import json
import datetime

import requests
import pandas as pd
import numpy as np

# matplotlib 延迟导入(仅生成图表时需要)
RESULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'result')
INDEX_HTML = os.path.join(RESULT, 'index.html')
JSON_OUT = os.path.join(RESULT, 'vix_price_distribution.json')
PNG_OUT = os.path.join(RESULT, 'vix_price_distribution.png')

# FRED VIXCLS 本地资源（官方 VIX 现货日线 1990 起，用户从 https://fred.stlouisfed.org/series/VIXCLS 下载覆盖更新）
FRED_VIX_XLSX = os.path.join(os.path.dirname(RESULT), 'data', 'VIXCLS.xlsx')

VIX_SYMBOL = '^VIX'
RANGE = '25y'    # 25 年日线(Yahoo 日线最深;再长会降为月线)
KEY_LEVELS = [15, 18, 20, 22, 25, 28, 30, 35, 40, 45, 50]
BINS = list(range(8, 62, 2)) + [200]


def fetch_vix_history():
    """拉取 ^VIX 日线历史(现货)。返回 pandas.DataFrame(date, close)。

    优先用本地 FRED VIXCLS(官方 VIX 现货日线,1990 起,最真实;用户定期从 FRED 官网覆盖更新)。
    FRED 文件不在时回退 Yahoo，再回退腾讯 us.VIX(kline/kline 分页；腾讯 feed 2022 后停更需剥平尾)。
    CBOE 近期日线由 main() 末尾追加补齐最新交易日。
    """
    # === 方案0: 本地 FRED VIXCLS（官方全量现货日线，主源）===
    if os.path.isfile(FRED_VIX_XLSX):
        try:
            raw = pd.read_excel(FRED_VIX_XLSX, sheet_name='Daily, Close')
            raw = raw[['observation_date', 'VIXCLS']].rename(columns={'observation_date': 'date', 'VIXCLS': 'close'})
            raw['date'] = pd.to_datetime(raw['date'])
            raw['close'] = pd.to_numeric(raw['close'], errors='coerce')
            df = raw.dropna().sort_values('date').reset_index(drop=True)
            if len(df) > 0:
                print(f'  [VIX] FRED VIXCLS 取数成功: {len(df)} 条，范围 {df["date"].min().date()} ~ {df["date"].max().date()}')
                return df
        except Exception as e:
            print(f'  [VIX] FRED 文件读取失败: {e}')

    # === 方案1: Yahoo Finance ===
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{VIX_SYMBOL}'
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, params={'range': RANGE, 'interval': '1d'}, timeout=30)
        data = resp.json()['chart']['result'][0]
        ts = data['timestamp']
        quote = data['indicators']['quote'][0]
        df = pd.DataFrame({'date': pd.to_datetime(ts, unit='s'), 'close': quote['close']}).dropna()
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) > 0:
            print(f'  [VIX] Yahoo 取数成功: {len(df)} 条')
            return df
    except Exception as e:
        print(f'  [VIX] Yahoo 失败: {e}')

    # === 方案2: 腾讯财经 us.VIX ===
    import time as _t
    from datetime import datetime, timedelta
    tx_headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    end_date = '2026-08-08'
    all_rows = []
    for _ in range(8):
        try:
            r = requests.get('https://web.ifzq.gtimg.cn/appstock/app/kline/kline',
                             params={'param': f'us.VIX,day,1990-01-01,{end_date},2000'},
                             headers=tx_headers, timeout=30)
            arr = (r.json().get('data') or {}).get('us.VIX', {}).get('day') or []
        except Exception:
            arr = []
        if not arr:
            break
        # 字段顺序: [date, open, close, high, low, volume]
        all_rows = arr + all_rows
        if len(arr) < 2000:
            break
        first_date = arr[0][0]
        nd = datetime.strptime(first_date, '%Y-%m-%d') - timedelta(days=1)
        end_date = nd.strftime('%Y-%m-%d')
        _t.sleep(0.3)

    if not all_rows:
        raise RuntimeError('VIX 取数失败：Yahoo 与腾讯均无数据')

    seen, rows = set(), []
    for item in all_rows:
        d_ = item[0]
        if d_ in seen:
            continue
        seen.add(d_)
        try:
            rows.append({'date': pd.to_datetime(d_), 'close': float(item[2])})
        except (IndexError, ValueError, TypeError):
            continue
    df = pd.DataFrame(rows).dropna()
    df = df.sort_values('date').reset_index(drop=True)

    # 腾讯 VIX feed 末段会有一长串"平值死值"（连续相等，长达数年，是 feed 停更后的占位），
    # 必须剥掉，否则会用假值污染分布。从尾部往前删连续相等值。
    if len(df) >= 3:
        last_val = df['close'].iloc[-1]
        n_flat = 0
        for v in df['close'].tolist()[::-1]:
            if v == last_val:
                n_flat += 1
            else:
                break
        if n_flat >= 2:
            real_end = df['date'].iloc[-n_flat - 1].date() if n_flat < len(df) else None
            df = df.iloc[:-n_flat].reset_index(drop=True)
            print(f'  [VIX] 剥除腾讯平值死尾 {n_flat} 根（疑似 feed 停更占位），真实末点 {real_end}')

    print(f'  [VIX] 腾讯取数成功: {len(df)} 条，范围 {df["date"].min().date()} ~ {df["date"].max().date()}'
          f'（腾讯 VIX feed 滞后，近期由 CBOE 补）')
    return df


def fetch_vix_realtime_cboe():
    """从 CBOE 官方 VIX 产品页抓取近期 VIX 现货日线（约近 1 个月分时点，按日取末值）。

    页面内嵌 React Query 脱水状态，含 ``VIX.symbolData = [{x:ms, "val-VIX":v, "pct-VIX":pct}, ...]``。
    返回 [(date, close), ...] 升序（每个交易日取当日最后一点）；失败返回空 list。
    本机 Yahoo/CBOE CDN 均 403，但 www.cboe.com 可达；腾讯 VIX feed 2022 年后停更，故用 CBOE 补近期。
    """
    import re as _re
    import datetime as _dt
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36'}
    resp = requests.get('https://www.cboe.com/tradable_products/vix/', headers=headers, timeout=25)
    t = resp.text
    pairs = _re.findall(r'\\"x\\":(\d+),\\"val-VIX\\":([0-9.]+),\\"pct-VIX\\":([-\-0-9.]+)', t)
    if not pairs:
        pairs = _re.findall(r'"x":(\d+),"val-VIX":([0-9.]+),"pct-VIX":([-\-0-9.]+)', t)
    if not pairs:
        return []
    daily = {}
    for x, val, _pct in pairs:
        d = _dt.datetime.fromtimestamp(int(x) / 1000, tz=_dt.timezone.utc).date()
        daily[d] = float(val)   # 同日多点，后者覆盖前者（取当日最后值）
    return sorted(daily.items())


def compute_distribution(prices):
    """价位分桶统计。返回 dict(同 vix_price_distribution.json 结构)。"""
    prices = np.asarray(prices, dtype=float)
    n = len(prices)
    counts, _ = np.histogram(prices, bins=BINS)
    pcts = counts / n * 100
    # 累积: >= 档位下界的占比(高位稀有度)
    cum_ge = []
    running = 0
    for i in range(len(counts) - 1, -1, -1):
        running += counts[i]
        cum_ge.insert(0, running / n * 100)
    key_levels = {str(lv): round(float((prices >= lv).sum() / n * 100), 3) for lv in KEY_LEVELS}
    low = prices[prices < 20]; mid = prices[(prices >= 20) & (prices < 30)]; high = prices[prices >= 30]
    return {
        'symbol': VIX_SYMBOL, 'name': 'VIX恐慌指数', 'total': int(n),
        'date_range': None,  # 调用方填
        'current': round(float(prices[-1]), 2),
        'mean': round(float(prices.mean()), 2),
        'median': round(float(np.median(prices)), 2),
        'min': round(float(prices.min()), 2),
        'max': round(float(prices.max()), 2),
        'bins': BINS[:-1],
        'counts': [int(c) for c in counts],
        'pcts': [round(float(p), 2) for p in pcts],
        'cum_ge': [round(float(c), 2) for c in cum_ge],
        'key_levels': key_levels,
        'zones': {
            'low_lt20': round(float(len(low) / n * 100), 2),
            'mid_20_30': round(float(len(mid) / n * 100), 2),
            'high_ge30': round(float(len(high) / n * 100), 2),
            'high_mean': round(float(high.mean()), 2) if len(high) else 0,
        },
    }


def render_chart(dist):
    """重新生成 VIX 分布图表 PNG。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fp in ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Medium.ttc']:
        if os.path.exists(fp):
            plt.rcParams['font.family'] = font_manager.FontProperties(fname=fp).get_name()
            break
    plt.rcParams['axes.unicode_minus'] = False

    bins = dist['bins']; pcts = dist['pcts']; cum = dist['cum_ge']; cur = dist['current']
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), gridspec_kw={'height_ratios': [3, 2]})
    centers = [bins[i] + 1 for i in range(len(dist['counts']))]
    colors = ['#2ecc71' if b < 15 else ('#3498db' if b < 22 else ('#f39c12' if b < 30 else '#e74c3c')) for b in bins]
    ax1.bar(centers, pcts, width=1.8, color=colors, edgecolor='white', linewidth=0.5, alpha=0.85)
    ax1.axvline(cur, color='red', ls='--', lw=2, label=f'当前 VIX={cur}')
    ax1.set_xlabel('VIX 数值'); ax1.set_ylabel('占比 (%)')
    ax1.set_title(f'VIX 恐慌指数 历史价位分布 ({dist["date_range"][0]}~{dist["date_range"][1]}, {dist["total"]} 个交易日)',
                  fontsize=14, fontweight='bold')
    ax1.set_xticks(list(range(10, 62, 5)))
    ax1.axvspan(8, 15, alpha=0.08, color='green'); ax1.axvspan(15, 22, alpha=0.06, color='blue')
    ax1.axvspan(22, 30, alpha=0.08, color='orange'); ax1.axvspan(30, 62, alpha=0.10, color='red')
    mp = max(pcts) if pcts else 1
    ax1.text(11, mp * 0.92, '极度平静', ha='center', fontsize=9, color='#27ae60')
    ax1.text(18, mp * 0.92, '正常波动', ha='center', fontsize=9, color='#2980b9')
    ax1.text(26, mp * 0.92, '波动升高', ha='center', fontsize=9, color='#e67e22')
    ax1.text(40, mp * 0.92, '★恐慌区\n做多甜区', ha='center', fontsize=9, color='#c0392b', fontweight='bold')
    ax1.legend(fontsize=11, loc='upper right'); ax1.grid(axis='y', alpha=0.3)
    # 累积稀有度
    ax2.plot(bins, cum, color='#8e44ad', lw=2.5, marker='o', ms=4)
    ax2.fill_between(bins, cum, color='#8e44ad', alpha=0.12)
    ax2.axvline(cur, color='red', ls='--', lw=2)
    ax2.axhline(10, color='gray', ls=':', alpha=0.5); ax2.axhline(5, color='gray', ls=':', alpha=0.5)
    for lv in [30, 35, 40]:
        ge = dist['key_levels'].get(str(lv), 0)
        ax2.annotate(f'VIX≥{lv} = {ge}%', xy=(lv, ge), xytext=(lv + 4, ge + 8),
                     fontsize=9, color='#c0392b', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='#c0392b'))
    ax2.set_xlabel('VIX 数值 (≥)'); ax2.set_ylabel('历史占比 (%)')
    ax2.set_title('高位稀有度: VIX ≥ X 的历史时间占比 (越低越罕见 = 做多机会越好)',
                  fontsize=12, fontweight='bold')
    ax2.set_xticks(list(range(10, 62, 5))); ax2.set_ylim(0, 105); ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PNG_OUT, dpi=130, bbox_inches='tight')
    plt.close(fig)


def update_index_html(dist):
    """用正则原地替换 index.html 里 ``const VIX_DIST = {...};`` 这一行。
    若该行不存在则不修改(避免破坏文件)。返回是否成功。
    """
    if not os.path.exists(INDEX_HTML):
        print(f'  [VIX] index.html 不存在,跳过更新: {INDEX_HTML}')
        return False
    new_line = 'const VIX_DIST = ' + json.dumps(dist, ensure_ascii=False, separators=(',', ':')) + ';'
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = re.compile(r'const VIX_DIST = \{.*?\};', re.DOTALL)
    if pattern.search(content):
        new_content = pattern.sub(lambda m: new_line, content, count=1)
        with open(INDEX_HTML, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'  [VIX] 已更新 index.html 的 VIX_DIST (current={dist["current"]})')
        return True
    else:
        print(f'  [VIX] index.html 未找到 VIX_DIST 行,跳过(不破坏文件)')
        return False


def main():
    print('>>> 阶段四: 刷新 VIX 价位分布', flush=True)
    try:
        df = fetch_vix_history()
    except Exception as e:
        print(f'  [VIX] 拉取 VIX 数据失败: {e}')
        return False
    if len(df) == 0:
        print('  [VIX] VIX 数据为空,跳过')
        return False
    # 用 CBOE 近期日线补腾讯停更后的缺口：追加所有晚于历史末点的交易日
    try:
        rt = fetch_vix_realtime_cboe()
        if rt:
            new_pts = [(d, v) for d, v in rt if pd.Timestamp(d) > df['date'].max()]
            if new_pts:
                df = pd.concat([df, pd.DataFrame({'date': [pd.Timestamp(d) for d, _ in new_pts],
                                                  'close': [v for _, v in new_pts]})],
                               ignore_index=True).sort_values('date').reset_index(drop=True)
                print(f'  [VIX] CBOE 追加近期 {len(new_pts)} 个交易日: {new_pts[0][0]} ~ {new_pts[-1][0]}'
                      f'，当前值 {new_pts[-1][1]} @ {new_pts[-1][0]}')
            else:
                print(f'  [VIX] CBOE 末点 {rt[-1][1]} @ {rt[-1][0]} 未晚于历史末点，不追加')
    except Exception as e:
        print(f'  [VIX] CBOE 实时取数失败(不影响历史分布): {e}')
    prices = df['close'].values
    dist = compute_distribution(prices)
    dist['date_range'] = [str(df['date'].min().date()), str(df['date'].max().date())]
    # 保存 JSON
    with open(JSON_OUT, 'w', encoding='utf-8') as f:
        json.dump(dist, f, ensure_ascii=False, indent=2)
    print(f'  [VIX] 数据: {dist["total"]} 条, {dist["date_range"][0]}~{dist["date_range"][1]}')
    print(f'  [VIX] 当前={dist["current"]} 均值={dist["mean"]} 中位={dist["median"]} '
          f'最小={dist["min"]} 最大={dist["max"]}')
    for lv in [25, 30, 35, 40]:
        print(f'  [VIX]   VIX≥{lv}: {dist["key_levels"][str(lv)]}%')
    # 生成图表
    try:
        render_chart(dist)
        print(f'  [VIX] 图表已更新: {PNG_OUT}')
    except Exception as e:
        print(f'  [VIX] 图表生成失败(不影响数据): {e}')
    # 更新 index.html
    update_index_html(dist)
    print('>>> 阶段四完成', flush=True)
    return True


if __name__ == '__main__':
    ok = main()
    raise SystemExit(0 if ok else 0)  # VIX 失败不应中断 batch_update