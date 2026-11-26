# Meta Marketing API 对接说明（阶段 3）

## 1. 模式：Mock-first，绝不假装真实成功

| 配置 | 行为 |
|---|---|
| `META_MOCK=true`（默认） | 使用 `MockMetaClient`：返回合成数据，每个响应带 `mock: true` / `source: "mock"`；`/api/v1/meta/status` 明确显示 mock |
| `META_MOCK=false` + token | 使用 `MetaClient` 请求真实 Graph API |
| `META_MOCK=false` + 无 token | **直接抛 `MetaConfigError`**，不会偷偷降级成 mock |

Insights 落库时 `ad_insights.source` 记录 `meta` / `mock`，报表和接口都能追溯来源。

## 2. 目录

```
crossborder_ops/integrations/meta/
  client.py     HTTP 客户端：分页、重试/退避、超时、异常分类、token 脱敏
  oauth.py      授权链接 / code 换 token / 长期 token / 加密存储 / 过期检查
  accounts.py   GET me/adaccounts
  campaigns.py  GET {account_id}/campaigns
  adsets.py     GET {campaign_id}/adsets
  ads.py        GET {adset_id}/ads
  insights.py   GET {account_id}/insights（按天、分页、归一化）
  mock.py       Mock 适配器（形状一致，显式 mock 标记）
  errors.py     MetaAuthError / MetaPermissionError / MetaRateLimited / MetaServerError / MetaNetworkError / MetaConfigError
```

## 3. 请求与分页

- 基础 URL：`{META_GRAPH_URL}/{META_API_VERSION}`（默认 `https://graph.facebook.com/v21.0`）；
- 分页优先跟随 `paging.next`（绝对 URL），否则用 `paging.cursors.after` 重新请求；
- 单次分页有硬上限（100 页），防止异常翻页死循环。

## 4. 限流与退避

1. HTTP 429 或错误码 `4 / 17 / 32 / 613` → 视为限流；
2. 优先使用 `Retry-After` 头，缺失时指数退避 + jitter（0.5s 起，上限 30s）；
3. 最多重试 `META_MAX_RETRIES`（默认 3）次，耗尽抛 `MetaRateLimited`；
4. 5xx 同样重试，耗尽抛 `MetaServerError`；
5. 指标：`crossborder_meta_requests_total{outcome}`、`crossborder_meta_throttled_total`。

## 5. 异常分类（与广告盾规则对齐）

| 异常 | 触发条件 | 广告盾 rule |
|---|---|---|
| `MetaAuthError` | 401 / 错误码 190 | `R401_TOKEN_INVALID`（critical，需要重新授权） |
| `MetaPermissionError` | 403 / 权限错误码 | `R403_PERMISSION`（critical，需人工确认，不等于封号） |
| `MetaRateLimited` | 429 / 限流码 | `R429_RATE_LIMIT`（info，可恢复） |
| `MetaServerError` | 5xx | `R5XX_PLATFORM`（warn，平台故障） |
| `MetaNetworkError` | 超时/连接中断 | 结果未知：读操作可重试，写操作不自动重试 |

## 6. Token 安全

- Token **只加密落库**（Fernet，`TOKEN_ENCRYPTION_KEY`），明文只在内存中短暂存在；
- 生产环境未配置 `TOKEN_ENCRYPTION_KEY` 时加密直接失败（fail-closed）；
- 日志与异常信息中只出现脱敏值（`EAAG***oken`），请求参数在日志前统一 `redact()`；
- 过期前 7 天自动用 `fb_exchange_token` 换长期 token（`refresh_if_needed`）。

## 7. 同步

`POST /api/v1/meta/sync {since, until}`：

1. `sync_accounts`：按 `(shop, platform, external_id)` upsert；
2. `sync_campaigns`：按 `(account_id, external_id)` upsert；
3. `sync_adsets_and_ads`：按 `(campaign_id/adset_id, external_id)` upsert；
4. `sync_insights`：按 `(shop, level, entity, date)` 幂等 upsert（重复同步只更新不新增）。

返回 `{source, accounts, campaigns, adsets, ads, insights}`；重复调用结果一致（有测试覆盖）。

## 8. 测试（不需要真实凭证）

`tests/test_meta.py` 覆盖：分页（next/cursor）、429 Retry-After、重试耗尽、401/403/5xx/超时分类、
token 不落日志、加密往返与掩码、Mock 显式标记、同步幂等与 source 标记、API 状态/同步。

## 9. 未完成

- 真实环境未联调（没有 Meta App/Token）；
- 用户级授权回调路由（`/oauth/callback`）未实现，当前是接口接收 code 后换 token；
- Ad Review 状态采集（`effective_status` / `issues_info`）尚未接入，阶段 4 实现；
- Insights 的 `actions` 归因口径只取 `purchase`，ACOS 口径在阶段 5 统一。
