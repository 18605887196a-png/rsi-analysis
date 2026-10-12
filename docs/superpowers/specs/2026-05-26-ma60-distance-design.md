# MA60 距离能力设计文档

**日期**：2026-05-26
**作者**：rsi-analysis skill
**状态**：待实现

## 背景

面板现有指标：RSI、历史分位、当日涨跌、净值。
缺少一个**当前价距离 60 日均线的偏离度**指标，用于辅助判断标的相对于近期 3 个月趋势的位置。

## 目标

每只标的卡片新增一格：**vs MA60**，显示当前价相对 SMA60 的偏离百分比（正数偏高、负数偏低）。

## 不做什么 (YAGNI)

- 不做 MA60 走势图、不做单独图表区
- 不做 zone 着色分档（只用现有涨跌色，红正绿负）
- 不重算历史 RSI、不改 RSI 算法
- 不影响美股/A股股票/港股口径（这次不改）

## 价格口径选择

| 资产类型 | MA60 用什么价 | 原因 |
|---|---|---|
| A股基金 | **复权净值**（`adj_nav` = `equityReturn` 累乘） | 避开分红除权噪声，反映真实趋势 |
| 美股 | 现有 `close`（Yahoo 已 adjclose） | 已经是复权价 |
| A股股票 | 现有 `close` | 不在本期改动范围 |
| 港股基金 | 现有 `acc_nav` | 兜底，分红影响小 |

> 注：RSI 仍走累计净值不变，详见 brainstorm 讨论。两个指标口径不完全一致是已知 trade-off，换取实现风险最小化。

## 接口与数据流

### 新数据源

`http://fund.eastmoney.com/pingzhongdata/{fund_code}.js`
- 字段：`Data_netWorthTrend`，每个元素 `{x: 时间戳ms, y: 单位净值, equityReturn: 日收益率%, unitMoney: 分红说明}`
- 复权净值序列：`adj[i] = adj[i-1] * (1 + equityReturn[i]/100)`，初值 1.0

### 修改链路

```
data_fetcher.py
  └─ A股基金/cn_auto 路径：返回 DataFrame 多带一列 adj_nav
     └─ 与 sina 历史净值按日期对齐合并

technical_analysis.py
  └─ 新增 calc_sma60_distance(df, price_col_for_ma)
     └─ result['ma60'] = {'value': float|None, 'price': float, 'distance_pct': float|None}

inject_ta_summary.py
  └─ summary['ma60_distance'] = ta_data['ma60']['distance_pct']
  └─ summary['ma60_value']    = ta_data['ma60']['value']

index.html (renderCards.cardHtml)
  └─ sc-metrics 网格从 4 列改为 5 列
  └─ 新增 <div class="sc-m"><div class="v ${changeClass}">${ma60_distance}%</div><div class="l">vs MA60</div></div>
```

## 接口契约

### `data_fetcher.fetch_cn_fund(...)` 返回值变更

**旧**：`(df, 'acc_nav', fund_name)`，`df` 列：`date, unit_nav, acc_nav, nav_for_rsi, daily_change`

**新**：`(df, 'acc_nav', fund_name)`，`df` 多加一列 `adj_nav`
- 若 pingzhongdata 拉取失败：`adj_nav` 回退为 `acc_nav`（不阻塞主流程）

### `run_technical_analysis(df, price_col, data_type)` 新增输出

```python
result['ma60'] = {
    'price': 1.1524,         # 最新价（与 latest_price 一致）
    'value': 1.1842,         # SMA60 值（基于 adj_nav 或 close）
    'distance_pct': -2.69,   # (price/value - 1) * 100，保留 2 位
}
```

不足 60 个交易日时：`value=None, distance_pct=None`

## 错误处理

| 场景 | 行为 |
|---|---|
| pingzhongdata 网络失败 | adj_nav 回退用 acc_nav，正常返回 |
| pingzhongdata 解析失败 | 同上 |
| 数据不足 60 天 | `result['ma60']['value'] = None`，前端显示 `-` |
| 字段缺失（旧缓存基金） | 前端显示 `-`，不报错 |

## 测试 / 验证

1. **数值核对**：跑 `512890`，对比手算（最近 60 个 adj_nav 算术平均），偏离值与 brainstorm 时实测对齐（≈-2.69%）
2. **回退测试**：mock pingzhongdata 返回 500，确认 adj_nav 等于 acc_nav 且无异常
3. **不足 60 天**：跑一只数据少于 60 天的新基金（如有），确认前端显示 `-`
4. **面板视觉**：107 只全跑后打开 index.html，确认每张卡片都有 "vs MA60" 一格

## 实施步骤

1. data_fetcher.py：A股基金分支加 adj_nav 累乘
2. technical_analysis.py：加 ma60 计算
3. inject_ta_summary.py：注入 ma60_distance
4. index.html：sc-metrics 加第 5 格
5. 删除 result/*_full_ta.json 旧缓存
6. 重跑 batch_full_ta.py + inject_ta_summary.py 更新技术分析摘要和报告
7. 同步 data.js，打开面板验收

## 风险

- **风险点**：pingzhongdata 接口若失效，A股基金 ma60 数据全部回退累计净值口径，偏差 0.5-1%（可接受）
- **不可逆**：无。新增字段，老数据不会被破坏。回滚只需移除 5 处改动
