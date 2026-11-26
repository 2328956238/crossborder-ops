# 阶段 5 报告：经营报表 + 交付收尾

> 阶段结论：**验收通过**。报表补全商品排行/广告趋势/多店铺汇总，全部支持日期区间与 shop 隔离；
> 交付文档补齐（API 文档、测试报告、五阶段报告）；139 个测试全绿；5 个迁移在真实 PostgreSQL 上验证通过。

## 1. 本阶段改动

| 文件 | 说明 |
|---|---|
| `models/order_items.py`（新） | 订单明细表（shop/order/sku/quantity/unit_amount），排行榜数据来源 |
| `alembic/versions/*_order_items_for_product_ranking.py`（新） | 迁移 0005 |
| `repositories/business.py`（扩展） | `add_order_item`、`top_products` 聚合（join orders 过滤日期） |
| `services/reports.py`（扩展） | `top_products`、`ad_trend`（逐日消耗与 ACOS） |
| `api/routers/reports.py`（扩展） | `GET /top-products`、`GET /ads/trend` |
| `tests/test_reports_phase5.py`（新） | 4 个用例（排行/隔离/日期区间/趋势/汇总字段） |
| `docs/api.md`（新） | **API 文档**（交付物） |
| `docs/test-report.md`（新） | **测试报告**（交付物） |
| `docs/phase5-report.md`（新） | 本报告 |

## 2. 报表清单与口径

| 报表 | 接口 | 口径 |
|---|---|---|
| 销售额 / 订单量 / 客单价 | `GET /reports/sales` | 订单 `created_at` 落在区间内，金额 `Numeric(18,4)` |
| 商品销售排行 | `GET /reports/top-products` | `order_items` join `orders`，按营收降序，支持 limit |
| 库存预警 | `GET /reports/inventory-warnings` | 可售 = `on_hand − reserved`；低于 `safety_stock` 计缺口 |
| 广告汇总指标 | `GET /reports/ads` | CTR=clicks/impressions，CPC=spend/clicks，CPM=spend/impressions×1000，CPA=spend/conversions，ROAS=revenue/spend，ACOS=spend/revenue（分母为 0 返回 null） |
| 广告消耗趋势 | `GET /reports/ads/trend` | 按天汇总 spend/revenue/clicks/impressions + 逐日 ACOS |
| 多店铺经营汇总 | `GET /reports/overview` | 每店 orders/revenue/ad_spend/roas/acos；`shops` 参数仅 admin |

全部接口强制 `date_from/date_to`，并按认证 token 的 `shop_id` 过滤。

## 3. 最终交付物对照

| 交付要求 | 位置 | 状态 |
|---|---|---|
| 1. 完整可运行项目代码 | `crossborder_ops/`（84 文件 / 5781 行） | ✅ |
| 2. PostgreSQL 数据库迁移 | `alembic/`（5 个版本） | ✅ 真实 PG 验证 |
| 3. Docker Compose | `docker-compose.yml` + `Dockerfile` | ✅（本机无 Docker，未端到端启动） |
| 4. `.env.example` | 根目录（23 个键，全部映射 Settings） | ✅ |
| 5. API 文档 | `docs/api.md` | ✅ |
| 6. 测试报告 | `docs/test-report.md`（139 passed） | ✅ |
| 7. 系统架构文档 | `docs/architecture.md` | ✅ |
| 8. Meta API 对接说明 | `docs/meta-integration.md` | ✅ |
| 9. 广告盾风险规则说明 | `docs/ad-shield-rules.md` | ✅ |
| 10. README | `README.md` | ✅ |

## 4. 原始 10 条强制约束最终核对

| # | 约束 | 结果 |
|---|---|---|
| 1 | 禁止修改源仓库 | ✅ 源仓库只读（本地已有改动均为任务前遗留） |
| 2 | 修改只在 crossborder-ops | ✅ |
| 3 | 先检查依赖再迁移 | ✅ 盘点报告（Agent 专属 2214 行/28%） |
| 4 | 不得简单删目录清理 | ✅ 每项删除都列出能力去向 |
| 5 | 不得伪造真实 API 接入 | ✅ 无真实调用；Mock 显式标记 |
| 6 | 合成数据标 synthetic | ✅ `source: synthetic` / `source: mock` |
| 7 | 店铺数据查询必须验证 shop_id | ✅ 仓储签名 + API 上下文 + 跨店 403/404 |
| 8 | Meta Token 安全存储、不明文日志 | ✅ Fernet 加密落库 + 日志脱敏（有测试） |
| 9 | 迁移支持空库初始化 | ✅ SQLite + PostgreSQL 双验证（upgrade/downgrade/upgrade） |
| 10 | 不得只生成 README | ✅ 5781 行业务代码 + 139 测试 |

## 5. 测试结果

```
pytest -q  →  139 passed（8.9s）
```

真实 PostgreSQL 16（5 个迁移）：
`upgrade head → downgrade base → upgrade head` 全部 rc=0；**20 张表 / 22 个外键 / 58 个索引**。

## 6. 未完成（如实说明）

1. 真实 Meta App/API 未联调（无凭证，全部走 Mock）；
2. Docker Compose 未在本机实测（无 Docker 环境）；
3. 目标 GitHub 仓库（crossborder-ops）不存在，代码尚未 push；
4. 商品销售排行依赖 `order_items` 数据源，当前没有从平台订单同步明细的适配器（阶段 3 只同步了广告域）；
5. 历史补检/通知渠道扩展（企微/钉钉/邮件）未做。
