# 指标口径定义(earnings-analysis 参考)

## 期间基准 basis

- cumulative:年初至报告期末的累计数(如 2026H1 = 2026-01-01 至 2026-06-30)
- single_quarter:单季数(如 2026Q2 = 2026-04-01 至 2026-06-30)
- 两种 basis 不可直接比较;单季累计相加得到累计数属于派生计算,
  需在 assumptions 中注明。

## 报表口径 scope

- 合并报表:含子公司;母公司报表:仅母公司。两者不可比、不可相加。

## 修订版本

- 同一报告期存在多版本(revision_id v1/v2...)时,工具已按任务截止时间
  返回当时可获得的最新修订;引用时使用返回的 observation_id,
  并检查 note 中的修订说明。

## 金额与币种

- value 为 Decimal 字符串,unit 元/美元,currency CNY/USD;
  币种不同的观测不可直接比较(growth 会返回 INCOMPARABLE_INPUTS)。
