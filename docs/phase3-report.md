# 阶段 3 报告：Meta Marketing API 集成（Mock-first）

> 阶段结论：**验收通过**。7 个 Meta 模块落地；无真实凭证时走 Mock 且**显式标记**；
> 真实 PG 上三个迁移 upgrade/downgrade/upgrade 全部 rc=0；126 个测试全绿（新增 15 个）。

## 1. 新增文件

| 文件 | 职责 |
|---|---|
| `integrations/meta/client.py` | Graph API 客户端：分页（next/cursor）、429/5xx 重试、Retry-After、指数退避、超时、异常分类、token 脱敏、指标 |
| `integrations/meta/errors.py` | 6 类异常：Config / Auth / Permission / RateLimited / Server / Network |
| `integrations/meta/oauth.py` | 授权 URL、code 换 token、长期 token、加密存储、7 天过期检查与自动刷新 |
| `integrations/meta/accounts.py` | 广告账户查询 |
| `integrations/meta/campaigns.py` | Campaign 查询 |
| `integrations/meta/adsets.py` | AdSet 查询 |
| `integrations/meta/ads.py` | Ad 查询 |
| `integrations/meta/insights.py` | Insights 按天分页拉取 + 行归一化（purchase 归因） |
| `integrations/meta/mock.py` | Mock 适配器：形状一致、显式 `mock: true`、可模拟分页 |
| `integrations/meta/__init__.py` | 工厂 `build_meta_client()` + `meta_status()` |
| `core/crypto.py` | Fernet 加解密 + 掩码（生产未配 key 时 fail-closed） |
| `models/credentials.py` | `shop_credentials` 表（密文 token） |
| `repositories/credentials.py` | 凭证 upsert / 查询 |
| `services/meta_sync.py` | 账户/结构/Insights 同步，全部幂等 upsert，source 标记 meta/mock |
| `api/routers/meta.py` | 状态 / OAuth / 账户 / 同步 |
| `alembic/versions/*_meta_credentials_and_insight_source.py` | 新表 + `ad_insights.source`（带 default，老数据可升级） |
| `tests/test_meta.py` | 15 个用例 |
| `docs/meta-integration.md` | 对接说明 |

## 2. 核心逻辑

- **Mock-first**：`META_MOCK=true` 返回合成数据并带 `mock` 标记；`META_MOCK=false` 且无 token → `MetaConfigError`（不静默降级）。
- **分页**：优先 `paging.next`，否则 cursor after；硬上限 100 页。
- **限流**：429 优先 `Retry-After`，缺失时指数退避 + jitter，最多重试 3 次；5xx 同样重试。
- **异常分类**（不混为一谈）：401→Auth、403→Permission、429→RateLimited、5xx→Server、超时→Network；与广告盾 R401/R403/R429/R5XX 一一对应。
- **Token 安全**：Fernet 加密落库，日志统一 `redact()`，只输出 `EAAG***oken`；过期前 7 天自动换长期 token。
- **同步幂等**：账户/结构按业务键 upsert；Insights 按 `(shop, level, entity, date)` 唯一，重复同步只更新；`ad_insights.source` 记录来源。

## 3. 测试结果

```
pytest -q  →  126 passed（10.2s）
```

新增覆盖：分页 next / cursor、429 Retry-After、重试耗尽、401/403/5xx/超时分类、无 token 配置错误、
token 不落日志（caplog）、加密往返与掩码、Mock 显式标记、同步幂等 + source、API 状态/同步/账户。

**真实 PostgreSQL**：`upgrade head → downgrade base → upgrade head` 全 rc=0；19 张表 / 22 外键 / 54 索引；
`shop_credentials.access_token_encrypted` 列存在。

## 4. 未完成

- 真实 Meta App 未联调（无凭证，按设计走 Mock）；
- OAuth 回调路由（`/oauth/callback`）未实现，当前通过接口提交 code；
- Ad Review 状态采集（effective_status/issues_info）留到阶段 4；
- Insights 归因只取 `purchase`，完整 ACOS 口径在阶段 5；
- 目标仓库仍未 push（GitHub 仓库不存在）。
