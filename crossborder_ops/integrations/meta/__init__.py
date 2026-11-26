"""Meta（Facebook）Marketing API 集成包 —— 阶段 3 实现。

规划模块：
    client.py      HTTP 客户端：限流、Retry-After、指数退避、超时与异常分类
    oauth.py       OAuth 授权码换 token、刷新、加密存储
    accounts.py    广告账户查询
    campaigns.py   Campaign 查询
    adsets.py      AdSet 查询
    ads.py         Ad 查询
    insights.py    Insights 分时段同步（分页 + 幂等写入）
    mock.py        无真实凭证时的 Mock Adapter（绝不伪造真实调用成功）

约束：
- access_token 只进加密存储/内存，不写日志；
- 无凭证时 meta_mock=True，客户端返回明确的 mock 标记，不假装成功。
"""
