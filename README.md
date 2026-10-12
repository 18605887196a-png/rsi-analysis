# RSI Analyzer - 基金/股票 RSI 多维分析系统

支持 A股基金、A股股票、港股基金、美股 的 RSI 历史分位分析、布林带信号、回测胜率、Sell Put 目标价预测，以及多维评分系统。

## 快速开始

### 1. 安装依赖

```bash
pip3 install requests pandas matplotlib
```

### 2. 单只分析

```bash
# A股基金
python3 main.py 515300

# A股股票
python3 main.py 600900

# 港股基金
python3 main.py 968049

# 美股
python3 main.py JEPI
python3 main.py DIVO
```

### 3. 批量更新 + 评分

```bash
# 对 result/ 下所有已有 JSON 重新评分
python3 main.py --score

# 单只基金评分
python3 main.py 515300 --score
```

### 4. 批量更新脚本

```bash
# 从 result/fund_watchlist.json 读取关注标的，单次取数后统一计算
bash batch_update.sh
```

## 功能说明

| 功能 | 说明 |
|------|------|
| RSI(14) 计算 | Wilder's Smoothing 方法 |
| 历史分位 | 当前 RSI 在历史中的百分位排名 |
| 布林带信号 | MA20 ± 2σ，%B 指标判断超买/超卖 |
| EMA60 | 与 RSI/布林带使用同一复权价格口径 |
| 回测胜率 | 超卖区间买入持有 N 天胜率、超买区间持有 N 天回撤概率 |
| Sell Put 预测 | 基于当前 RSI 模拟持续下跌，预测目标 RSI 对应的价位 |
| 多维评分 | 机会分(0-100) + 风险分(0-100) → 操作建议(强力买入/买入/关注/持有/减仓/强力减仓) |
| Dashboard | result/index.html 可视化看板，支持分类筛选、排序、详情查看 |

## 支持的资产类型

| 代码规则 | 类型 | 数据源 |
|---------|------|--------|
| 51xxxx / 15xxxx / 16xxxx / 18xxxx | A股基金/ETF | 新浪单位/累计净值 + 东方财富再投资净值 |
| 60xxxx / 30xxxx / 68xxxx | A股股票 | 腾讯行情(前复权) |
| 00xxxx | 自动检测(基金/股票) | 先尝试基金，再尝试股票 |
| 968xxx | 港股基金 | 新浪财经 |
| 纯字母(如 JEPI) | 美股 | Yahoo Finance(前复权) |

## 产物说明

| 文件 | 位置 | 说明 |
|------|------|------|
| JSON 数据 | `result/{type}_{code}_rsi.json` | 完整分析数据 |
| RSI 图表 | `result/{type}_{code}_rsi_chart.png` | RSI 走势图 |
| Markdown 报告 | `result/{type}_{code}_rsi_report.md` | 文字版报告 |
| Dashboard | `result/index.html` | 可视化看板(自动嵌入数据) |
| 评分报告 | `result/fund_scoring_report.md` | 全量评分汇总 |
| 数据清单 | `result/manifest.json` | 所有标的元数据 |
| 评分数据 | `result/data.js` / `result/embedded_data.js` | Dashboard 数据源 |

## 文件结构

```
rsi-analysis/
├── main.py                 # 入口脚本
├── batch_update.sh         # 批量更新脚本
├── .python-version         # Python 版本锁定
├── lib/
│   ├── data_fetcher.py     # 数据获取(多数据源)
│   ├── analyzer.py         # RSI 分析核心
│   ├── chart_generator.py  # 图表生成
│   └── fund_scoring.py     # 多维评分系统
└── result/                 # 分析结果(自动生成)
    ├── index.html          # Dashboard
    ├── *_rsi.json          # 各标的分析数据
    ├── *_rsi_chart.png     # 各标的RSI图表
    └── *_rsi_report.md     # 各标的文字报告
```

## 注意事项

- A股/港股数据来自新浪财经/东方财富/腾讯，美股来自 Yahoo Finance，均为免费接口，请勿高频请求
- 基金优先使用再投资/复权净值；不足时整段回退累计净值，单位净值仅展示
- 美股开高低收统一调整到 Adj Close 口径
- RSI、EMA60、布林带、回测与技术分析使用同一批数据快照
- 批量更新仅运行行情/净值、RSI、技术指标、报告与图表，不调用 LLM 服务
