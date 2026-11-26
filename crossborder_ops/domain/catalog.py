"""Listing 内容质量校验与修改预览（纯函数，无 I/O）。

说明：没有真实 Product Type Definition Schema，字段约束使用**本地演示规则**（DEMO_RULES），
并在输出里明确标注 rule_source="demo_rules"，不冒充 Amazon 官方 Schema。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

IMAGE_URL_RE = re.compile(r"^https://[\w./-]+\.(jpg|jpeg|png|webp)$", re.IGNORECASE)

DEMO_RULES = {
    "title_min": 10, "title_max": 200,
    "bullets_min": 1, "bullets_max": 5, "bullet_len_min": 10, "bullet_len_max": 500,
    "description_min": 30, "description_max": 2000,
    "images_min": 1, "images_max": 9,
    "required_attributes": ("brand", "category"),
    "valid_status": ("active", "inactive", "suppressed"),
}

EDITABLE_FIELDS = ("title", "description", "bullets", "images", "listing_status")


@dataclass(frozen=True)
class Issue:
    field: str
    code: str
    severity: str      # error / warning
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code,
                "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class ListingCheck:
    asin: str
    passed: bool
    issues: tuple[Issue, ...] = field(default_factory=tuple)
    rule_source: str = "demo_rules"

    def to_dict(self) -> dict[str, Any]:
        return {"asin": self.asin, "passed": self.passed, "rule_source": self.rule_source,
                "declaration": "没有真实 Product Type Definition Schema，校验使用本地演示规则",
                "issues": [i.to_dict() for i in self.issues]}


def validate_listing(product: dict) -> ListingCheck:
    r = DEMO_RULES
    issues: list[Issue] = []

    def add(field_name: str, code: str, severity: str, msg: str) -> None:
        issues.append(Issue(field_name, code, severity, msg))

    title = (product.get("title") or "").strip()
    if not title:
        add("title", "missing", "error", "标题为空")
    elif not r["title_min"] <= len(title) <= r["title_max"]:
        add("title", "length", "error",
            f"标题长度 {len(title)} 不在 {r['title_min']}..{r['title_max']}")

    bullets = product.get("bullets") or []
    if not isinstance(bullets, list) or not (r["bullets_min"] <= len(bullets) <= r["bullets_max"]):
        add("bullets", "count", "error", f"Bullet 数量需在 {r['bullets_min']}..{r['bullets_max']}")
    for i, b in enumerate(bullets if isinstance(bullets, list) else []):
        text = (b or "").strip()
        if not text:
            add("bullets", "empty", "error", f"第 {i + 1} 条 Bullet 为空")
        elif not r["bullet_len_min"] <= len(text) <= r["bullet_len_max"]:
            add("bullets", "length", "warning", f"第 {i + 1} 条 Bullet 长度异常: {len(text)}")

    desc = (product.get("description") or "").strip()
    if len(desc) < r["description_min"]:
        add("description", "length", "error", f"描述过短（{len(desc)} < {r['description_min']}）")
    elif len(desc) > r["description_max"]:
        add("description", "length", "warning", "描述过长")

    images = product.get("images") or []
    if not isinstance(images, list) or not (r["images_min"] <= len(images) <= r["images_max"]):
        add("images", "count", "error", f"图片数量需在 {r['images_min']}..{r['images_max']}")
    for i, url in enumerate(images if isinstance(images, list) else []):
        if not isinstance(url, str) or not IMAGE_URL_RE.match(url):
            add("images", "url_format", "error", f"第 {i + 1} 张图片地址格式不合法")

    attrs = dict(product.get("attributes") or {})
    # brand/category 在数据里可能是顶层字段，统一合并后再校验
    attrs.setdefault("brand", product.get("brand"))
    attrs.setdefault("category", product.get("category"))
    for key in r["required_attributes"]:
        if not str(attrs.get(key) or "").strip():
            add(f"attributes.{key}", "missing", "error", f"缺少必填属性 {key}")

    status = product.get("listing_status")
    if status not in r["valid_status"]:
        add("listing_status", "invalid", "error", f"Listing 状态不合法: {status}")

    return ListingCheck(asin=product.get("asin", ""),
                        passed=not any(i.severity == "error" for i in issues),
                        issues=tuple(issues))


def build_after_snapshot(product: dict, changes: dict) -> dict:
    """只允许修改 EDITABLE_FIELDS；未提供的字段沿用原值。"""
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"不支持修改字段: {', '.join(sorted(unknown))}")
    after = {k: product.get(k) for k in EDITABLE_FIELDS}
    after.update({k: v for k, v in changes.items()})
    return after


def diff_listing(before: dict, after: dict) -> list[dict]:
    """修改前后差异（只比较可编辑字段）。"""
    out = []
    for field_name in EDITABLE_FIELDS:
        b, a = before.get(field_name), after.get(field_name)
        if b != a:
            out.append({"field": field_name, "before": b, "after": a})
    return out
