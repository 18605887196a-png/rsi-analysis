#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据获取模块 - 支持美股、A股股票、A股基金、香港基金"""

import re
import json
import os
import time
import requests
import pandas as pd
from functools import wraps


def load_start_override():
    """加载数据起始日期覆盖配置"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data_start_override.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith('_')}
    return {}


def apply_start_override(symbol, df):
    """如果标的在覆盖配置中，裁剪数据起始日期"""
    override = load_start_override()
    if symbol in override:
        start_date = override[symbol]
        before = len(df)
        source_start = df['date'].min().strftime('%Y-%m-%d') if 'date' in df.columns else None
        # 确保有 date 列
        date_col = 'date' if 'date' in df.columns else df.index.name
        if date_col and date_col in df.columns:
            df = df[df[date_col] >= pd.Timestamp(start_date)].copy()
        elif df.index.name == 'date':
            df = df[df.index >= pd.Timestamp(start_date)].copy()
        df.attrs.update(
            analysis_start_override=start_date,
            source_history_start=source_start,
            source_history_records=before,
        )
        print(f"  [数据裁剪] {symbol}: 从 {start_date} 开始，{before} → {len(df)} 条")
    return df


def retry_on_failure(max_retries=3, delay=5, backoff=2):
    """重试装饰器 - 用于网络请求"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                        requests.exceptions.HTTPError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait = delay * (backoff ** attempt)
                        print(f"  [重试] {func.__name__} 第{attempt+1}次失败, {wait}s后重试...")
                        time.sleep(wait)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait = delay * (backoff ** attempt)
                        print(f"  [重试] {func.__name__} 异常, {wait}s后重试...")
                        time.sleep(wait)
            raise last_exception
        return wrapper
    return decorator


def detect_type(symbol):
    """根据代码自动识别资产类型

    A股代码规则：
    - 60xxxx: 上海主板（股票）
    - 00xxxx: 需要自动检测（可能是基金也可能是股票）
    - 30xxxx: 创业板（股票）
    - 68xxxx: 科创板（股票）
    - 51xxxx: ETF/基金
    - 15xxxx: ETF/基金
    - 968xxx: 香港基金
    """
    s = symbol.strip().upper()
    # Yahoo 指数: ^VIX / ^GSPC / ^DJI 等 (^ 前缀，需保留 ^ 传给 Yahoo)
    if re.match(r'^\^[A-Z]+$', s):
        return 'us_stock', s
    if re.match(r'^[A-Z]+$', s):
        return 'us_stock', s
    if re.match(r'^968', s):
        return 'hk_fund', s
    if re.match(r'^\d{6}$', s):
        first_two = s[:2]
        # ETF/基金: 51, 15, 16, 18 开头
        if first_two in ['51', '52', '56', '58', '15', '16', '18']:
            return 'cn_fund', s
        # 00开头需要自动检测（可能是基金也可能是股票）
        if first_two == '00':
            return 'cn_auto', s
        # A股股票: 60, 30, 68 开头
        if first_two in ['60', '30', '68']:
            return 'cn_stock', s
        # 其他6位数字，尝试自动检测
        return 'cn_auto', s
    return 'unknown', s


def calculate_rsi(prices, period=14):
    """使用 Wilder's Smoothing 方法计算 RSI"""
    prices_series = pd.Series(prices)
    if len(prices_series) <= period:
        return [None] * len(prices_series)
    delta = prices_series.diff()

    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.iloc[1:period+1].mean()
    avg_loss = loss.iloc[1:period+1].mean()

    rsi_values = []

    if avg_gain == 0 and avg_loss == 0:
        rsi_values.append(50.0)
    elif avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_values.append(round(rsi, 2))

    for i in range(period+1, len(prices)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period

        if avg_gain == 0 and avg_loss == 0:
            rsi_values.append(50.0)
        elif avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_values.append(round(rsi, 2))

    result = [None] * period + rsi_values
    return result


def _eastmoney_date(timestamp_ms):
    """东方财富毫秒时间戳代表北京时间日期，不能按 UTC 日期直接截断。"""
    return pd.to_datetime(timestamp_ms, unit='ms', utc=True).tz_convert('Asia/Shanghai').strftime('%Y-%m-%d')


def fetch_us_stock_history(symbol, years=20):
    """获取美股历史数据 — 优先 Yahoo Finance，失败则回退东方财富"""
    print(f"正在获取 {symbol} 的历史数据（{years}年）...")

    # === 方案1: Yahoo Finance ===
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        params = {'range': f'{years}y', 'interval': '1d'}

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        data = resp.json()

        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        meta = result.get('meta', {})
        asset_name = meta.get('longName') or meta.get('shortName') or symbol

        # 优先使用前复权价(adjclose)，对分红股(JEPI/DIVO等)至关重要
        raw_close = pd.Series(quote['close'], dtype='float64')
        adjclose = pd.Series(
            result['indicators'].get('adjclose', [{}])[0].get('adjclose', quote['close']),
            dtype='float64'
        )
        adjustment = (adjclose / raw_close).replace([float('inf'), float('-inf')], pd.NA).fillna(1.0)

        df = pd.DataFrame({
            'date': pd.to_datetime(timestamps, unit='s'),
            'open': pd.Series(quote['open'], dtype='float64') * adjustment,
            'high': pd.Series(quote['high'], dtype='float64') * adjustment,
            'low': pd.Series(quote['low'], dtype='float64') * adjustment,
            'close': adjclose,
            'volume': quote['volume']
        })

        df = df.dropna()
        df = df.sort_values('date').reset_index(drop=True)
        df.attrs.update(data_source='Yahoo Finance chart', price_basis='adjusted_close')

        print(f"成功获取 {len(df)} 条数据 [{asset_name}]")
        print(f"数据范围: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")

        return df, asset_name

    except Exception as e:
        print(f"Yahoo Finance 失败: {e}")

    # === 方案2: 东方财富（美股，前复权 fqt=1）===
    # secid 前缀按交易所区分（105=纳斯达克, 106=纽交所, 107=NYSE Arca/部分ETF），
    # 不能写死 107。先用 suggest 接口解析正确 QuoteID，失败则按 105/107/106 顺序试探。
    try:
        print(f"  尝试东方财富美股接口...")
        import time
        from datetime import datetime, timedelta
        em_headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.eastmoney.com/'
        }

        # 带连接级重试的 Session（push2his 端点有约 20% 的 RemoteDisconnected 抖动）；
        # 重试次数克制，避免被硬封 IP 时长时间空等（会快速落到腾讯兜底）。
        em_session = requests.Session()
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            _retry = Retry(total=2, backoff_factor=1,
                           status_forcelist=[502, 503, 504],
                           allowed_methods=frozenset(['GET']),
                           raise_on_status=False)
            em_session.mount('https://', HTTPAdapter(max_retries=_retry, pool_connections=2, pool_maxsize=2))
        except Exception:
            pass

        def _em_resolve_secid(sym):
            """通过 suggest 接口解析美股 secid（QuoteID 形如 105.AAPL / 107.SPY）。"""
            try:
                r = em_session.get('https://searchapi.eastmoney.com/api/suggest/get',
                                   params={'input': sym, 'type': '14',
                                           'token': 'D43BF722C8E33BDC906FB84D85E329E8',
                                           'count': '8'},
                                   headers=em_headers, timeout=15)
                data = (r.json().get('QuotationCodeTable') or {}).get('Data') or []
                for q in data:
                    if q.get('Code') == sym and q.get('Classify') == 'UsStock':
                        qid = q.get('QuoteID')
                        if qid and qid.startswith(('105.', '106.', '107.')):
                            return qid, (q.get('Name') or sym)
            except Exception:
                pass
            return None, None

        def _em_fetch_kline(secid):
            """拉取日K，返回 (klines_list, name) 或 (None, None)。"""
            beg_date = (datetime.now() - timedelta(days=years * 365)).strftime('%Y%m%d')
            end_date = (datetime.now() + timedelta(days=30)).strftime('%Y%m%d')
            params = {
                'secid': secid,
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
                'klt': '101',   # 日K
                'fqt': '1',     # 前复权
                'beg': beg_date,
                'end': end_date,
            }
            for attempt in range(2):
                try:
                    r = em_session.get('https://push2his.eastmoney.com/api/qt/stock/kline/get',
                                       params=params, headers=em_headers, timeout=20)
                    d = r.json()
                    data = d.get('data') or {}
                    kls = data.get('klines') or []
                    if kls:
                        return kls, (data.get('name') or symbol)
                    # rc==100 且 data 为空表示该 secid 无此标的，需换前缀
                    return None, None
                except Exception:
                    if attempt < 1:
                        time.sleep(2)
                    else:
                        raise
            return None, None

        # 解析 secid：suggest 优先；suggest 未命中时才按 105/107/106 试探。
        # （suggest 命中后若取数失败，多半是端点限流，换前缀无益，直接落腾讯兜底。）
        secid, resolved_name = _em_resolve_secid(symbol)
        klines, asset_name = None, symbol
        if secid:
            klines, asset_name = _em_fetch_kline(secid)
            if resolved_name and (not asset_name or asset_name == symbol):
                asset_name = resolved_name
        else:
            print(f"  suggest 未命中，按 105/107/106 顺序试探...")
            for mk in ('105', '107', '106'):
                klines, asset_name = _em_fetch_kline(f'{mk}.{symbol}')
                if klines:
                    print(f"  命中前缀 {mk}.{symbol}")
                    break
                time.sleep(1)

        if not klines:
            raise ValueError('东方财富返回空数据')

        # klines 格式: "date,open,close,high,low,volume,amount,amplitude"
        rows = []
        for line in klines:
            parts = line.split(',')
            rows.append({
                'date': pd.to_datetime(parts[0]),
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': float(parts[5]) if parts[5] else 0,
            })

        df = pd.DataFrame(rows)
        df = df.dropna()
        df = df.sort_values('date').reset_index(drop=True)
        df.attrs.update(data_source='东方财富(前复权)', price_basis='adjusted_close')

        print(f"成功获取 {len(df)} 条数据 [{asset_name}] (东方财富)")
        print(f"数据范围: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")

        return df, asset_name

    except Exception as e:
        print(f"  东方财富失败: {e}")

    # === 方案3: 腾讯财经美股 K线（east财富不可用时的兜底）===
    # 用 qt.gtimg.cn 解析交易所后缀（usAAPL -> AAPL.OQ），再分页拉 fqkline 前复权日K。
    # 注意：腾讯美股 qfq 不回溯拆股复权（如 AAPL 2020 拆股），ETF 不受影响。
    try:
        print(f"  尝试腾讯财经美股接口...")
        import time
        from datetime import datetime, timedelta
        tx_headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}

        # 1) 解析交易所后缀 + 名称
        tx_code, asset_name, snap_fields = None, symbol, None
        try:
            qr = requests.get(f'https://qt.gtimg.cn/q=us{symbol}', headers=tx_headers, timeout=10)
            f = qr.text.split('~')
            if len(f) > 3:
                if f[1]:
                    asset_name = f[1]
                if '.' in f[2]:
                    tx_code = f[2]   # 如 AAPL.OQ / VOO.AM / MCD.N
                # 快照字段: [3]=最新价 [30]=时间 [32]=涨跌额 [33]=最高 [34]=最低 [5]=今开 [6]=量
                try:
                    snap_fields = {
                        'date': f[30][:10] if len(f) > 30 and len(f[30]) >= 10 else None,
                        'close': float(f[3]),
                        'open': float(f[5]) if f[5] else float(f[3]),
                        'high': float(f[33]) if len(f) > 33 and f[33] else float(f[3]),
                        'low': float(f[34]) if len(f) > 34 and f[34] else float(f[3]),
                        'volume': float(f[6]) if f[6] else 0.0,
                    }
                except (ValueError, IndexError):
                    snap_fields = None
        except Exception:
            pass
        if not tx_code:
            tx_code = symbol       # 退化（部分标的无后缀也能取）

        # 2) 分页拉全量前复权日K（count 上限 ~2000，超了返回空）
        end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        all_rows = []
        for _ in range(12):
            r = requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                             params={'param': f'us{tx_code},day,2000-01-01,{end_date},2000,qfq'},
                             headers=tx_headers, timeout=30)
            d = r.json()
            sd = (d.get('data') or {}).get(f'us{tx_code}') or {}
            arr = sd.get('qfqday') or sd.get('day') or []
            if not arr or not isinstance(arr, list):
                break
            # 腾讯字段顺序: [date, open, close, high, low, volume]
            all_rows = arr + all_rows        # 更早的拼到前面
            if len(arr) < 2000:              # 已到上市起点
                break
            first_date = arr[0][0]
            nd = datetime.strptime(first_date, '%Y-%m-%d') - timedelta(days=1)
            end_date = nd.strftime('%Y-%m-%d')
            time.sleep(0.3)

        if not all_rows:
            raise ValueError('腾讯返回空数据')

        # 3) 去重 + 裁剪到目标年限
        seen, rows = set(), []
        for item in all_rows:
            d_ = item[0]
            if d_ in seen:
                continue
            seen.add(d_)
            try:
                rows.append({
                    'date': pd.to_datetime(d_),
                    'open': float(item[1]),
                    'close': float(item[2]),
                    'high': float(item[3]),
                    'low': float(item[4]),
                    'volume': float(item[5]) if item[5] else 0,
                })
            except (IndexError, ValueError, TypeError):
                continue

        df = pd.DataFrame(rows)
        df = df.dropna()
        df = df.sort_values('date').reset_index(drop=True)
        if not df.empty:
            cutoff = pd.Timestamp(datetime.now() - timedelta(days=years * 365))
            df = df[df['date'] >= cutoff].reset_index(drop=True)

        # 4) 交易日K线滞后补齐: 腾讯 fqkline 日K可能晚一个交易日入库，快照已是最新收盘。
        #    有新数据就用新的 —— 若快照日期晚于历史K最后一天，则把快照追加为最新一根。
        #    注意快照未复权、历史为腾讯qfq，仅用于补最新一根（ETF/近半年无除权时基本一致）。
        if snap_fields and snap_fields.get('date'):
            try:
                last_date = df['date'].max().strftime('%Y-%m-%d') if not df.empty else '1970-01-01'
                snap_date = snap_fields['date']
                if snap_date > last_date and snap_fields.get('close'):
                    append_row = {
                        'date': pd.to_datetime(snap_date),
                        'open': snap_fields['open'],
                        'close': snap_fields['close'],
                        'high': snap_fields['high'],
                        'low': snap_fields['low'],
                        'volume': snap_fields['volume'],
                    }
                    df = pd.concat([df, pd.DataFrame([append_row])], ignore_index=True)
                    df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
                    print(f"  ⚡ 腾讯日K滞后, 快照补齐 {snap_date}: close={snap_fields['close']}")
            except Exception as e:
                print(f"  [补最新一根] 失败: {e}")

        df.attrs.update(data_source='腾讯财经(美股qfq+快照)', price_basis='adjusted_close')

        print(f"成功获取 {len(df)} 条数据 [{asset_name}] (腾讯)")
        print(f"数据范围: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")

        return df, asset_name

    except Exception as e:
        print(f"获取数据失败: {e}")
        return None, symbol


def get_cn_fund_info(fund_code):
    """获取国内基金名称（优先从新浪财经页面获取）"""
    # 方式1: 新浪财经页面（和净值数据同源，最可靠）
    try:
        url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_LSJZ.php?symbol={fund_code}"
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gb2312'
        match = re.search(r'fund_app\.name\s*=\s*["\'](.*?)["\']', resp.text)
        if match:
            return match.group(1)
    except:
        pass

    # 方式2: fundgz 实时估值接口
    try:
        url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/'
        }
        resp = requests.get(url, headers=headers, timeout=10)
        match = re.search(r'"name"\s*:\s*"([^"]+)"', resp.text)
        if match and not match.group(1).startswith('基金'):
            return match.group(1)
    except:
        pass

    # 方式3: 东方财富 pingzhongdata (对场内 ETF/LOF 也能取到 fS_name)
    try:
        url = f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        match = re.search(r'fS_name\s*=\s*"([^"]+)"', resp.text)
        if match and match.group(1) and not match.group(1).startswith('基金'):
            return match.group(1)
    except:
        pass

    # 方式4: 本地 manifest.json 反查兜底（避免兜出 "基金{code}" 占位）
    try:
        import json as _json
        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'result', 'manifest.json'
        )
        with open(manifest_path) as _f:
            _data = _json.load(_f)
        _entries = _data if isinstance(_data, list) else next(
            (v for v in _data.values() if isinstance(v, list)), []
        )
        for _e in _entries:
            if _e.get('symbol') == fund_code:
                _n = _e.get('asset_name') or _e.get('name')
                if _n and not _n.startswith('基金'):
                    return _n
                break
    except:
        pass

    return f"基金{fund_code}"


@retry_on_failure(max_retries=2, delay=5)
def _fetch_sina_fund_history(fund_code, fund_name):
    """从新浪财经获取基金单位/累计净值，失败时回退东方财富 F10。"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': f'https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_LSJZ.php?symbol={fund_code}'
    }

    api_url = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getNav"

    all_data = []
    page = 1
    sina_failed = False
    total_num = 0

    while True:
        params = {
            'symbol': fund_code,
            'datefrom': '',
            'dateto': '',
            'page': page
        }

        try:
            resp = requests.get(api_url, params=params, headers=headers, timeout=30)
            if resp.status_code != 200:
                print(f"新浪API返回状态码 {resp.status_code}，切换到东方财富...")
                sina_failed = True
                break
            data = resp.json()

            result = data.get('result', {})
            result_data = result.get('data', {})
            items = result_data.get('data', [])

            if not items:
                break

            if page == 1:
                total_num = int(result_data.get('total_num', 0))
                print(f"总数据条数: {total_num}")

            for item in items:
                date_str = item.get('fbrq', '').split(' ')[0]
                unit_nav = float(item.get('jjjz', 0))
                acc_nav = float(item.get('ljjz', 0))

                all_data.append({
                    'date': date_str,
                    'unit_nav': unit_nav,
                    'acc_nav': acc_nav,
                    'nav_for_rsi': acc_nav if acc_nav > 0 else unit_nav,
                    'daily_change': 0
                })

            page += 1

        except Exception as e:
            print(f"新浪获取第{page}页数据失败: {e}")
            sina_failed = True
            break

    # 老基金翻页末端偶发超时：已取得绝大多数历史且包含最新页时保留数据，
    # 避免把成功拉取的数千条记录全部丢弃。
    partial_usable = bool(all_data and total_num and len(all_data) >= total_num * 0.9)
    if sina_failed and partial_usable:
        print(f"新浪历史末端不完整，保留已获取 {len(all_data)}/{total_num} 条")
    elif sina_failed or not all_data:
        print(f"使用东方财富备用数据源...")
        return _fetch_eastmoney_fund_history(fund_code, fund_name)

    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates(subset=['date']).reset_index(drop=True)
    df = df.sort_values('date').reset_index(drop=True)
    df['daily_change'] = df['nav_for_rsi'].pct_change() * 100
    source = 'Sina fund NAV (partial history)' if sina_failed else 'Sina fund NAV'
    df.attrs.update(data_source=source, price_basis='cumulative_nav')

    print(f"成功获取 {len(df)} 条历史净值记录")
    print(f"数据范围：{df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")

    return df, fund_name


def _fetch_eastmoney_pingzhongdata_history(fund_code, fund_name):
    """主数据源：获取完整单位/累计净值，技术指标统一使用官方累计净值。"""
    try:
        url = f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/'
        }
        resp = requests.get(url, headers=headers, timeout=15)

        # 单位净值趋势: [{x: timestamp, y: unit_nav, equityReturn: pct, ...}]
        m_nwt = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?\])\s*;', resp.text)
        # 累计净值趋势: [[timestamp, acc_nav], ...]
        m_acw = re.search(r'Data_ACWorthTrend\s*=\s*(\[.*?\])\s*;', resp.text)
        m_inception = re.search(r'fS_clrq\s*=\s*["\']([^"\']+)["\']', resp.text)

        if not m_nwt and not m_acw:
            return None

        all_data = []
        price_basis = 'cumulative_nav'
        expected_records = 0

        # netWorthTrend 提供单位净值，ACWorthTrend 提供官方累计净值。
        if m_nwt:
            arr = json.loads(m_nwt.group(1))
            expected_records = len(arr)
            acc_map = {}
            if m_acw:
                arr_acw = json.loads(m_acw.group(1))
                for item in arr_acw:
                    ts = item[0]
                    d = _eastmoney_date(ts)
                    if item[1] is not None:
                        acc_map[d] = float(item[1])

            acc_coverage = sum(_eastmoney_date(item['x']) in acc_map for item in arr) / len(arr) if arr else 0
            if acc_coverage < 0.95:
                return None

            for item in arr:
                d = _eastmoney_date(item['x'])
                unit_nav = float(item.get('y', 0))
                acc_nav = acc_map.get(d)
                if unit_nav <= 0 or acc_nav is None or acc_nav <= 0:
                    continue
                all_data.append({
                    'date': d,
                    'unit_nav': unit_nav,
                    'acc_nav': acc_nav,
                    'adj_nav': acc_nav,
                    'nav_for_rsi': acc_nav,
                    'daily_change': 0,
                })
        elif m_acw:
            # 只有累计净值，单位净值用累计净值兜底
            arr = json.loads(m_acw.group(1))
            expected_records = len(arr)
            for item in arr:
                d = _eastmoney_date(item[0])
                acc_nav = float(item[1])
                if acc_nav <= 0:
                    continue
                all_data.append({
                    'date': d,
                    'unit_nav': acc_nav,
                    'acc_nav': acc_nav,
                    'adj_nav': acc_nav,
                    'nav_for_rsi': acc_nav,
                    'daily_change': 0
                })

        if not all_data:
            return None

        df = pd.DataFrame(all_data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.drop_duplicates(subset=['date']).reset_index(drop=True)
        df = df.sort_values('date').reset_index(drop=True)
        if expected_records and len(df) < expected_records * 0.95:
            return None
        inception = pd.Timestamp(m_inception.group(1)) if m_inception else None
        inception_gap = (df['date'].min() - inception).days if inception is not None else None
        max_gap_value = df['date'].diff().dt.days.max()
        max_gap = 0 if pd.isna(max_gap_value) else int(max_gap_value)
        if inception_gap is not None and not -7 <= inception_gap <= 45:
            return None
        if max_gap > 45:
            return None
        df['daily_change'] = df['adj_nav'].pct_change() * 100
        df.attrs.update(
            data_source='Eastmoney pingzhongdata', price_basis=price_basis,
            inception_date=inception.strftime('%Y-%m-%d') if inception is not None else None,
            expected_records=expected_records, parsed_records=len(df),
            inception_gap_days=inception_gap, max_gap_days=max_gap,
        )
        print(f"数据范围：{df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")

        return df, fund_name
    except Exception as e:
        print(f"东方财富 pingzhongdata 获取失败: {e}")
        return None


@retry_on_failure(max_retries=2, delay=5)
def _fetch_eastmoney_fund_history(fund_code, fund_name):
    """最终备用：东方财富 F10 JSON 全历史累计净值。"""
    url = 'https://api.fund.eastmoney.com/f10/lsjz'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://fundf10.eastmoney.com/'}
    # API 服务端固定最多返回 20 条；传更大值对部分 ETF 会直接返回空数据。
    page, page_size, total_count, raw_rows = 1, 20, 0, []
    while not total_count or len(raw_rows) < total_count:
        resp = requests.get(url, params={
            'fundCode': fund_code, 'pageIndex': page, 'pageSize': page_size,
            'startDate': '', 'endDate': '', '_': int(time.time() * 1000),
        }, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get('ErrCode') != 0:
            raise RuntimeError(payload.get('ErrMsg') or 'F10 API 返回错误')
        rows = (payload.get('Data') or {}).get('LSJZList') or []
        if not rows:
            break
        total_count = int(payload.get('TotalCount') or 0)
        for item in rows:
            unit = float(item['DWJZ'])
            if unit <= 0:
                continue
            raw_rows.append({
                'date': pd.Timestamp(item['FSRQ']), 'unit_nav': unit,
                'acc_nav': float(item['LJJZ']) if item.get('LJJZ') else None,
                'growth': float(item['JZZZL']) if item.get('JZZZL') not in (None, '') else None,
            })
        page += 1

    if not raw_rows or not total_count or len(raw_rows) != total_count:
        return None

    raw_rows.sort(key=lambda row: row['date'])
    acc_coverage = sum(row['acc_nav'] is not None for row in raw_rows) / len(raw_rows)
    if acc_coverage < 0.95:
        return None
    all_data = []
    for row in raw_rows:
        if row['acc_nav'] is None:
            continue
        acc = row['acc_nav']
        all_data.append({
            'date': row['date'], 'unit_nav': row['unit_nav'], 'acc_nav': acc,
            'adj_nav': acc, 'nav_for_rsi': acc, 'daily_change': 0,
        })

    df = pd.DataFrame(all_data).drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    if len(df) != total_count:
        return None
    df['daily_change'] = df['adj_nav'].pct_change() * 100
    max_gap_value = df['date'].diff().dt.days.max()
    max_gap = 0 if pd.isna(max_gap_value) else int(max_gap_value)
    if max_gap > 45:
        return None
    df.attrs.update(
        data_source='Eastmoney F10 JSON fallback',
        price_basis='cumulative_nav',
        latest_verified=True, expected_records=total_count,
        reference_total_count=total_count, max_gap_days=max_gap,
    )

    print(f"成功获取 {len(df)} 条历史净值记录（东方财富 F10 备用）")
    print(f"数据范围：{df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")

    return df, fund_name


def _fetch_eastmoney_nav_reference(fund_code):
    """用东方财富 F10 独立核对最新净值和总记录数。"""
    try:
        url = 'https://api.fund.eastmoney.com/f10/lsjz'
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://fundf10.eastmoney.com/'}
        resp = requests.get(url, params={
            'fundCode': fund_code, 'pageIndex': 1, 'pageSize': 30,
            'startDate': '', 'endDate': '', '_': int(time.time() * 1000),
        }, headers=headers, timeout=20)
        payload = resp.json()
        rows = (payload.get('Data') or {}).get('LSJZList') or []
        if payload.get('ErrCode') != 0 or not rows:
            return None
        parsed_rows = []
        for item in reversed(rows):
            parsed_rows.append({
                'date': pd.Timestamp(item['FSRQ']), 'unit_nav': float(item['DWJZ']),
                'acc_nav': float(item['LJJZ']) if item.get('LJJZ') else None,
                'daily_change': float(item['JZZZL']) if item.get('JZZZL') not in (None, '') else None,
            })
        row = parsed_rows[-1]
        return {
            'date': row['date'].strftime('%Y-%m-%d'), 'unit_nav': row['unit_nav'],
            'acc_nav': row['acc_nav'], 'rows': parsed_rows,
            'total_count': int(payload.get('TotalCount') or 0),
        }
    except Exception as e:
        print(f"东方财富 F10 完整性校验失败: {e}")
        return None


def _append_eastmoney_tail(frame, reference):
    """用同一供应商 F10 的官方累计净值补齐静态历史源最新尾部。"""
    attrs = dict(frame.attrs)
    latest_date = frame['date'].max()
    tail = [row for row in reference.get('rows', []) if row['date'] > latest_date]
    if not tail:
        return frame
    if reference.get('total_count') and len(frame) + len(tail) != reference['total_count']:
        return None

    rows = []
    prev = frame.iloc[-1]
    prev_acc = float(prev['acc_nav'])
    for item in tail:
        unit = item['unit_nav']
        if item['acc_nav'] is None:
            return None
        acc = item['acc_nav']
        adj = acc
        daily_change = (acc / prev_acc - 1) * 100
        if min(unit, acc, adj) <= 0:
            return None
        rows.append({
            'date': item['date'], 'unit_nav': unit, 'acc_nav': acc,
            'adj_nav': adj, 'nav_for_rsi': adj,
            'daily_change': daily_change,
        })
        prev_acc = acc

    result = pd.concat([frame, pd.DataFrame(rows)], ignore_index=True)
    result.attrs.update(attrs)
    result.attrs['data_source'] = f"{attrs.get('data_source', 'Eastmoney')} + F10 tail"
    return result


def get_gaoduan_fund_info(fund_code):
    """高端理财/私募基金名称（东方财富 gaoduan 详情页）。

    注意：页面里的 `fundname` 变量是底层持仓基金名（如"银华信用四季红债券"），
    不是产品本身的名字；产品正式名在 <title> 里，如"国泰君安君享大类资产全天候1号"。
    """
    url = f'https://fund.eastmoney.com/gaoduan/{fund_code}.html'
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.encoding = 'utf-8'
        text = resp.text
        # 产品正式名：<title>国泰君安君享大类资产全天候1号(953831)主页 ...
        m = re.search(r'<title>([^<(]+?)\(\d+\)', text)
        if m and m.group(1).strip():
            return m.group(1).strip()
        # 兜底：底层持仓基金名（不理想，但好过纯代码）
        m = re.search(r"fundname\s*=\s*['\"]([^'\"]+)['\"]", text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return f"私募基金{fund_code}"


def fetch_gaoduan_fund_history(fund_code):
    """高端理财/私募基金历史净值：东方财富 gaoduan 通道 PinzhongF10DataApi。

    常规 lsjz/pingzhongdata 接口对高端理财标的（如 953831）返回空，只能走此通道，
    可一次拉到成立至今全量净值。口径：累计净值(ACCNAV)用于 RSI/EMA/布林带，与
    A股基金一致。
    """
    fund_name = get_gaoduan_fund_info(fund_code)
    print(f"正在获取高端理财/私募基金 {fund_code}（{fund_name}）的历史净值数据...")
    url = 'https://fund.eastmoney.com/gaoduan/PinzhongF10DataApi.aspx'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': f'https://fund.eastmoney.com/gaoduan/flowf12{fund_code}.html',
    }
    page, page_size, all_rows = 1, 10000, []
    while True:
        params = {
            'type': 'lsjz', 'fc': fund_code, 'pageindex': page,
            'pagesize': str(page_size), 'lsjzSDate': '', 'lsjzEDate': '',
            'r': str(int(time.time() * 1000)),
        }
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        m = re.search(r'var\s+jzData\s*=\s*(\{.*\})', resp.text, re.S)
        if not m:
            break
        try:
            payload = json.loads(m.group(1))
        except Exception:
            break
        if payload.get('ErrCode') not in (0, None):
            break
        rows = payload.get('Datas') or []
        if not rows:
            break
        for item in rows:
            try:
                nav = float(item['NAV'])
                acc = float(item['ACCNAV']) if item.get('ACCNAV') not in (None, '') else nav
            except (KeyError, ValueError, TypeError):
                continue
            if nav <= 0 or acc <= 0:
                continue
            all_rows.append({
                'date': pd.Timestamp(item['PDATE']),
                'unit_nav': nav, 'acc_nav': acc,
            })
        total_pages = int(payload.get('Pages') or 1)
        if page >= total_pages or len(rows) < page_size:
            break
        page += 1

    if len(all_rows) < 15:
        print(f"高端理财 {fund_code} 净值记录不足（{len(all_rows)} 条）")
        return None

    df = pd.DataFrame(all_rows).drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    df['adj_nav'] = df['acc_nav']
    df['nav_for_rsi'] = df['adj_nav']
    df['daily_change'] = df['adj_nav'].pct_change() * 100
    gap = df['date'].diff().dt.days.max() if len(df) > 1 else 0
    df.attrs.update(
        data_source='Eastmoney gaoduan PinzhongF10DataApi',
        price_basis='cumulative_nav',
        latest_verified=True,
        max_gap_days=0 if pd.isna(gap) else int(gap),
    )
    print(f"成功获取 {len(df)} 条历史净值记录（东方财富高端理财通道）")
    print(f"数据范围：{df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")
    return df, fund_name


def fetch_cn_fund_history(fund_code):
    """A 股基金：东方财富完整单源优先，失败后整源切换新浪/F10。"""
    def valid_history(result):
        if result is None or result[0] is None:
            return False
        frame = result[0]
        required = {'date', 'unit_nav', 'acc_nav', 'adj_nav'}
        if len(frame) < 30 or not required.issubset(frame.columns):
            return False
        if frame['date'].duplicated().any() or not frame['date'].is_monotonic_increasing:
            return False
        if frame[['unit_nav', 'acc_nav', 'adj_nav']].isna().any().any():
            return False
        if (frame[['unit_nav', 'acc_nav', 'adj_nav']] <= 0).any().any():
            return False
        return (pd.Timestamp.now().normalize() - frame['date'].max().normalize()).days <= 14

    fund_name = get_cn_fund_info(fund_code)
    print(f"正在获取国内基金 {fund_code}（{fund_name}）的历史净值数据...")
    result = _fetch_eastmoney_pingzhongdata_history(fund_code, fund_name)
    reference = _fetch_eastmoney_nav_reference(fund_code) if valid_history(result) else None
    if result is not None:
        result[0].attrs['latest_verified'] = False
    if reference:
        frame = _append_eastmoney_tail(result[0], reference)
        if frame is None:
            result = None
        else:
            result = (frame, result[1])
    if reference and result:
        frame = result[0]
        latest = frame.iloc[-1]
        result_matches_reference = (
            latest['date'].strftime('%Y-%m-%d') == reference['date']
            and abs(float(latest['unit_nav']) - reference['unit_nav']) < 1e-6
            and (not reference['total_count'] or len(frame) == reference['total_count'])
        )
        frame.attrs.update(
            latest_verified=result_matches_reference,
            reference_total_count=reference['total_count'],
            reference_latest_date=reference['date'],
        )
        if not result_matches_reference:
            result = None
    if not valid_history(result):
        print("东方财富完整净值不可用，整源切换新浪累计净值...")
        result = _fetch_sina_fund_history(fund_code, fund_name)
    if result is None or result[0] is None:
        return None
    df, name = result
    df = df.copy()
    df['adj_nav'] = df['acc_nav']
    df.attrs['price_basis'] = 'cumulative_nav'
    df['nav_for_rsi'] = df['adj_nav']
    df['daily_change'] = df['adj_nav'].pct_change() * 100
    if not valid_history((df, name)):
        print("基金净值完整性校验失败")
        return None
    return df, name


def get_hk_fund_name(fund_code):
    """获取香港基金名称"""
    url = f"https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_LSJZ.php?symbol={fund_code}"
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.encoding = 'gb2312'
        match = re.search(r'fund_app\.name\s*=\s*["\']([^"\']+)["\']', resp.text)
        if match:
            return match.group(1)
    except:
        pass

    return f"香港基金{fund_code}"


def fetch_hk_fund_history(fund_code):
    """获取香港基金历史净值数据"""
    fund_name = get_hk_fund_name(fund_code)
    print(f"正在获取香港基金 {fund_code}（{fund_name}）的历史净值数据...")
    return _fetch_sina_fund_history(fund_code, fund_name)


def get_cn_stock_name(stock_code):
    """获取A股股票名称"""
    # 确定市场前缀
    if stock_code.startswith('6'):
        market = 'sh'
    else:
        market = 'sz'

    try:
        # 从腾讯接口获取股票名称
        url = f"https://web.sqt.gtimg.cn/q={market}{stock_code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        # 返回格式: v_sh600900="1~长江电力~600900~..."
        match = re.search(r'~([^~]+)~', resp.text)
        if match:
            return match.group(1)
    except:
        pass

    return f"股票{stock_code}"


def get_cn_stock_realtime(stock_code):
    """获取A股股票实时行情（盘中数据）

    Args:
        stock_code: 股票代码（如 600900）

    Returns:
        dict: 包含实时行情数据，或 None（如果获取失败或非交易时间）
        {
            'date': '2026-04-15',
            'open': 26.41,
            'close': 26.55,  # 当前价格
            'high': 26.67,
            'low': 26.36,
            'volume': 970566,
            'prev_close': 26.42,  # 昨收
            'is_trading': True  # 是否交易中
        }
    """
    # 确定市场前缀
    if stock_code.startswith('6'):
        market = 'sh'
    else:
        market = 'sz'

    try:
        # 使用腾讯实时行情接口
        url = f"https://web.sqt.gtimg.cn/q={market}{stock_code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        content = resp.content.decode('gbk')

        # 解析格式: v_sh600900="1~长江电力~600900~当前价~昨收~今开~成交量~..."
        if '~' not in content:
            return None

        parts = content.split('~')
        if len(parts) < 35:
            return None

        # 提取字段
        current_price = float(parts[3]) if parts[3] else 0
        prev_close = float(parts[4]) if parts[4] else 0
        today_open = float(parts[5]) if parts[5] else 0
        volume = int(parts[6]) if parts[6] else 0
        high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
        low = float(parts[34]) if len(parts) > 34 and parts[34] else 0
        time_str = parts[30] if len(parts) > 30 else ''  # 格式: 20260415161409

        # 解析日期
        if time_str and len(time_str) >= 8:
            date_str = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
        else:
            date_str = pd.Timestamp.now().strftime('%Y-%m-%d')

        # 判断是否交易中（当前价格不为0且有成交量）
        is_trading = current_price > 0 and volume > 0

        return {
            'date': date_str,
            'open': today_open,
            'close': current_price,
            'high': high,
            'low': low,
            'volume': volume,
            'prev_close': prev_close,
            'is_trading': is_trading
        }

    except Exception as e:
        print(f"获取实时行情失败: {e}")
        return None


@retry_on_failure(max_retries=3, delay=10)
def fetch_cn_stock_history(stock_code, years=20):
    """获取A股股票历史K线数据（使用新浪接口，单次拉取完整历史 + 前复权）

    Args:
        stock_code: 股票代码（如 600900）
        years: 获取最近N年的数据，默认20年获取全部历史

    Returns:
        (DataFrame, stock_name) 或 None
    """
    stock_name = get_cn_stock_name(stock_code)
    print(f"正在获取A股股票 {stock_code}（{stock_name}）的历史K线数据...")

    # 确定市场前缀
    market = 'sh' if stock_code.startswith('6') else 'sz'

    # 一次性拉取全量前复权日K线（Sina 支持 5000+ 条，覆盖 20 年）
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        'symbol': f'{market}{stock_code}',
        'scale': '240',
        'ma': 'no',
        'datalen': '10000',
    }
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        raw_data = resp.json()
    except Exception as e:
        print(f"获取数据失败: {e}")
        return None

    if not raw_data or not isinstance(raw_data, list):
        print("获取数据失败: 返回格式异常")
        return None

    # 转换为 DataFrame（Sina 返回格式: day, open, high, low, close, volume）
    all_data = []
    for d in raw_data:
        try:
            all_data.append([
                d['day'],
                float(d['open']),
                float(d['close']),
                float(d['high']),
                float(d['low']),
                float(d['volume']),
            ])
        except (KeyError, ValueError):
            continue

    if not all_data:
        print("获取数据失败: 无有效数据")
        return None

    df = pd.DataFrame(all_data, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    df = df.sort_values('date').dropna().reset_index(drop=True)
    df.attrs.update(data_source='Sina CN stock K-line', price_basis='close')

    print(f"成功获取 {len(df)} 条历史K线数据（前复权）")
    print(f"数据范围：{df['date'].min().strftime('%Y-%m-%d')} 至 {df['date'].max().strftime('%Y-%m-%d')}")

    return df, stock_name


def fetch_data(symbol, data_type):
    """根据类型获取数据，返回 (DataFrame, price_col, asset_name)"""
    if data_type == 'us_stock':
        result = fetch_us_stock_history(symbol, years=20)
        if result is None:
            return None, None, None
        df, asset_name = result
        if df is None or len(df) == 0:
            return None, None, None
        df = apply_start_override(symbol, df)
        for p in [7, 14]:
            df[f'RSI_{p}'] = calculate_rsi(df['close'].tolist(), p)
        return df, 'close', asset_name

    elif data_type == 'hk_fund':
        result = fetch_hk_fund_history(symbol)
        if result is None or len(result[0]) == 0:
            return None, None, None
        df, fund_name = result
        df = apply_start_override(symbol, df)
        for p in [7, 14]:
            df[f'RSI_{p}'] = calculate_rsi(df['nav_for_rsi'].tolist(), p)
        return df, 'nav_for_rsi', fund_name

    elif data_type == 'cn_fund':
        result = fetch_cn_fund_history(symbol)
        if result is None:
            return None, None, None
        df, fund_name = result
        if len(df) == 0:
            return None, None, None
        df = apply_start_override(symbol, df)
        for p in [7, 14]:
            df[f'RSI_{p}'] = calculate_rsi(df['nav_for_rsi'].tolist(), p)
        return df, 'adj_nav', fund_name

    elif data_type == 'cn_stock':
        result = fetch_cn_stock_history(symbol)
        if result is None:
            return None, None, None
        df, stock_name = result
        if len(df) == 0:
            return None, None, None
        df = apply_start_override(symbol, df)
        for p in [7, 14]:
            df[f'RSI_{p}'] = calculate_rsi(df['close'].tolist(), p)
        return df, 'close', stock_name

    elif data_type == 'private_fund':
        # 高端理财/私募基金：走东方财富 gaoduan 专用通道
        result = fetch_gaoduan_fund_history(symbol)
        if result is None or len(result[0]) == 0:
            return None, None, None
        df, fund_name = result
        df = apply_start_override(symbol, df)
        for p in [7, 14]:
            df[f'RSI_{p}'] = calculate_rsi(df['nav_for_rsi'].tolist(), p)
        return df, 'adj_nav', fund_name

    elif data_type == 'cn_bond':
        # 纯债基金：走基金数据拉取逻辑
        print(f"正在获取纯债基金 {symbol} 的历史净值数据...")
        result = fetch_cn_fund_history(symbol)
        if result is not None and result[0] is not None and len(result[0]) > 0:
            df, fund_name = result
            df = apply_start_override(symbol, df)
            for p in [7, 14]:
                df[f'RSI_{p}'] = calculate_rsi(df['nav_for_rsi'].tolist(), p)
            return df, 'adj_nav', fund_name
        print(f"⚠️ 纯债基金 {symbol} 数据获取失败")
        return None, None, None

    elif data_type == 'cn_auto':
        # 自动检测：先尝试基金，再尝试股票
        print(f"正在自动检测 {symbol} 的资产类型...")
        
        # 先尝试基金
        result = fetch_cn_fund_history(symbol)
        if result is not None and result[0] is not None and len(result[0]) > 0:
            df, fund_name = result
            df = apply_start_override(symbol, df)
            for p in [7, 14]:
                df[f'RSI_{p}'] = calculate_rsi(df['nav_for_rsi'].tolist(), p)
            return df, 'adj_nav', fund_name
        
        # 再尝试股票
        result = fetch_cn_stock_history(symbol)
        if result is not None and result[0] is not None and len(result[0]) > 0:
            df, stock_name = result
            df = apply_start_override(symbol, df)
            for p in [7, 14]:
                df[f'RSI_{p}'] = calculate_rsi(df['close'].tolist(), p)
            return df, 'close', stock_name

        # 最后尝试高端理财/私募通道（代码不在常规基金库的情况，如高端理财 953831）
        result = fetch_gaoduan_fund_history(symbol)
        if result is not None and result[0] is not None and len(result[0]) > 0:
            df, fund_name = result
            df = apply_start_override(symbol, df)
            for p in [7, 14]:
                df[f'RSI_{p}'] = calculate_rsi(df['nav_for_rsi'].tolist(), p)
            return df, 'adj_nav', fund_name

        return None, None, None

    return None, None, None
