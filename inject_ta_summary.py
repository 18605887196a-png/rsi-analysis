#!/usr/bin/env python3
"""将已有的 full_ta.json 注入 embedded_data.js，生成结构化技术摘要和报告。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from technical_analysis import build_dashboard_bollinger, format_technical_report

RESULT_DIR = os.path.join(os.path.dirname(__file__), 'result')
EMBEDDED_JS = os.path.join(RESULT_DIR, 'embedded_data.js')
BACKUP_JS = os.path.join(RESULT_DIR, 'embedded_data.js.bak')

def load_funds():
    with open(EMBEDDED_JS, 'r', encoding='utf-8') as f:
        content = f.read()
    json_str = content.split('var EMBEDDED_FUNDS = ', 1)[1].rstrip().rstrip(';')
    return json.loads(json_str)

def save_funds(funds):
    with open(EMBEDDED_JS, 'w', encoding='utf-8') as f:
        f.write('var EMBEDDED_FUNDS = ')
        json.dump(funds, f, ensure_ascii=False)
        f.write(';\n')

def main():
    # 备份
    if os.path.exists(EMBEDDED_JS) and not os.path.exists(BACKUP_JS):
        import shutil
        shutil.copy2(EMBEDDED_JS, BACKUP_JS)
        print(f'已备份到 {BACKUP_JS}')

    funds = load_funds()
    print(f'加载 {len(funds)} 个基金', flush=True)
    updated = 0

    for idx, fund in enumerate(funds):
        symbol = fund['symbol']
        name = fund.get('name', fund.get('asset_name', symbol))
        # 确保 name 和 asset_name 双向同步
        if name and not fund.get('name'):
            fund['name'] = name
        if name and not fund.get('asset_name'):
            fund['asset_name'] = name
        data_type = fund.get('data_type', '')
        # 可选过滤：通过环境变量 INJECT_ONLY_US=1 只处理美股，
        # 或 INJECT_ONLY_SYMBOLS="SPYM,DIA" 只处理指定标的(逗号分隔)。
        only_us = os.environ.get('INJECT_ONLY_US')
        only_symbols = os.environ.get('INJECT_ONLY_SYMBOLS')
        if only_us and data_type != 'us_stock':
            continue
        if only_symbols and symbol not in [s.strip() for s in only_symbols.split(',')]:
            continue
        # 文件名有类型前缀: fund_ / us_stock_ / cn_stock_ / hk_fund_
        type_prefix = {
            'us_stock': 'us_stock_',
            'cn_stock': 'cn_stock_',
            'hk_fund': 'hk_fund_',
        }.get(data_type, 'fund_')
        ta_file = os.path.join(RESULT_DIR, f'{type_prefix}{symbol}_full_ta.json')

        if not os.path.exists(ta_file):
            continue

        print(f'[{idx+1}/{len(funds)}] {symbol} ({name})...', flush=True)

        with open(ta_file, 'r', encoding='utf-8') as f:
            ta_data = json.load(f)

        # 扁平结构，直接从 ta_data 取
        signal_summary = ta_data.get('signal_summary', {})

        # 生成结构化摘要
        changes = ta_data.get('change_stats', {})
        sr = ta_data.get('support_resistance', {})
        summary = {
            'overall': signal_summary.get('overall', '中性'),
            'bull': signal_summary.get('bull', 0),
            'bear': signal_summary.get('bear', 0),
            'details': signal_summary.get('details', []),
            'rsi_zone': (ta_data.get('rsi') or {}).get('zone', ''),
            'macd_signal': (ta_data.get('macd') or {}).get('signal', ''),
            'ma_alignment': ta_data.get('ma_alignment', ''),
            'boll_position': (ta_data.get('bollinger') or {}).get('position', ''),
            'kdj_signal': (ta_data.get('kdj') or {}).get('signal', '') or (ta_data.get('kdj') or {}).get('zone', ''),
            'stoch_zone': (ta_data.get('stoch') or {}).get('zone', ''),
            'cci_zone': (ta_data.get('cci') or {}).get('zone', ''),
            'wr_zone': (ta_data.get('williams_r') or {}).get('zone', ''),
            'obv_trend': (ta_data.get('obv') or {}).get('trend', ''),
            'adx_value': (ta_data.get('adx') or {}).get('value'),
            'adx_trend': (ta_data.get('adx') or {}).get('trend_strength', ''),
            'adx_direction': (ta_data.get('adx') or {}).get('direction', ''),
            'mfi_value': (ta_data.get('mfi') or {}).get('value'),
            'mfi_zone': (ta_data.get('mfi') or {}).get('zone', ''),
            'trend_direction': (ta_data.get('trend_strength') or {}).get('direction', ''),
            'trend_strength': (ta_data.get('trend_strength') or {}).get('strength', ''),
            'rsi_divergence': '底背离' if (ta_data.get('rsi_divergence') or {}).get('bullish') else '顶背离' if (ta_data.get('rsi_divergence') or {}).get('bearish') else '',
            'volume_price_pattern': (ta_data.get('volume_price') or {}).get('pattern', ''),
            'change_5d': changes.get('5d'),
            'change_20d': changes.get('20d'),
            'change_50d': changes.get('50d'),
            'change_200d': changes.get('200d'),
            'max_drawdown': changes.get('max_drawdown'),
            'swing_high': sr.get('swing_high'),
            'swing_low': sr.get('swing_low'),
            'ema60_value': (ta_data.get('ema60') or ta_data.get('ma60') or {}).get('value'),
            'ema60_distance': (ta_data.get('ema60') or ta_data.get('ma60') or {}).get('distance_pct'),
            'ema60_price_source': (ta_data.get('ema60') or ta_data.get('ma60') or {}).get('price_source'),
        }
        fund['full_ta_summary'] = summary

        fund['bollinger'] = build_dashboard_bollinger(
            ta_data, (fund.get('latest') or {}).get('rsi', 50))

        # 生成技术分析报告
        report = format_technical_report(ta_data, name)

        fund['full_ta_report'] = report

        # 每10个保存一次
        if (updated + 1) % 10 == 0:
            save_funds(funds)
            print(f'  >>> 中间保存 {updated+1}/{len(funds)} <<<', flush=True)

        updated += 1

    save_funds(funds)
    print(f'\n注入 {updated}/{len(funds)} 个基金', flush=True)
    print(f'已更新 {EMBEDDED_JS}', flush=True)

if __name__ == '__main__':
    main()
