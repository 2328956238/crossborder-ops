# 广告盾风险规则说明（阶段 4）

## 1. 定位

广告盾只做四件事：**检测 → 记录 → 告警 → 人工处置**。
**不自动修改账户、预算、广告状态**；任何写操作都必须走统一审批链（Operation 状态机）。
规则全部是纯函数（`services/ad_shield_rules.py`），与 API 路由、数据库完全解耦。

## 2. 规则表

| rule_code | 触发条件 | 级别 | 说明 / 不能得出的结论 |
|---|---|---|---|
| `R001_SPEND_DROP` | 今日花费 < 前 7 日均值 × 30% | warn | **花费下降 ≠ 封号**：可能是停投、预算调整、审核拒登、数据延迟。需人工核查 |
| `R002_CTR_DROP` | 今日 CTR < 前 7 日均值 × 50% | warn | 可能是素材疲劳/受众变化/竞争加剧 |
| `R003_CPA_SPIKE` | 今日 CPA > 前 7 日均值 × 200% | warn | 先查落地页与转化归因，不能直接归因账户问题 |
| `R004_REVIEW_REJECTED` | 广告 `effective_status ∈ {REJECTED, DISAPPROVED, WITH_ISSUES}` | critical（有原因）/ warn（无原因） | 拒审是广告级问题，不是账户风险 |
| `R005_CVR_DROP` | 今日 CVR < 前 7 日均值 × 50% | warn | 转化下降可能来自流量结构变化 |
| `R006_ACCOUNT_DISABLED` | `account_status = 2` | critical | 需人工确认原因，**不等于"被封号"结论** |
| `R006_ACCOUNT_UNSETTLED` | `account_status = 3` | warn | 未结清款项 |
| `R006_ACCOUNT_PENDING_RISK_REVIEW` | `account_status = 7` | warn | 平台风险审核中 |
| `R006_ACCOUNT_IN_GRACE_PERIOD` | `account_status = 9` | warn | 宽限期 |
| `R006_ACCOUNT_CLOSED` | `account_status ∈ {100, 201}` | critical | 账户已关闭 |
| `R401_TOKEN_INVALID` | Meta 401 / OAuthException 190 | critical | Token 失效，重新授权即可；不是账户问题 |
| `R403_PERMISSION` | Meta 403 / 权限错误码 | critical | 权限受限，需人工确认；**不等于封号** |
| `R429_RATE_LIMIT` | Meta 429 / 限流码 4/17/32/613 | info | 限流可恢复，退避重试 |
| `R5XX_PLATFORM` | Meta 5xx | warn | 平台故障，不是账户问题 |
| `R_NETWORK_UNKNOWN` | 超时 / 连接中断 | warn | 结果未知，写操作不得重试 |
| `R_CONFIG_MISSING` | 缺少 app/token 配置 | warn | 配置问题 |

阈值都可通过环境变量调整（`AD_SHIELD_*_RATIO`）。

## 3. 去重与告警抑制

- 风险事件唯一键：`(shop_id, rule_code, entity_type, entity_id, window_key)`；
- `window_key` 默认是巡检当天（UTC 日期）→ 同一规则同一实体同一天只报一次；
- 告警表 `alerts.dedupe_key = shop:rule:entity:window` 唯一，通知失败也不会重复刷屏；
- 通知渠道：`NOTIFY_CHANNEL=log`（默认）或 `webhook`（`NOTIFY_WEBHOOK_URL`）；
  通知失败只把 alert 标记 `failed`，不影响巡检与风险事件。

## 4. 状态流转

```
open ──ack──▶ acknowledged ──resolve──▶ resolved
  └──────────resolve──────────────────▶ resolved
```
非法流转（如已 resolved 再 ack）→ 422；所有流转保留 `acked_by` / `resolved_by`。

## 5. 数据来源与"人工核实"

| 数据 | 来源 | 拿不到时的处理 |
|---|---|---|
| 账户状态 | Meta `me/adaccounts.account_status` | 该账户跳过状态检查 |
| 审核状态 | `ads.effective_status` + `issues_info` | **`manual_required=True`**，不猜原因 |
| 消耗/CTR/CVR/CPA | Meta Insights 按天分页 | 该账户本期不出指标规则 |
| API 错误 | 客户端异常分类（401/403/429/5xx/网络） | 各自成规则，不合并不误判 |

## 6. 巡检调度

- APScheduler 每 6 小时执行 `workers/jobs.ad_shield_patrol_job`（`SCHEDULER_ENABLED=true` 时）；
- 手动触发：`POST /api/v1/ad-shield/patrol`（仅 admin）；
- 每店独立凭证（无凭证 → Mock 模式，结果标记 `source=mock`）。

## 7. 验证方式

- 规则单测：`tests/test_ad_shield_patrol.py`（CVR 规则、账户状态映射、错误分类、daily totals/baseline）；
- 巡检集成测试：Mock Meta → 生成审核记录/风险事件，第二次巡检 0 新增（去重）；
- 通知测试：webhook MockTransport 成功/失败两条路径；
- API 测试：viewer 触发 403、admin 触发 200、审核列表可查。
