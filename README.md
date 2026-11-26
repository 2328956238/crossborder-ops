# crossborder-ops

跨境电商运营自动化管理系统 —— 从 `amazon-agent-hub` 迁移重构而来。

**与旧项目的本质区别**：本系统**没有** Agent、多 Agent、LangGraph、LLM、Prompt、Checkpointer。
它是传统 Python 后端分层架构：`api → schemas → services → repositories → models`，
把「运营数据获取 → 清洗 → 报表 → 广告风险巡检 → 审批后执行」做成可审计的业务系统。

## 1. 技术栈

- Python 3.12 / FastAPI / Pydantic v2
- SQLAlchemy 2.0 Async + PostgreSQL（asyncpg）
- Redis（限流令牌桶）
- APScheduler（定时巡检 / 同步）
- HTTPX（外部平台调用）
- Alembic（数据库迁移）
- Prometheus（指标）
- Docker Compose

## 2. 目录结构

```
crossborder_ops/
  main.py            # create_app() 工厂 + lifespan
  config.py          # pydantic-settings，全部配置来自环境变量
  db.py              # async engine / session
  metrics.py         # Prometheus 指标与中间件
  models/            # SQLAlchemy 模型（shops / orders / events / inventory / ad_report / operation / audit）
  schemas/           # Pydantic 请求响应模型
  repositories/      # 数据库访问（shop_id 强制在签名里出现）
  services/          # 业务服务（审批状态机、事件同步、补拉、执行器）
  api/               # 路由 + 依赖（认证 / 会话 / 适配器）
  core/              # 错误类型、认证与租户上下文、限流器
  domain/            # 纯业务规则（定价 / 库存 / Listing 校验 / 广告指标），零 I/O
  integrations/      # 外部平台集成（local=本地合成数据；meta=阶段 3）
  workers/           # APScheduler 定时任务
alembic/             # 数据库迁移（空库可初始化）
tests/               # pytest（不需要真实平台凭证）
data/amazon/         # synthetic 合成数据（非真实卖家数据）
docs/                # 架构 / 阶段报告 / Meta 对接 / 广告盾规则
```

## 3. 快速开始

### 方式 A：Docker Compose（推荐，含 PostgreSQL + Redis）

```bash
cp .env.example .env
docker compose up --build
# 服务: http://127.0.0.1:8000  (健康检查 /healthz，指标 /metrics)
```

### 方式 B：本地开发

```bash
python -m venv .venv && . .venv/Scripts/activate    # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# 开发可用 SQLite 直接跑（生产必须 PostgreSQL）：
#   DATABASE_URL=sqlite+aiosqlite:///./dev.db
alembic upgrade head
uvicorn crossborder_ops.main:app --reload
```

## 4. 数据库迁移

```bash
alembic upgrade head      # 空库 → 全表（含索引/唯一约束）
alembic downgrade base    # 回退
alembic revision --autogenerate -m "..."   # 新增迁移
```

生产环境 `AUTO_CREATE_TABLES=false`，只允许通过迁移变更 schema。

## 5. API（阶段 1）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` `/readyz` `/metrics` | 健康检查 / 就绪 / Prometheus |
| POST | `/webhook/amazon` | 平台事件（去重 + 订单防乱序） |
| GET | `/api/v1/operations` | 审批列表（shop 隔离） |
| GET | `/api/v1/operations/{id}` | 操作详情 + 审计 |
| POST | `/api/v1/operations/{id}/approve` | 审批（风险等级 → 角色） |
| POST | `/api/v1/operations/{id}/reject` | 拒绝 |
| POST | `/api/v1/operations/{id}/execute` | 执行（执行前重核旧值） |
| GET | `/api/v1/amazon/{products,orders,inventory,advertising,summary,pricing}` | 旧只读接口（synthetic 适配器，阶段 5 收口） |
| GET/POST/PATCH | `/api/v1/shops`、`/api/v1/products` | 店铺 / 商品 |
| GET | `/api/v1/orders`、`/api/v1/orders/stats`、`/api/v1/orders/{id}` | 订单 |
| GET/PUT/POST | `/api/v1/inventory`、`/api/v1/inventory/low-stock`、`/api/v1/inventory/{sku}/adjust` | 库存 |
| GET/POST | `/api/v1/advertising/{accounts,campaigns,adsets,ads,insights,metrics}` | 广告域 |
| GET/POST | `/api/v1/ad-shield/{risks,alerts,reviews,patrol}`、`/risks/{id}/ack`、`/risks/{id}/resolve` | 广告盾（patrol 仅 admin） |
| GET | `/api/v1/reports/{sales,ads,inventory-warnings,overview}` | 经营报表 |
| GET/POST | `/api/v1/meta/{status,oauth/authorize-url,oauth/exchange,accounts,sync}` | Meta 集成（Mock-first） |

认证：`Authorization: Bearer <token>`，token → `{shop_id, actor, role}` 由服务端映射；
**shop_id 不允许由客户端指定**。生产环境未配置 `API_TOKENS` 时 fail-closed。

## 6. 测试

```bash
pytest -q
```

- 默认 SQLite（`tests/conftest.py` 自动配置临时库），不需要 PostgreSQL/Redis/平台凭证；
- 覆盖：领域规则、事件去重与防乱序、审批状态机（幂等/角色/stale/UNKNOWN/并发/跨店）、
  限流、API 认证与 shop 隔离、迁移 upgrade/downgrade。

## 7. 数据诚实性

- `data/amazon/*.json` 全部是 **synthetic** 合成数据，接口响应里带 `source: "synthetic"` 声明；
- 不伪造真实 Amazon / Meta API 调用；无凭证时使用 Mock Adapter 并显式标记；
- 阶段 3 接入 Meta Marketing API 时同样遵守：没真实凭证就不假装成功。

## 8. 阶段进度

- ✅ 阶段 1：复制清理 + 分层骨架 + PostgreSQL + Alembic + 审批/审计独立业务能力
- ✅ 阶段 2：七个业务模块（shops/products/orders/inventory/advertising/ad_shield/reports）+ 外键/索引/唯一约束
- ✅ 阶段 3：Meta Marketing API 集成（OAuth / 账户 / Campaign / AdSet / Ad / Insights + Mock，分页/限流/退避/幂等）
- ✅ 阶段 4：广告盾（定时巡检 / 审核状态采集 / 异常规则 / 告警通知 / 状态流转）
- ⬜ 阶段 5：经营报表（销售额 / 订单 / 排行 / 库存预警 / 广告指标 / 多店铺汇总）

详细说明见 `docs/architecture.md` 与 `docs/phase1-report.md`。
