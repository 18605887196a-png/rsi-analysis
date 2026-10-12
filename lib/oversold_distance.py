#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""超卖距离表 —— 核心关注标的距离 RSI 超卖阈值(35/30/25/22)还需跌多少、跌到什么价。

被 update_dividend_bond_qdii.sh 在 VIX 步骤之后调用。每次全量更新时:
  1. 扫描 result/*_rsi.json 的 symbol/data_type,按 index.html 的 CODES 集合
     归类出"核心关注"标的(FOCUS_CATEGORIES = dividend/bond_tier1/global/us_stock)
  2. 逐只拉取与主批次同一管道(fetch_data)的完整价格序列,用与
     data_fetcher.calculate_rsi 完全一致的 Wilder 递推重建 avgGain/avgLoss 终态
  3. 反解"次日单日跌到位"场景: RSI(14) 达到目标 T 所需单日跌幅 loss_req = 13*(A*(100-T)/T - L),
     输出距现价跌幅百分比(页面用 latest.price 现价换算触达价)
     RSI 已低于 T 的阈值按用户约定不写(None),页面显示为 "-"
  4. 用正则原地替换 index.html 里 ``const OVERSOLD_DISTANCE = {...};`` 一行
     (与 VIX_DIST 同一套机制;替换失败不破坏文件)

可单独运行:  python3 lib/oversold_distance.py
"""
import os
import re
import json
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 复用主项目的取数管道(脚本内调用时 cwd=rsi-analysis;单独调用也兼容)
_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)
if os.path.join(_SKILL_DIR, 'lib') not in sys.path:
    sys.path.insert(0, os.path.join(_SKILL_DIR, 'lib'))

from data_fetcher import fetch_data  # noqa: E402

RESULT = os.path.join(_SKILL_DIR, 'result')
INDEX_HTML = os.path.join(RESULT, 'index.html')

# 超卖阈值(注意顺序递减);与 index.html FOCUS_CATEGORIES 保持一致的"核心关注"定义
THRESHOLDS = [40, 35, 30, 25, 22]
FOCUS_CATEGORIES = {'dividend', 'bond_tier1', 'global', 'us_stock', 'broad'}
PERIOD = 14
MAX_WORKERS = 5

SET_NAMES = ('BROAD_CODES', 'QUALITY_CODES', 'HK_CODES', 'DIVIDEND_CODES',
             'THEMATIC_CODES', 'BOND_CODES', 'BOND_TIER1', 'COMMODITY_CODES',
             'GLOBAL_CODES', 'PRIVATE_CODES')


def load_category_sets():
    """从 result/index.html 解析分类常量集合(与 update_all.py 同一套正则口径)"""
    sets = {}
    try:
        text = open(INDEX_HTML, 'r', encoding='utf-8').read()
        for name in SET_NAMES:
            m = re.search(r'const\s+' + name + r'\s*=\s*new\s+Set\(\[([^\]]*)\]\)', text, re.S)
            sets[name] = set(re.findall(r"'(\d+)'", m.group(1))) if m else set()
    except Exception:
        pass
    return sets


def get_category(symbol, data_type, sets):
    """Python 版 getCategory 精简版(顺序与 index.html/update_all 一致)"""
    if symbol in sets.get('PRIVATE_CODES', set()): return 'private'
    if symbol in sets.get('BROAD_CODES', set()): return 'broad'
    if symbol in sets.get('QUALITY_CODES', set()): return 'quality'
    if symbol in sets.get('HK_CODES', set()): return 'hk'
    if symbol in sets.get('DIVIDEND_CODES', set()): return 'dividend'
    if symbol in sets.get('THEMATIC_CODES', set()): return 'thematic'
    bond, tier1 = sets.get('BOND_CODES', set()), sets.get('BOND_TIER1', set())
    if symbol in bond and symbol not in tier1: return 'bond'
    if symbol in tier1: return 'bond_tier1'
    if symbol in sets.get('COMMODITY_CODES', set()): return 'commodity'
    if symbol in sets.get('GLOBAL_CODES', set()): return 'global'
    if data_type == 'us_stock': return 'us_stock'
    if data_type == 'cn_stock': return 'cn_stock'
    return 'other'


def collect_focus_symbols():
    """扫 result/*_rsi.json,取核心关注标的 [{symbol, data_type}...]"""
    sets = load_category_sets()
    targets = []
    for fn in sorted(os.listdir(RESULT)):
        if not fn.endswith('_rsi.json'):
            continue
        try:
            meta = json.load(open(os.path.join(RESULT, fn), 'r', encoding='utf-8'))
            sym, dt = str(meta.get('symbol', '')), meta.get('data_type', '')
            if sym and get_category(sym, dt, sets) in FOCUS_CATEGORIES:
                targets.append({'symbol': sym, 'data_type': dt})
        except Exception:
            continue
    return targets


def wilder_state(prices, period=PERIOD):
    """复刻 data_fetcher.calculate_rsi 的 Wilder 平滑,返回最终 (avg_gain, avg_loss, last_price)。
    权重:首段用前 period 个差值的简单均值为种子,之后 avg = (avg*(p-1)+x)/p。"""
    n = len(prices)
    if n <= period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    return avg_gain, avg_loss, prices[-1]


def compute_oversold(entry):
    """单只标的:取数 -> Wilder 终态 -> 各阈值所需的次日单日跌幅(%)。"""
    sym = entry['symbol']
    df, price_col, _name = fetch_data(sym, entry['data_type'])
    if df is None or price_col is None or price_col not in df.columns or len(df) <= PERIOD + 1:
        return sym, None
    prices = [float(x) for x in df[price_col].dropna().tolist()]
    state = wilder_state(prices)
    if state is None:
        return sym, None
    avg_gain, avg_loss, last_price = state
    if last_price <= 0:
        return sym, None
    if avg_gain == 0 and avg_loss == 0:
        rsi_now = 50.0
    elif avg_loss == 0:
        rsi_now = 100.0
    else:
        rsi_now = 100.0 * avg_gain / (avg_gain + avg_loss)
    d = {}
    for t in THRESHOLDS:
        # RSI 已低于该阈值:按约定不写(None, 页面显示 "-")
        if rsi_now <= t + 1e-9:
            d[str(t)] = None
            continue
        # 次日单日跌到位: L1_req = A1*(100-T)/T; loss_req = L1_req*p - L*(p-1)
        # 化简后 loss_req = (p-1)*(avg_gain*(100-T)/T - avg_loss),RSI>T 时恒 >0
        loss_req = (PERIOD - 1) * (avg_gain * (100 - t) / t - avg_loss)
        pct = loss_req / last_price * 100.0
        # 单日跌不出该 RSI(理论上仅极端高 RSI+零波动锚定时),同样留空
        # 保留3位小数:2位时对<1%的小跌幅会带来近似误差(回算RSI可偏0.05+)
        d[str(t)] = round(pct, 3) if 0 < pct < 99.5 else None
    return sym, {'rsi': round(rsi_now, 1), 'd': d}


def update_index_html(dist):
    """用正则原地替换 index.html 里 ``const OVERSOLD_DISTANCE = {...};`` 这一行(VIX_DIST 同款机制)。"""
    if not os.path.exists(INDEX_HTML):
        print(f'  [超卖] index.html 不存在,跳过更新: {INDEX_HTML}')
        return False
    new_line = 'const OVERSOLD_DISTANCE = ' + json.dumps(dist, ensure_ascii=False, separators=(',', ':')) + ';'
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = re.compile(r'const OVERSOLD_DISTANCE = \{.*?\};', re.DOTALL)
    if pattern.search(content):
        new_content = pattern.sub(lambda m: new_line, content, count=1)
        with open(INDEX_HTML, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'  [超卖] 已更新 index.html 的 OVERSOLD_DISTANCE ({dist["_meta"]["ok"]}/{dist["_meta"]["universe"]} 只)')
        return True
    print('  [超卖] index.html 未找到 OVERSOLD_DISTANCE 行,跳过(不破坏文件)')
    return False


def main():
    print('>>> 阶段: 刷新核心关注超卖距离表', flush=True)
    targets = collect_focus_symbols()
    print(f'  核心关注标的: {len(targets)} 只,开始取数(并发{MAX_WORKERS})...', flush=True)
    result, ok = {}, 0

    def work(entry):
        try:
            return compute_oversold(entry)
        except Exception as e:
            print(f'  [{entry["symbol"]}] 取数/计算失败: {type(e).__name__}: {e}', flush=True)
            return entry['symbol'], None

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(work, e): e['symbol'] for e in targets}
        for fut in as_completed(futures):
            sym, data = fut.result()
            done += 1
            if data:
                result[sym] = data
                ok += 1
            if done % 10 == 0 or done == len(targets):
                print(f'  进度 {done}/{len(targets)} (成功 {ok})', flush=True)

    dist = {'_meta': {
        'generated_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'thresholds': THRESHOLDS,
        'note': '距离=RSI(14)达到目标阈值所需跌幅%,次日单日跌到位(Wilder口径);已低于阈值为null,页面显示-;触达价=现价×(1-距离%)',
        'universe': len(targets), 'ok': ok,
    }, **result}
    if ok == 0:
        print('  ⚠️ 无一只成功,保留旧数据不覆盖')
        return
    update_index_html(dist)
    print(f'>>> 超卖距离表完成: {ok}/{len(targets)} 只成功', flush=True)


if __name__ == '__main__':
    main()
