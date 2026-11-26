# SP-API Sandbox 示例 fixture（官方公开示例，非真实卖家数据）

这些文件是从 **Amazon 官方 Swagger 模型** 里抽取的 `x-amzn-api-sandbox` 内容，用于对齐
真实 SP-API 的请求/响应结构。**它们不是真实卖家数据，也不是我们调用接口拿到的结果。**

## 来源

| fixture | API | 版本 | 官方模型文件 |
|---|---|---|---|
| `orders.json` | Orders API | 2026-01-01 | [orders_2026-01-01.json](https://github.com/amzn/selling-partner-api-models/blob/main/models/orders-api-model/orders_2026-01-01.json) |
| `catalog.json` | Catalog Items API | 2022-04-01 | [catalogItems_2022-04-01.json](https://github.com/amzn/selling-partner-api-models/blob/main/models/catalog-items-api-model/catalogItems_2022-04-01.json) |
| `pricing.json` | Product Pricing API | 2022-05-01 | [productPricing_2022-05-01.json](https://github.com/amzn/selling-partner-api-models/blob/main/models/product-pricing-api-model/productPricing_2022-05-01.json) |
| `fbaInventory.json` | FBA Inventory API | v1 | [fbaInventory.json](https://github.com/amzn/selling-partner-api-models/blob/main/models/fba-inventory-api-model/fbaInventory.json) |
| `reports.json` | Reports API | 2021-06-30 | [reports_2021-06-30.json](https://github.com/amzn/selling-partner-api-models/blob/main/models/reports-api-model/reports_2021-06-30.json) |

抽取方式：递归扫描模型 JSON，找到 `x-amzn-api-sandbox` 节点，取 `static[]` 里的
`request` / `response`（每个 API 保留前 2 组），连同所在 operation 路径一起保存。

## Static vs Dynamic Sandbox（来自官方文档）

- **Static sandbox**：按请求参数做模式匹配，返回 Swagger 模型里写死的 mock 响应。
  文档：<https://developer-docs.amazon/sp-api/docs/sp-api-sandbox>
- **Dynamic sandbox**：把请求代理到 sandbox 后端，按参数返回（可能带状态的）响应。
  模型里对应 `x-amzn-api-sandbox: {"dynamic": {}}`。

本仓库的抽取结果：

| API | sandbox 类型 | 是否有 static 示例 |
|---|---|---|
| Orders | Static + AI | ✅ 2 组 |
| Catalog Items | Static + AI | ✅ 2 组 |
| Product Pricing | Static + AI | ✅ 2 组 |
| Reports | Static + AI | ✅ 2 组 |
| **FBA Inventory** | **Dynamic + AI** | ❌ 无 static 示例（`fbaInventory.json` 里 samples 为空，meta.sandbox_type=dynamic-only） |

- Sandbox 端点（官方）：`sandbox.sellingpartnerapi-na.amazon.com`（NA）、`-eu`、`-fe`；
  限流 rate=5 rps / burst=15。
- 本仓库**没有**调用这些端点：没有 LWA 凭证、没有卖家授权，按项目约定不连接生产接口。

## 与我们自己的合成数据的关系

- `data/amazon/fixtures/spapi/*.json` —— 官方示例，用于**字段结构对齐**；
- `data/amazon/{products,orders,inventory,pricing,advertising}.json` —— 我们自己造的
  **synthetic 数据**，用于演示业务逻辑（字段是简化视图，不是 SP-API 原始结构）。

两套数据不要混用，也不要把 synthetic 数据说成 SP-API 返回。
