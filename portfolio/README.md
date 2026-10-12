# portfolio/ — 本人基金持仓持久化目录

用途：记录本人基金持仓，作为 rsi-analysis 抄底/再平衡的参考基准。与 `../result/`(RSI 技术分析输出)解耦。

## 文件结构
```
portfolio/
├── holdings.json              # 当前持仓(源数据)。更新时直接覆盖 latest + total/allocation
├── README.md                  # 本说明
└── snapshots/
    └── portfolio_YYYY-MM-DD.md   # 每次更新的日级快照 + 当时结构分析
```

## 更新流程（下次给新持仓时）
1. 我会新建 `snapshots/portfolio_<新日期>.md` 存档旧状态+新分析。
2. 同步把 `holdings.json` 的 `updated_at` / `total` / `total_profit` / `allocation` / `latest` 覆盖为最新。
3. 如需对比，可新旧两份 snapshot diff 算出"调了什么、调了多少"。

## 字段约定（holdings.json）
- `amount`：持有金额(元)，通常为当前市值
- `weight_pct`：占总市值百分比
- `profit`：累计浮盈(元)，可正可负
- 区间收益率 = profit / (amount − profit)，在分析快照里现算

## 与 RSI 分析的衔接
- 单只标的抄底/超买判断仍走 `../main.py` / `../batch_*.sh`，输出落 `../result/`。
- 后续如需批量按持仓跑 RSI，建议补一份 `holdings_codes.json`(产品名 → 基金代码/指数代码)。