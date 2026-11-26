# 阶段 1 报告：复制清理 + 分层骨架 + PostgreSQL + Alembic

> 目标仓库：`crossborder-ops`（本地 git 仓库，origin 指向 github.com/2328956238/crossborder-ops）
> 源仓库 `amazon-agent-hub`：**未做任何修改**（只在本地复制一份到目标仓库）。
> 阶段结论：**验收通过**，100 个测试全绿，空库可迁移，Agent/LLM/LangGraph 代码已清除。

## 1. 交付清单

### 新增（核心）

| 文件 | 说明 |
|---|---|
| `crossborder_ops/config.py` | pydantic-settings 配置（PG/Redis/认证/Meta/webhook/调度/指标） |
| `crossborder_ops/db.py` | async engine / sessionmaker / `get_session`；SQLite 测试用 NullPool+WAL |
| `crossborder_ops/main.py` | `create_app()` 工厂、lifespan、统一错误封装 |
| `crossborder_ops/metrics.py` | Prometheus 中间件 + `/metrics` |
| `crossborder_ops/core/errors.py` | 统一错误类型（AppError 家族） |
| `crossborder_ops/core/security.py` | token → ShopContext，生产 fail-closed |
| `crossborder_ops/core/rate_limiter.py` | Redis Lua 令牌桶（从旧 sync/limiter 迁移） |
| `crossborder_ops/models/{base,shop,sync,business,approval}.py` | 8 张保留表；删除 4 张 Agent 专属表 |
| `crossborder_ops/repositories/approval.py` | 条件 UPDATE 抢锁 / 幂等查询 / 审计查询 |
| `crossborder_ops/services/approval.py` | 审批状态机（独立业务能力，零 Agent 依赖） |
| `crossborder_ops/services/executors.py` | Action Registry（Listing / 价格执行器） |
| `crossborder_ops/services/events.py` | 事件去重 + 订单防乱序 upsert |
| `crossborder_ops/services/backfill.py` | 水位线增量补拉 |
| `crossborder_ops/api/deps.py` | 认证/会话/适配器依赖 |
| `crossborder_ops/api/routers/{health,webhooks,operations,amazon}.py` | 4 组路由 |
| `crossborder_ops/workers/scheduler.py` | APScheduler 骨架（阶段 3/4 注册任务） |
| `crossborder_ops/integrations/local/` | 本地 synthetic 数据适配器（从旧 adapters 迁移） |
| `crossborder_ops/integrations/http_client.py` | 带限流/429/退避的 HTTP 客户端（阶段 3 复用） |
| `crossborder_ops/domain/*` | 定价/库存/Listing/广告指标纯规则（原样迁移） |
| `alembic/env.py` + `alembic/script.py.mako` + `alembic/versions/*_initial_schema.py` | 空库可 initial |
| `tests/conftest.py` + 9 个测试文件 | 100 个用例 |
| `Dockerfile` / `docker-compose.yml` / `.env.example` / `.gitignore` / `README.md` / `docs/architecture.md` | 交付物 |

### 删除（旧仓库内容，非"简单删除目录"——能力已在前一列替换）

| 删除项 | 原因 | 能力去向 |
|---|---|---|
| `hub/agent/`（6 文件 449 行） | Agent/LLM/Prompt | 不需要；审批能力迁到 `services/approval.py` |
| `hub/orchestration/`（10 文件 1426 行） | LangGraph 编排/checkpoint | 删除；审批恢复改为显式 REST 调用 |
| `hub/api/agent.py`（339 行） | Agent API（chat/runs/capabilities） | 删除；认证抽到 `core/security.py` |
| `hub/operations/`（3 文件） | 与 Agent 相邻但可独立 | 拆成 `services/approval.py` + `repositories/approval.py` + `services/executors.py` |
| `hub/adapters/local_ads.py`、`mock_spapi.py` | 反向依赖 `agent/` / `sync/` | 删除；阶段 3 用 Meta Mock 替代 |
| `hub/sync/*`（5 文件） | 基础设施 | 拆分迁到 `services/events.py`、`services/backfill.py`、`core/rate_limiter.py`、`integrations/http_client.py` |
| `hub/models.py` 中 `diagnosis_run`/`tool_call_log`/`suggestion`/`approval_log` | Agent 专属表 | 删除；审批统一走 `operation`/`operation_audit` |
| `mock_amazon/`、`tools/demo_ops.py`、`hub.db`、`hub_checkpoints.sqlite`、`demo_phase2.*` | 旧演示/残留物 | 删除；阶段 3 新建 Meta Mock |

### 保留并迁移

- FastAPI 入口、DB 基础设施、认证与店铺隔离、Redis 限流、事件去重、同步水位线、
  可复用适配器逻辑、`domain/` 纯规则、测试基础设施（conftest 改造为 SQLite 临时库）。

## 2. 关键改造点

1. **配置统一**：`os.getenv` 散落 → pydantic-settings 单一来源；`API_TOKENS` 不再二次读取。
2. **认证解耦**：从 `api/agent.py` 抽出 `core/security.py`，三个路由文件统一依赖 `api/deps.py`。
3. **仓储层**：审批的 SQL 全部收进 `repositories/approval.py`，service 不碰 ORM/SQL。
4. **错误语义**：`AppError` 家族 + API 层统一映射（404/403/422/409/503），保留 `{ok,error{code,message}}` 响应格式。
5. **迁移补全**：旧仓库只有 2 张表有迁移；现在 8 张保留表全部由 `0001_initial_schema` 覆盖（含索引/唯一约束），空库 `upgrade head` 可初始化、`downgrade base` 可回退。
6. **测试可移植**：测试默认 SQLite（不需要 PG/Redis/真实凭证），CI 可切 PostgreSQL。

## 3. 测试结果

```
pytest -q
100 passed, 0 failed  (~7s)
```

覆盖：
- 领域规则（`test_domain.py` / `test_domain_advertising.py`，42 用例，原样迁移）
- 本地 synthetic 适配器（`test_local_data.py`，22 用例）
- 事件去重/防乱序/429 退避（`test_sync.py`）
- 审批状态机：生命周期、幂等、未知 action、角色、stale、UNKNOWN、并发 20 抢锁、跨店隔离（`test_approval.py`）
- API：401/错误 token、shop 隔离、422/404、synthetic 声明、operation 端到端（`test_api.py` / `test_operations_api.py`）
- webhook：重复事件、乱序、校验、店铺白名单（`test_webhook_api.py`）
- 限流：令牌桶计数与分桶隔离（`test_ratelimit.py`）
- 迁移：upgrade head 建表/索引/唯一约束 + downgrade base（`test_migrations.py`）

## 4. 未完成 / 阶段 2 承接

1. 只读接口仍是 synthetic 适配器（未接 PG 仓储），且响应是裸 dict（缺 Pydantic response schema）；
2. 业务模块（shops/products/orders/inventory/reports/advertising/ad_shield）只建了 `shops` 表，其余模块未落地；
3. `orders.last_update_time` / `sync_cursor.value` 仍为字符串时间；`inventory` 字段不全；
4. 外键（→ shops）未加；无 RLS；
5. webhook 未做 HMAC 验签；
6. Docker Compose 已提供但本机无 Docker，未实测 `docker compose up`；
7. 目标仓库尚未推送（GitHub 上 `crossborder-ops` 不存在，需要先建空仓库/提供凭证）。
