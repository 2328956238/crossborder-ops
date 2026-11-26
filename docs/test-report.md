# 测试报告

## 1. 环境

| 项 | 值 |
|---|---|
| Python | 3.12（项目 venv） |
| 测试框架 | pytest 9 + pytest-asyncio（asyncio_mode=auto） |
| 业务库 | SQLite（aiosqlite，临时文件，NullPool + WAL）；**同一套迁移在 PostgreSQL 16 上另做验证** |
| 外部依赖 | 无真实 Meta/Amazon 凭证；Meta 走 Mock / httpx.MockTransport |
| Redis | fakeredis（Lua 令牌桶） |

## 2. 命令与结果

```bash
pytest -q
# 139 passed in ~9s
```

| 阶段 | 测试数（累计） | 新增覆盖 |
|---|---|---|
| 阶段 1 | 100 | 领域规则 42、本地 synthetic 适配器 22、事件去重/乱序/429 退避、审批状态机 8、API 认证与隔离、限流 3、迁移 upgrade/downgrade |
| 阶段 2 | 111 | 商品/订单/库存/广告/广告盾规则/报表 + shop 隔离、参数校验、迁移"老数据升级" |
| 阶段 3 | 126 | Meta 分页（next/cursor）、429 Retry-After、重试耗尽、401/403/5xx/超时分类、token 不落日志、加密往返、Mock 显式标记、同步幂等 |
| 阶段 4 | 135 | CVR/账户状态规则、错误分类、巡检去重、审核 `manual_required`、通知成功/失败、巡检 API 权限 |
| 阶段 5 | 139 | 商品销售排行（含跨店隔离）、日期区间过滤、广告趋势逐日 ACOS、多店铺汇总字段 |

## 3. 需求 §8 测试清单对照

| 要求 | 覆盖用例 |
|---|---|
| 店铺数据隔离 | `test_api.py`、`test_business_modules.py`、`test_meta.py`、`test_reports_phase5.py` |
| API 参数校验 | `test_api.py`（422/404）、`test_business_modules.py`（负价/limit）、`test_reports_phase5.py`（limit=0） |
| 数据同步幂等 | `test_sync.py`、`test_meta.py`（同步两次结果一致）、`test_ad_shield_patrol.py`（审核 upsert） |
| 事件重复处理 | `test_sync.py`（并发 50 次只入库 1 次）、`test_webhook_api.py`（duplicate） |
| 乱序事件处理 | `test_sync.py`、`test_webhook_api.py`（旧事件不覆盖新状态） |
| 数据库事务 | `test_approval.py`（状态机条件更新）、`test_operations_api.py` |
| 并发数据写入 | `test_approval.py`（20 并发只 1 个 approved）、`test_sync.py`（50 并发去重） |
| Meta API 分页 | `test_meta.py::test_pagination_follows_next/cursor` |
| Meta API 限流 | `test_meta.py::test_429_retry_after_is_respected / exhausts_retries` |
| Token 过期 | `test_meta.py::test_401_is_auth_error` + `oauth.needs_refresh`/`refresh_if_needed` |
| 广告风险规则 | `test_ad_shield_patrol.py`（CVR/账户状态/错误分类/花费下降不判封号） |
| 重复告警抑制 | `test_ad_shield_patrol.py`（同窗口第二次巡检 0 新增；alerts dedupe_key） |
| 定时任务异常恢复 | 巡检 per-shop try/except（单店失败不影响其它店）+ `patrol_all_shops`；间隔任务由 APScheduler 兜底 |
| 数据库迁移 | `test_migrations.py`（空库 upgrade/downgrade、老数据升级、env.py 指向校验） |

## 4. 真实 PostgreSQL 验证（每阶段都跑）

| 阶段 | 迁移数 | upgrade→downgrade→upgrade | 结果 |
|---|---|---|---|
| 1 | 1 | rc=0 / rc=0 / rc=0 | 8 表 |
| 2 | 2 | rc=0 / rc=0 / rc=0 | 19 表 / 22 外键 / 51 索引 |
| 3 | 3 | rc=0 / rc=0 / rc=0 | 19 表 / 22 外键 / 54 索引 |
| 4 | 4 | rc=0 / rc=0 / rc=0 | 19 表 / 21 外键 / 54 索引 |
| 5（最终） | 5 | rc=0 / rc=0 / rc=0 | **20 表 / 22 外键 / 58 索引** |

## 5. 其他静态校验

- `docker-compose.yml`：YAML 解析通过，services = `app/db/redis`（本机无 Docker，未端到端启动）；
- `.env.example`：23 个键全部能映射到 `Settings` 字段（无悬空配置）；
- 代码禁用词扫描：`crossborder_ops/` 内无 `langgraph`、`LangGraph`、`FakeLLM`、`orchestrat*`。

## 6. 已知限制

1. 真实 Meta API/App 未联调（无凭证）；
2. Docker Compose 未在本机实测（无 Docker）；
3. SQLite 为测试库，生产 PostgreSQL 已验证迁移但未做压测；
4. GitHub 目标仓库尚不存在，未 push。
