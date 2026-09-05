"""
订阅配置存取（建议 #11 · T-D11）
订阅以 YAML 存在 ``data/subscriptions/{name}.yaml``，默认用户 ``default``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_USER = "default"


@dataclass
class Subscription:
    name: str = DEFAULT_USER
    companies: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "companies": self.companies,
                "categories": self.categories, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict[str, Any], name: str = DEFAULT_USER) -> "Subscription":
        return cls(
            name=d.get("name", name),
            companies=list(d.get("companies", []) or []),
            categories=list(d.get("categories", []) or []),
            note=d.get("note", ""),
        )


class SubscriptionStore:
    def __init__(self, dir_path: str | Path = "data/subscriptions") -> None:
        self.dir = Path(dir_path)

    def _path(self, name: str) -> Path:
        safe = "".join(c for c in name if c.isalnum() or c in ("-", "_")) or DEFAULT_USER
        return self.dir / f"{safe}.yaml"

    def exists(self, name: str = DEFAULT_USER) -> bool:
        return self._path(name).exists()

    def get(self, name: str = DEFAULT_USER) -> Subscription:
        p = self._path(name)
        if not p.exists():
            return Subscription(name=name)
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return Subscription.from_dict(data, name)

    def save(self, sub: Subscription) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self._path(sub.name)
        p.write_text(yaml.safe_dump(sub.to_dict(), allow_unicode=True, sort_keys=False),
                     encoding="utf-8")
        return p

    def list_all(self) -> list[Subscription]:
        if not self.dir.exists():
            return []
        return [Subscription.from_dict(yaml.safe_load(p.read_text(encoding="utf-8")) or {}, p.stem)
                for p in sorted(self.dir.glob("*.yaml"))]

    def delete(self, name: str = DEFAULT_USER) -> bool:
        p = self._path(name)
        if p.exists():
            p.unlink()
            return True
        return False

    # ── 增删（CLI 用） ──────────────────────────────
    def add(self, name: str, companies: list[str] | None = None,
            categories: list[str] | None = None) -> Subscription:
        sub = self.get(name)
        for c in companies or []:
            c = c.strip()
            if c and c not in sub.companies:
                sub.companies.append(c)
        for c in categories or []:
            c = c.strip()
            if c and c not in sub.categories:
                sub.categories.append(c)
        self.save(sub)
        return sub

    def remove(self, name: str, companies: list[str] | None = None,
               categories: list[str] | None = None) -> Subscription:
        sub = self.get(name)
        for c in companies or []:
            if c in sub.companies:
                sub.companies.remove(c)
        for c in categories or []:
            if c in sub.categories:
                sub.categories.remove(c)
        self.save(sub)
        return sub
