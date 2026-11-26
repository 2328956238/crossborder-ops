# 系统架构（阶段 1）

## 1. 分层

```
HTTP 请求
   │
api/            路由 + 依赖（认证、会话、适配器）       ← 只做参数校验与错误映射
   │
schemas/        Pydantic v2 请求/响应模型
   │
services/       业务编排（审批状态机、事件同步、补拉、执行器注册表）
   │
repositories/   数据库访问（SQL 只出现在这里）
   │
models/         SQLAlchemy 2.0 声明式模型
```

横切：
- `core/`：错误类型、认证与租户上下文、Redis 令牌桶；
- `domain/`：纯业务规则（定价、库存、Listing 校验、广告指标），零 I/O、可单测；
- `integrations/`：外部平台。`local/` 是 synthetic 合成数据适配器；`meta/` 在阶段 3 落地；
- `workers/`：APScheduler 定时任务（阶段 3/4 注册具体任务）。

**依赖方向是单向的**：api → services → repositories → models；
`integrations` 被 services 调用，但不得反向依赖 services/api。

## 2. 应用生命周期

`create_app()` 工厂在 `main.py`：

1. 读 `Settings`（pydantic-settings，全部来自环境变量/.env）；
2. `AUTO_CREATE_TABLES=true` 时用 metadata 建表（**仅 dev/test**；生产走 alembic）；
3. 初始化 synthetic 数据适配器，失败只降级只读接口（503），不影响 webhook/审批；
4. 启动 APScheduler（`SCHEDULER_ENABLED=false` 时跳过）；
5. 关闭时释放调度器与数据库引擎。

## 3. 租户隔离（shop_id）

1. **唯一来源**：token → `{shop_id, actor, role}` 映射（`core/security.py`）；
2. 客户端请求体不接受 shop_id：`schemas` 里禁止该字段，webhook 例外（平台推送，走店铺白名单）；
3. Repository 层所有查询签名里带 `shop_id`，service 不得跨店读取；
4. 审批详情/执行在 `_load` 里二次校验归属，跨店返回 `403 forbidden_shop`；
5. 生产环境未配置 `API_TOKENS` 时 fail-closed，且拒绝内置 dev token。

## 4. 审批状态机（独立业务能力）

```
PENDING_APPROVAL ──approve──▶ APPROVED ──execute──▶ EXECUTING ──▶ EXECUTED
        │                                              │
        └──reject──▶ REJECTED                          ├──▶ FAILED（规则/stale/执行失败）
                                                       └──▶ UNKNOWN（超时/网络中断，不重试不回滚）
```

关键设计：
- **并发安全**：状态流转用条件 UPDATE（`WHERE id AND status=:from` + `rowcount==1`），20 并发只 1 个赢家；
- **幂等**：`(shop_id, idempotency_key)` 唯一约束，重复创建返回已有操作；
- **执行前重核**：`executor.read_current` + `validate` 对比 `before_snapshot`，被他人改过 → `stale` 失败；
- **结果未知语义**：超时/网络异常 → `UNKNOWN` 终态，不自动重试、不回滚，交给人工核对；
- **审计**：每次流转写 `operation_audit`（create/approve/reject/execute_start/execute_done/execute_unknown）。

执行器注册表 `services/executors.py`：只有登记过的 `action_type` 才能执行（`product.update_listing`、
`pricing.update_price`），且当前只作用于 mock/local 适配器，**不触达真实平台**。

## 5. 事件同步

`POST /webhook/amazon`：
1. Pydantic 校验字段；生产环境校验店铺白名单；
2. `INSERT ... ON CONFLICT (shop_id,event_id) DO NOTHING`：同一事件只入库一次（去重）；
3. `ORDER_CHANGE` 走 `UPSERT_ORDER`：只有 `last_update_time` 更晚才覆盖（防乱序）；
4. 去重与 upsert 在同一事务内完成。

补拉（`services/backfill.py`）：水位线 `sync_cursor` 只在本批全部写入成功后、同一事务推进，
并回退 5 分钟重叠窗口防边界漏单。

## 6. 可观测性

- `/healthz`：进程存活；`/readyz`：数据库连通性；`/metrics`：Prometheus 指标；
- 中间件记录请求数/耗时（method/path/status 维度）；
- 业务计数器（如 `crossborder_sync_events_total`）按阶段扩展。

## 7. 数据库

- 生产 PostgreSQL 16（asyncpg）；测试 SQLite（aiosqlite，NullPool + WAL）；
- 迁移：`alembic upgrade head` 从空库建全部表，含索引与唯一约束；
- 表：`shops`、`platform_event`、`orders`、`order_items`、`sync_cursor`、`inventory`、`products`、`ad_report`、`ad_accounts/campaigns/sets/ads/insights`、`ad_reviews`、`risk_events`、`alerts`、`shop_credentials`、`operation`、`operation_audit`。

## 8. 阶段 1 的已知边界（阶段 2+ 处理）

1. 只读数据接口仍走 `integrations/local`（synthetic），阶段 2 换成 PG 仓储 + Pydantic 响应模型；
2. `orders.last_update_time`、`sync_cursor.value` 仍是 ISO 字符串（阶段 2 迁移为 `timestamptz`）；
3. `inventory` 只有 `quantity`，阶段 2 扩展 on_hand/reserved/inbound/warehouse/lead_time；
4. 无数据库级外键到 `shops`（阶段 2 补 FK 与迁移）；
5. webhook 验签（HMAC）未实现，阶段 2 补；
6. Mock 状数据写覆盖层仍在进程内存（阶段 2 落库）。
