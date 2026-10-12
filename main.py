#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSI Analysis Skill - 入口脚本

用法:
    python3 main.py <代码>           # 完整分析并输出报告
    python3 main.py SPYM --json      # 输出 JSON 格式
    python3 main.py 512890 --no-file # 不保存文件
    python3 main.py 512890 --rsi 37  # 指定 RSI 值进行历史场景分析
    python3 main.py --score          # 对所有基金进行多维评分
    python3 main.py 515300 --score   # 对单只基金评分
"""

import sys
import os
import json
import argparse

# 添加 lib 目录到 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, 'lib')
RESULT_DIR = os.path.join(SCRIPT_DIR, 'result')
sys.path.insert(0, LIB_DIR)

from analyzer import RSIAnalyzer
from fund_scoring import score_fund, score_all_funds, format_console_output, generate_markdown_report, update_fund_json_with_scoring
from technical_analysis import run_technical_analysis, format_technical_report
from data_fetcher import detect_type, fetch_data


def run_scoring(symbols=None, open_report=False):
    """执行评分"""
    if symbols:
        # 单只基金评分
        results = []
        for symbol in symbols:
            json_files = []
            for prefix in ['asset', 'fund', 'hk_fund', 'cn_stock', 'cn_fund', 'us_stock', 'private']:
                p = os.path.join(RESULT_DIR, f'{prefix}_{symbol}_rsi.json')
                if os.path.exists(p):
                    json_files.append(p)
            if not json_files:
                print(f"[警告] 未找到 {symbol} 的分析数据，请先运行完整分析")
                continue
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
                    print(f"  评分失败 {symbol}: {e}")
    else:
        # 批量评分
        print("正在对所有基金进行多维评分...")
        results = score_all_funds(RESULT_DIR)

    if not results:
        print("未找到可评分的基金数据")
        return

    # 控制台输出
    print(format_console_output(results))

    # 写回 JSON
    update_fund_json_with_scoring(RESULT_DIR, results)

    # 生成 Markdown 报告
    report_path = os.path.join(RESULT_DIR, 'fund_scoring_report.md')
    generate_markdown_report(results, report_path)
    print(f"\n📄 评分报告: {report_path}")

    # 更新 manifest / data.js / embedded_data.js
    RSIAnalyzer.update_manifest(RESULT_DIR)
    print("✅ data.js / embedded_data.js 已更新")

    # 默认只生成报告并输出路径；仅在用户显式请求时打开网页看板。
    html_path = os.path.join(RESULT_DIR, 'index.html')
    if open_report and os.path.exists(html_path):
        from pathlib import Path
        import webbrowser
        webbrowser.open(Path(html_path).resolve().as_uri())
        print(f"🌐 网页报告已打开: {html_path}")
    elif os.path.exists(html_path):
        print(f"🌐 网页报告: {html_path}")


def main():
    parser = argparse.ArgumentParser(description='RSI 技术指标分析')
    parser.add_argument('symbol', nargs='?', help='资产代码（美股/基金代码）')
    parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    parser.add_argument('--no-file', action='store_true', help='不保存文件')
    parser.add_argument('--rsi', type=float, help='手动指定 RSI 值，进行历史场景分析')
    parser.add_argument('--score', action='store_true', help='对基金进行多维评分（不传代码则评分全部）')
    parser.add_argument('--full', action='store_true', help='全面技术分析（MACD/KDJ/ATR/OBV/CCI/Williams/布林带/均线系统/斐波那契）')
    parser.add_argument('--open', action='store_true', help='评分后尝试在默认浏览器打开网页报告')
    args = parser.parse_args()

    # 评分模式
    if args.score:
        symbols = [args.symbol] if args.symbol else None
        run_scoring(symbols, open_report=args.open)
        return

    if not args.symbol:
        parser.print_help()
        sys.exit(1)

    # 全面技术分析模式
    if args.full:
        symbol = args.symbol.strip().upper()
        data_type, symbol = detect_type(symbol)
        print(f'正在获取 {symbol} 的数据进行全面技术分析...', file=sys.stderr)
        fetch_result = fetch_data(symbol, data_type)
        if fetch_result[0] is None:
            print(f'[错误] 无法获取 {symbol} 的数据', file=sys.stderr)
            sys.exit(1)
        df, price_col, asset_name = fetch_result
        # 也计算 RSI 用于综合信号
        result = run_technical_analysis(df, price_col, data_type)
        result['symbol'] = symbol
        result['asset_name'] = asset_name

        report = format_technical_report(result, asset_name)

        # 保存文件
        if not args.no_file:
            type_prefixes = {
                'us_stock': 'us_stock', 'cn_stock': 'cn_stock',
                'cn_fund': 'fund', 'hk_fund': 'hk_fund', 'cn_auto': 'fund',
                'private_fund': 'fund',
            }
            prefix = type_prefixes.get(data_type, 'asset')
            report_path = os.path.join(RESULT_DIR, f'{prefix}_{symbol}_full_ta_report.md')
            json_path = os.path.join(RESULT_DIR, f'{prefix}_{symbol}_full_ta.json')
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            print(report)
            print(f'\n📁 报告已保存: {report_path}', file=sys.stderr)
            print(f'📁 JSON已保存: {json_path}', file=sys.stderr)
        else:
            print(report)
        return

    # 创建分析器
    analyzer = RSIAnalyzer(args.symbol)

    # 场景分析模式：指定 RSI 值
    if args.rsi is not None:
        result = analyzer.analyze_scenario(args.rsi)

        if result is None:
            print(f"[错误] 无法获取 {args.symbol} 的数据", file=sys.stderr)
            sys.exit(1)

        if result.get('match_count', 0) == 0:
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(analyzer.format_scenario_report(result))
            sys.exit(0)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            # 保存文件
            if not args.no_file:
                json_path, report_path = analyzer.save_scenario_files(result)
                # 读取 md 文件并原样输出
                with open(report_path, 'r', encoding='utf-8') as f:
                    print(f.read())
                print(f"\n📁 场景分析文件已保存:", file=sys.stderr)
                print(f"   JSON: {json_path}", file=sys.stderr)
                print(f"   报告: {report_path}", file=sys.stderr)
            else:
                print(analyzer.format_scenario_report(result))
        return

    # 完整分析模式（原逻辑）
    result = analyzer.analyze()

    if result is None:
        print(f"[错误] 无法获取 {args.symbol} 的数据", file=sys.stderr)
        sys.exit(1)

    # 输出结果
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 保存文件
        if not args.no_file:
            json_path, report_path, chart_path = analyzer.save_files(result)
            # 更新 manifest + data.js
            result_dir = os.path.dirname(json_path)
            RSIAnalyzer.update_manifest(result_dir)
            # 读取 md 文件并原样输出
            with open(report_path, 'r', encoding='utf-8') as f:
                print(f.read())
            # 图表路径提示
            if chart_path:
                print(f"\n📊 图表已生成: {chart_path}", file=sys.stderr)
            # HTML 报告页路径
            html_path = os.path.join(result_dir, 'index.html')
            if os.path.exists(html_path):
                print(f"\n🌐 网页报告: {html_path}", file=sys.stderr)
                print(f"   用 open \"{html_path}\" 打开查看所有基金", file=sys.stderr)
        else:
            report = analyzer.format_report(result)
            print(report)


if __name__ == '__main__':
    main()
