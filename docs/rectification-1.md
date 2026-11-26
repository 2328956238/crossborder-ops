# 第一轮整改报告：权限、审批与审计体系

> 结论：**P0/P1 阻断项已修复，可回归验证**。viewer 全部写接口 403；审批 API 真正可用（DRAFT→PENDING→审批→执行 落库）；
> 低风险写操作全部审计；Webhook 增加 HMAC 验签 + 时间戳 + 不自动建店。
> 原有 139 个测试全部通过，新增 16 个整改测试，**总计 155 passed**；Alembic 迁移在 SQLite 与 PostgreSQL 上 upgrade/downgrade/upgrade 均成功。
> 源仓库 `amazon-agent-hub` 未修改；未新增多账号/多站点/Listing/库存业务功能（按要求本轮不做）。

---

## 1. 修改/新增文件清单

### 新增

| 文件 | 作用 |
|---|---|
| `core/permissions.py` | `require_role()` 依赖 + `ensure_role()` 服务层校验；角色常量 |
| `core/policy.py` | 操作风险策略（action_type → 实体类型/风险等级/是否审批/允许字段） |
| `core/audit.py` | 审计写入（同事务/失败独立事务）、敏感信息脱敏、Decimal/日期序列化 |
| `models/audit.py` | `audit_log` 通用审计表 |
| `services/operation_submission.py` | 服务端读取 before 快照、创建 DRAFT、提交 PENDING、审批前目标复核 |
| `services/operation_execution.py` | 审批执行：DB 目标写回 + 审计；非 DB 目标明确标注 `execution_target=mock` |
| `services/webhooks_signing.py` | HMAC-SHA256 验签适配器（常量时间比较） |
| `schemas/operations.py` | 创建/提交审批的请求模型 |
| `tests/test_rectification.py` | 16 个整改测试 |
| `alembic/versions/6bfe62f2be21_audit_log_and_operation_reason.py` | 迁移 0006 |

### 修改

| 文件 | 变更 |
|---|---|
| `api/routers/operations.py` | 新增 `POST /operations`、`POST /{id}/submit`；全部端点角色依赖；审批/拒绝/执行审计 |
| `api/routers/products.py` | 创建 operator+ 审计；`PATCH` 改为**提交审批（202）**，不再直写 |
| `api/routers/inventory.py` | upsert/adjust 改 operator+，写前/写后审计 |
| `api/routers/advertising.py` | 账户/指标写 operator+，审计 |
| `api/routers/meta.py` | OAuth 授权/换 token 仅 admin；同步 operator+ 且审计（不记录 token 原文） |
| `api/routers/shops.py` | 创建店铺 admin 审计；读接口角色化 |
| `api/routers/ad_shield.py` | 风险处置 operator+ 审计；巡检 admin 审计 |
| `api/routers/webhooks.py` | 验签 + 时间戳 + 白名单 + 店铺必须已注册；移除自动建店；写入审计 |
| `services/approval.py` | 新增 `DRAFT`、`submit_operation`；`create_operation` 支持 status/reason/session（兼容旧调用） |
| `services/{catalog,inventory,advertising,shops}.py` | 写方法增加 `ctx` 参数 + `ensure_role` 内部校验（服务层不可绕过） |
| `services/meta_sync.py` | `sync_all` 增加 `ctx` + 角色校验 |
| `models/approval.py` | `operation.reason` 字段 |
| `core/errors.py` | `ApprovalError` 按错误码映射 HTTP 状态（403/404/422） |
| `main.py` | `X-Request-ID` 中间件（审计关联请求） |
| `tests/test_business_modules.py`、`tests/test_operations_api.py`、`tests/test_meta.py` | 按新规则调整调用（旧断言未删弱，仅改为走审批链/传 ctx） |

---

## 2. 新增数据库表和迁移说明

| 变更 | 说明 |
|---|---|
| `audit_log`（新表） | 通用审计日志；索引 `(shop_id, created_at)`、`(entity_type, entity_id)`、`operation_id`；`shop_id` 外键→`shops` CASCADE |
| `operation.reason`（新列） | 审批提交原因，nullable Text |
| 迁移 | `6bfe62f2be21_audit_log_and_operation_reason`：upgrade 建表+加列、downgrade 可回滚 |
| 历史数据 | 新列 nullable、新表无历史依赖，不影响已有数据；无需回填 |

验证结果（第 9 节）：SQLite 与 PostgreSQL 16 均 `upgrade head → downgrade base → upgrade head` 成功；PG 最终 **21 张表 / 23 个外键 / 62 个索引**。

---

## 3. 权限矩阵

角色：`viewer`（只读）、`operator`（业务写 + 提交审批）、`admin`（店铺/授权/高风险审批）。

| 接口 | viewer | operator | admin | 说明 |
|---|---|---|---|---|
| 所有 GET（products/orders/inventory/advertising/ad-shield/reports/meta 状态/shops/operations 列表） | ✅ | ✅ | ✅ | 读接口 |
| `POST /products`（创建） | ❌403 | ✅ | ✅ | 低风险，审计 |
| `PATCH /products/{sku}` | ❌403 | ✅202 | ✅202 | 中风险：返回 DRAFT 操作，不直写 |
| `PUT /inventory/{sku}`、`POST .../adjust` | ❌403 | ✅ | ✅ | 低风险，审计 |
| `POST /advertising/accounts`、`POST /advertising/insights` | ❌403 | ✅ | ✅ | 低风险，审计 |
| `POST /meta/sync` | ❌403 | ✅ | ✅ | 低风险，审计 |
| `POST /meta/oauth/authorize-url`、`/oauth/exchange` | ❌403 | ❌403 | ✅ | 授权管理仅 admin |
| `POST /shops` | ❌403 | ❌403 | ✅ | 店铺管理，审计 |
| `POST /operations`（提交审批） | ❌403 | ✅ | ✅ | 服务端读取 before 快照 |
| `POST /operations/{id}/submit` | ❌403 | ✅ | ✅ | DRAFT→PENDING |
| `POST /operations/{id}/approve` | ❌403 | 视风险（high→forbidden） | ✅ | 角色规则由 `ROLE_FOR_RISK` |
| `POST /operations/{id}/reject` / `execute` | ❌403 | ✅ | ✅ | 执行需已 APPROVED |
| `POST /ad-shield/risks/{id}/ack|resolve` | ❌403 | ✅ | ✅ | 审计 |
| `POST /ad-shield/patrol` | ❌403 | ❌403 | ✅ | 巡检 |
| `POST /webhook/amazon` | —（无 token） | — | — | HMAC 签名 + 白名单 + 已注册店铺，见第 6 节 |

服务层同样校验：`catalog.create_product/update_product`、`inventory.upsert/adjust`、`advertising.create_account/upsert_insight`、
`meta_sync.sync_all`、`shops.create_shop` 均要求 `ShopContext` 并在内部 `ensure_role`；直接 import Service 调用也无法绕过角色。
（`approval` 服务是审批状态机本身，其 approve 已有角色规则；execute 仅能从已审批状态执行，且路由层要求 operator+。）

---

## 4. 审批状态流转图

```
             POST /operations（服务端读 before 快照）
                          │
                          ▼
                       ┌──────┐   submit（operator+）
                       │DRAFT │──────────────▶ PENDING_APPROVAL
                       └──────┘                     │
                                     approve ──────┼──────▶ APPROVED ──execute──▶ EXECUTING
                                        │          │                                  │
                                        │          └──reject──▶ REJECTED              ├─▶ EXECUTED
                                        │                                             ├─▶ FAILED（规则/stale/异常）
                                        │                                             └─▶ UNKNOWN（超时/结果未知，不重试）
                                        └── role 不足 → forbidden（不流转，写审计）
```

并发与幂等：
- 状态流转用**条件 UPDATE**（`WHERE id=? AND status=?` + rowcount），10 并发 approve 只 1 个成功（测试覆盖）；
- `(shop_id, idempotency_key)` 唯一，重复提交返回同一操作；
- 审批前重新校验目标对象存在且属于本店；执行前重读当前快照，数据已变 → `stale` → FAILED；
- 重复执行返回 `skipped`；失败/未知写入 `error_code` 与审计。

风险规则（`core/policy.py`，独立配置）：
- low：`product.create`、`inventory.upsert/adjust`、`advertising.*`、`meta.sync`、`ad_shield.*` → operator 直接执行（审计）；
- medium：`product.update_listing`、`pricing.update_price` → 必须审批，operator/admin 可批；
- high：客户端可**升高**（不能降低服务端风险），仅 admin 可批。

---

## 5. 审计日志结构

`audit_log`：

| 字段 | 说明 |
|---|---|
| `id` | 自增主键 |
| `shop_id` | 店铺（FK→shops，CASCADE） |
| `actor_id` / `actor_role` | 操作者与角色（来自认证上下文，客户端不可伪造） |
| `action` | 业务动作，如 `product.create`、`inventory.adjust`、`operation.approve`、`meta.sync`、`webhook.amazon` |
| `entity_type` / `entity_id` | 业务对象 |
| `before_data` / `after_data` | 修改前后**实际数据**（JSON；Decimal/日期转字符串） |
| `request_id` | 请求 ID（`X-Request-ID` 或服务端生成） |
| `operation_id` | 关联审批操作（可空） |
| `result` / `failure_reason` | `ok` / `failed` + 失败原因 |
| `created_at` | 时间戳 |

规则：
1. 成功路径与业务变更**同一事务**提交；审计写入失败会使请求失败，不会"业务成功但无审计"；
2. 失败路径用独立事务记录（不被业务回滚带走），审计失败只记日志、不掩盖原始异常；
3. 敏感键（`token/access_token/refresh_token/secret/password/authorization/cookie/api_key`）统一写 `"***"`，疑似长 token 字符串也掩码；测试断言原文不落库；
4. 保留既有 `operation_audit`（每次审批流转），并与 `audit_log.operation_id` 衔接；
5. 无任何 API 可修改/删除审计记录（viewer/operator/admin 均无写审计接口）。

---

## 6. Webhook 安全实现

- 签名：`HMAC-SHA256(secret, f"{timestamp}.{raw_body}")`，头 `X-Timestamp` + `X-Signature: sha256=<hex>`；
- 常量时间比较 `hmac.compare_digest`；
- 时间戳偏差超过 `WEBHOOK_MAX_SKEW_SECONDS`（默认 300s）→ 401（防重放）；
- 店铺白名单 `WEBHOOK_ALLOWED_SHOPS`；**店铺必须已注册，否则 404，绝不自动创建**；
- 事件幂等：`platform_event` 唯一键 + `ON CONFLICT DO NOTHING`，重复/重放返回 `duplicate` 且不重复处理订单；
- `WEBHOOK_SECRET` 未配置：dev 记录警告后放行（仅本地）；生产必须配置（缺失 → 500，签名错误 → 401）；
- 不同平台签名算法通过独立 `services/webhooks_signing.py` 适配，不假设统一算法；
- 密钥/签名不写日志，也不进入审计 after 数据。

---

## 7. 新增测试数量

- 新增 `tests/test_rectification.py`：**16 个**
- 其中：权限 5（viewer 全写 403、viewer 只读、operator 低风险、operator 高风险审批 forbidden、服务层 403）
  审批 6（创建/提交/审批/执行落库、幂等+跨店、stale、并发审批、目标不存在 404、重复审批/执行）
  审计 3（写操作审计、operation_id 关联、脱敏+失败审计）
  Webhook 4（有效签名、错签名/过期、未知店铺不建店、重放去重）
- 合计：**155 个测试**

## 8. 完整 pytest 结果

```
$ .venv/Scripts/python.exe -m pytest -q
155 passed in 13.6s
```

（原有 139 个测试全部保留并通过；其中 `test_business_modules` 的商品 PATCH 用例按新规则改为"审批链"，`test_operations_api` 改为走新审批 API —— 属于预期行为变更，未删除断言。）

## 9. Alembic upgrade/downgrade 验证

| 环境 | 结果 |
|---|---|
| SQLite（临时库） | `upgrade head` → `downgrade base` → `upgrade head` 全部成功 |
| PostgreSQL 16（pgserver 实例） | 同上全部 rc=0；最终 21 张表 / 23 外键 / 62 索引；`audit_log` 14 列齐全；`operation.reason` 存在 |

## 10. 尚未解决的问题（本轮范围外，如实说明）

1. **多 Amazon 账号/多站点/SP-API 接入**仍未实现（上一轮审查 P0，属后续轮次）。
2. **Listing 批量/预览/任务拆分/失败重试、FBA/FBM 库存流水、订单履约状态机**仍未实现（后续轮次）。
3. 非 DB 目标（例如本地 synthetic 商品）审批执行会走 Mock 适配器，响应明确标注 `execution_target=mock`；**不会描述为真实平台操作**。
4. 审计目前只有写入能力，没有查询 API/看板（可按需加 `GET /audit`，本轮未做）。
5. 任务级隔离（batch/task 实体）未引入；跨店隔离目前是"店铺 + Operation"粒度。
6. Webhook 只有 Amazon 平台适配器；其他平台需各自实现签名适配。
7. 真实 Meta/Amazon 未联调，Docker Compose 仍未在本机实测。
