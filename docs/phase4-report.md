# 阶段 4 报告：广告盾（巡检 / 审核状态 / 异常检测 / 告警）

> 阶段结论：**验收通过**。规则独立于路由；巡检可手动/定时；审核状态与原因落库、拿不到原因标记人工核实；
> 401/403/429/5xx 各自成规则；花费下降只 warn 且明确"不等于封号"；告警去重 + 通知失败不影响巡检。
> 真实 PG 四个迁移 upgrade/downgrade/upgrade 全 rc=0；135 个测试全绿（新增 9 个）。

## 1. 新增/修改文件

| 文件 | 说明 |
|---|---|
| `services/ad_shield_rules.py`（扩展） | +CVR 规则、账户状态映射、Meta 错误分类、日汇总与基线 |
| `services/ad_shield_patrol.py`（新） | 巡检编排：账户状态 → 审核状态 → Insights 异常 → 落库 → 告警 |
| `services/notifications.py`（新） | Log / Webhook 通知，`deliver_pending` 回写 sent/failed |
| `workers/jobs.py`（新） | APScheduler 注册巡检任务（每 6 小时） |
| `api/routers/ad_shield.py`（扩展） | `POST /patrol`（admin）、`GET /reviews` |
| `integrations/meta/ads.py`（扩展） | `list_ads_with_review`（effective_status + issues_info） |
| `integrations/meta/mock.py`（扩展） | Mock 广告审核状态（含"有原因/无原因"两种） |
| `models/ad_shield.py` + 迁移 0004 | 审核快照存 Meta 外部 ad_id（去除本地 FK 误约束） |
| `main.py` / `config.py` | 调度注册；通知与阈值配置 |
| `tests/test_ad_shield_patrol.py` | 9 个用例 |
| `docs/ad-shield-rules.md` | **规则说明（交付物）** |

## 2. 巡检流程

```
Meta 账户状态 ─┐
Meta 广告审核 ─┼─▶ 规则引擎（纯函数）─▶ 风险事件(去重) ─▶ 告警(去重) ─▶ 通知(log/webhook)
Meta Insights ─┘                          │
                                          └─▶ 审核快照 ad_reviews（manual_required 标记）
```

- 账户状态码映射成 R006 系列（禁用/未结清/风险审核/宽限/关闭）；
- 审核状态 `DISAPPROVED/REJECTED/WITH_ISSUES` → R004；`issues_info` 为空 → `manual_required=True`；
- 指标规则用「今天 vs 前 7 天」基线；分母为 0 时规则跳过（不误报）；
- 巡检本身不修改任何账户/广告对象。

## 3. 安全与诚实性

| 约束 | 实现 |
|---|---|
| 规则独立于路由 | 规则全在 `ad_shield_rules.py`，无 FastAPI/SQL 依赖 |
| 花费下降 ≠ 封号 | R001 只 warn，detail 写"不等于封号，需核查预算/审核/停投" |
| 401/403/429/5xx 不混淆 | 分别 R401 / R403 / R429 / R5XX；401≠403≠账户禁用 |
| 拿不到审核原因 | `manual_required=True`，不猜原因 |
| Mock 不冒充真实 | 巡检结果带 `source=mock`；`/meta/status` 明示 |
| 告警不刷屏 | 风险事件唯一键 + alerts.dedupe_key 唯一 |
| 通知失败不影响巡检 | 捕获异常 → alert=failed，巡检继续 |

## 4. 测试结果

```
pytest -q  →  135 passed（10.2s）
```

阶段 4 新增覆盖：
- 规则：CVR 下降、账户状态映射、Meta 错误分类、daily totals/baseline；
- 巡检：Mock 下生成审核记录与 2 个风险事件；同窗口第二次巡检 0 新增；审核 upsert 幂等；无原因审核 `manual_required=True`；
- 通知：webhook 成功标记 sent、失败标记 failed（进程不崩）；
- API：viewer 触发巡检 403、admin 200、审核列表可查。

**真实 PostgreSQL**：4 个迁移 `upgrade/downgrade/upgrade` rc=0；19 表 / 21 外键 / 54 索引；`ad_reviews.ad_id` 本地外键已按设计移除。

## 5. 未完成

- 真实 Meta 环境未联调（无凭证）；
- 通知渠道只有 log/webhook（未接企微/钉钉/邮件）；
- 巡检窗口为"当天"，历史补检需手动指定日期（接口未暴露）；
- 广告竞价旧能力未并入统一审批（旧仓库 `approval.py` 的 rollback 语义未迁移，按之前确认"不保留"处理，文档已注明）。
