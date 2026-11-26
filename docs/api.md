# API 文档（crossborder-ops）

- Base URL：`http://127.0.0.1:8000`
- 认证：`Authorization: Bearer <token>`（token → `{shop_id, actor, role}` 由服务端映射）
- **shop_id 只能来自认证上下文**，请求体/路径中的店铺必须与 token 一致，否则 403
- 统一响应：成功 `{"ok": true, "data": ...}`；失败 `{"ok": false, "error": {"code", "message"}}`
- 金额一律返回 4 位小数字符串（如 `"12.5000"`）；比例指标为小数（`0.25` 表示 25%）
- 分页参数：`limit`（默认 50，上限 200）、`offset`（部分接口）

## 1. 健康与指标

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 存活探针：`{ok, version, env}` |
| GET | `/readyz` | 就绪探针：数据库连通性 |
| GET | `/metrics` | Prometheus 指标（含请求数/耗时/Meta 调用） |

## 2. 平台 webhook

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/webhook/amazon` | 平台事件；按 `(shop_id,event_id)` 去重；`ORDER_CHANGE` 防乱序 upsert |

请求体：`{shop_id, event_id, type, event_time, order_id?, status?}`（多余字段 422）。
生产环境必须配置 `WEBHOOK_ALLOWED_SHOPS`；店铺白名单外的 `shop_id` 返回 403。

```bash
curl -X POST http://127.0.0.1:8000/webhook/amazon -H 'Content-Type: application/json' \
  -d '{"shop_id":"S1","event_id":"e1","type":"ORDER_CHANGE",
       "event_time":"2026-03-01T00:00:00+00:00","order_id":"O1","status":"SHIPPED"}'
```

## 3. 审批（Operation）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/operations?status=&limit=` | 列表（shop 隔离） |
| GET | `/api/v1/operations/{id}` | 详情 + 审计轨迹 |
| POST | `/api/v1/operations/{id}/approve` | 审批（风险等级 → 角色：high 仅 admin） |
| POST | `/api/v1/operations/{id}/reject` | 拒绝 |
| POST | `/api/v1/operations/{id}/execute` | 执行（执行前重核旧值；UNKNOWN 不重试） |

## 4. 店铺 / 商品 / 订单 / 库存

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/shops` | 仅返回当前 token 的店铺 |
| GET | `/api/v1/shops/{shop_id}` | 店铺详情（跨店 403） |
| POST | `/api/v1/shops` | 创建店铺（admin） |
| GET/POST | `/api/v1/products` | 商品列表（`status/limit/offset`）/ 创建 |
| GET/PATCH | `/api/v1/products/{sku}` | 详情 / 更新（title、status、price） |
| GET | `/api/v1/orders` | 订单列表（`status/limit/offset`） |
| GET | `/api/v1/orders/stats?days=` | 最近 N 天订单量/金额/状态分布 |
| GET | `/api/v1/orders/{order_id}` | 订单详情 |
| GET | `/api/v1/inventory` | 库存列表（`low_only`） |
| GET | `/api/v1/inventory/low-stock` | 低库存（可售 = on_hand − reserved） |
| PUT | `/api/v1/inventory/{sku}` | 覆盖式 upsert |
| POST | `/api/v1/inventory/{sku}/adjust` | 增量调整（负数非法，reserved>on_hand 422） |

## 5. 广告（Meta 域）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/advertising/accounts` | 广告账户列表 |
| POST | `/api/v1/advertising/accounts` | 新增账户（本地登记） |
| GET | `/api/v1/advertising/campaigns` / `adsets` / `ads` | 结构列表 |
| POST | `/api/v1/advertising/insights` | 分日指标幂等写入（`shop,level,entity,date` 唯一） |
| GET | `/api/v1/advertising/metrics?date_from=&date_to=` | 汇总指标（CTR/CPC/CPM/CPA/ROAS/ACOS） |

## 6. 广告盾

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/ad-shield/risks?status=` | 风险事件列表 |
| GET | `/api/v1/ad-shield/risks/{id}` | 详情 |
| POST | `/api/v1/ad-shield/risks/{id}/ack` | 确认（open → acknowledged） |
| POST | `/api/v1/ad-shield/risks/{id}/resolve` | 解决（→ resolved；已解决再操作 422） |
| GET | `/api/v1/ad-shield/alerts` | 告警记录 |
| GET | `/api/v1/ad-shield/reviews` | 广告审核状态快照（含 `manual_required`） |
| POST | `/api/v1/ad-shield/patrol` | 手动巡检（admin；Mock 模式返回 `source=mock`） |

## 7. 报表

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/reports/sales?date_from=&date_to=` | 销售额/订单量/客单价 |
| GET | `/api/v1/reports/ads?date_from=&date_to=` | 广告汇总（spend/CTR/CPC/CPM/CPA/ROAS/ACOS） |
| GET | `/api/v1/reports/ads/trend?date_from=&date_to=` | 按天消耗趋势 + 逐日 ACOS |
| GET | `/api/v1/reports/top-products?date_from=&date_to=&limit=` | 商品销售排行（销量/营收） |
| GET | `/api/v1/reports/inventory-warnings` | 库存预警 |
| GET | `/api/v1/reports/overview?date_from=&date_to=&shops=` | 多店铺汇总（`shops` 仅 admin） |

所有报表均要求日期区间，并按认证上下文的 shop 隔离。

## 8. Meta 集成

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/meta/status` | 当前模式（mock/meta）、App 配置状态 |
| POST | `/api/v1/meta/oauth/authorize-url` | 生成授权链接 `{state}` |
| POST | `/api/v1/meta/oauth/exchange` | code 换 token 并加密落库 `{code}` |
| GET | `/api/v1/meta/accounts` | 拉取账户（Mock 模式带 `source=mock`） |
| POST | `/api/v1/meta/sync` | 同步账户/结构/Insights `{since, until}`，返回各实体写入数 |

## 9. 错误码

| HTTP | code | 场景 |
|---|---|---|
| 400 | `bad_token_config` / 各类业务错误 | 配置或请求错误 |
| 401 | `unauthorized` | 缺少/无效 token |
| 403 | `forbidden_shop` / `forbidden` / `shop_not_allowed` | 跨店、角色不足、webhook 白名单 |
| 404 | `not_found` | 资源不存在 |
| 409 | `conflict` | 重复创建（如商品 SKU 已存在） |
| 422 | `validation_error` / `invalid_arg` | 参数非法、非法状态流转 |
| 503 | `data_unavailable` | 本地数据源不可用 |

## 10. 已废弃

`GET /api/v1/amazon/*`（products/orders/inventory/advertising/summary/pricing）为旧 synthetic 只读接口，
保留用于演示；正式数据请使用 `/api/v1/{products,orders,inventory,advertising,reports}`。
