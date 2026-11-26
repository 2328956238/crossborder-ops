# 阶段 2 报告：业务模块 + PostgreSQL 迁移（索引/外键/唯一约束）

> 阶段结论：**验收通过**。7 个业务模块按 api→schemas→services→repositories→models 落地；
> 真实 PostgreSQL 16 上 `upgrade head → downgrade base → upgrade head` 全部成功；
> 111 个测试全绿（阶段 1 的 100 个 + 阶段 2 新增 11 个）。

## 1. 数据模型（17 张表）

| 模块 | 表 | 关键约束 |
|---|---|---|
| shops | `shops` | PK id |
| products | `products` | UQ(shop_id, sku)、IDX(shop_id, status)、IDX(shop_id, asin)、FK→shops CASCADE |
| orders | `orders`（扩展） | UQ(shop_id, order_id)、IDX(shop_id, status)、FK→shops；新增 total_amount/currency/channel/created_at |
| inventory | `inventory`（扩展） | UQ(shop_id, sku)、IDX(shop_id, sku)、FK→shops；新增 warehouse/on_hand/reserved/inbound/safety_stock/lead_time_days/updated_at |
| advertising | `ad_accounts`、`ad_campaigns`、`ad_sets`、`ads`、`ad_insights` | 账户 UQ(shop, platform, external_id)；Campaign UQ(account, external_id)；AdSet UQ(campaign, external_id)；Ad UQ(adset, external_id)；Insight UQ(shop, level, entity, date) + IDX(shop, date)；全部 FK（CASCADE） |
| ad_shield | `ad_reviews`、`risk_events`、`alerts` | 审核 UQ(shop, ad, fetched_at)；风险 UQ(shop, rule, entity_type, entity_id, window_key)（天然抑制重复告警）；告警 UQ(dedupe_key)；全部 FK |
| 基础设施 | `platform_event`、`sync_cursor`、`ad_report`、`operation`、`operation_audit` | 已有约束 + 本轮补 FK→shops / operation |

迁移：`0002_business_modules`（新增 9 张表 + 扩展 2 张表 + 补 8 个外键与索引），
对已有阶段 1 数据的库也能升级（新增 NOT NULL 列带 server_default，已用 legacy 行测试覆盖）。

## 2. 模块分层

| 模块 | schemas | repository | service | router |
|---|---|---|---|---|
| shops | `schemas/business.py::ShopCreate/Out` | `repositories/business.py` | `services/shops.py` | `/api/v1/shops` |
| products | `ProductCreate/Update/Out` | 同上 | `services/catalog.py` | `/api/v1/products` |
| orders | `OrderOut/OrderStats` | 同上 | `services/orders.py` | `/api/v1/orders` |
| inventory | `InventoryUpsert/Adjust/Out` | 同上 | `services/inventory.py` | `/api/v1/inventory` |
| advertising | `AccountCreate/InsightUpsert/AdMetrics` | `repositories/ads.py` | `services/advertising.py` | `/api/v1/advertising` |
| ad_shield | `RuleHit/RiskEventOut` | 同上 | `services/ad_shield.py` + `ad_shield_rules.py` | `/api/v1/ad-shield` |
| reports | `ReportRange` | 复用上面两个 repo | `services/reports.py` | `/api/v1/reports` |

## 3. 关键业务规则

- **租户隔离**：所有仓储函数签名第一个业务参数就是 `shop_id`；API 从认证上下文注入；
  跨店铺查询/读取返回 403 或 404（已用测试覆盖）。
- **金额精度**：DB 用 `Numeric(18,4)`，API 统一输出 4 位小数字符串（`core/serialization.money`）。
- **库存口径**：可售 = `on_hand − reserved`；`inbound` 在途不计可售；调整后不允许负数、`reserved > on_hand` → 422。
- **广告指标**：CTR/CPC/CPM/CPA/ROAS/ACOS 由 `domain/advertising.py` 纯函数计算；分母为 0 返回 `null` 而不是 0。
- **广告盾规则（独立模块，不依赖路由）**：
  - `R001_SPEND_DROP`：花费低于 7 日均值 30% → **warn**，detail 明确"不等于封号，需核查"；
  - `R401/R403/R429/R5XX`：**分别映射**，401/403 为 critical 但语义不同（token vs 权限）；
  - `R002_CTR_DROP`、`R003_CPA_SPIKE`：warn；
  - `R004_REVIEW_REJECTED`：拿不到原因时 `manual_required=True`；
  - 风险事件 `(shop, rule, entity, window)` 唯一 → 重复检测自动抑制，告警 `dedupe_key` 唯一。
- **广告盾状态流转**：`open → acknowledged → resolved`，非法流转 422。

## 4. 测试结果

```
pytest -q  →  111 passed（8.9s）
```

新增覆盖（`tests/test_business_modules.py`，11 例）：
商品 CRUD/重复 409/跨店 404/负价 422；订单列表统计与隔离；库存 upsert/adjust/低库存/非法调整 422；
广告账户 + Insights 幂等 + 指标（ROAS/ACOS）；规则单测（花费下降只 warn、4 类 API 错误不混淆、审核无原因需人工）；
风险落库去重 + 告警；状态流转与非法流转；报表日期区间/多店铺 admin 权限。
迁移：`tests/test_migrations.py` 增加"已有数据升级"用例。

**真实 PostgreSQL 验证**：`upgrade head → downgrade base → upgrade head` 均 rc=0，18 张表 / 21 个外键 / 51 个索引。

## 5. 未完成 / 后续阶段

1. **阶段 3**：`integrations/meta` 仍只有包声明；广告域目前用本地 API 写入 Insights，未接 Meta。
2. **阶段 4**：广告盾只有规则 + 落库 + 状态流转；定时巡检（APScheduler job）、通知渠道、审核状态采集未接。
3. **阶段 5**：报表只有销售额/广告指标/库存预警/多店铺基础汇总；商品销售排行、订单明细、ACOS 归因口径待补。
4. 旧只读接口 `/api/v1/amazon/*` 仍走 synthetic 适配器（与新的 PG 业务 API 并存，阶段 5 后收口）。
5. webhook 仍未做 HMAC 验签（只有店铺白名单）；`orders.last_update_time` 仍为字符串时间。
6. Docker Compose 本机无 Docker，未实测。
7. GitHub 目标仓库不存在，尚未 push。
