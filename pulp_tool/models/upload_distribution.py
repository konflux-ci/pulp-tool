"""Distribution URL map for upload results."""

from __future__ import annotations

from pydantic import Field

from .base import KonfluxBaseModel


class DistributionUrlMap(KonfluxBaseModel):
    """Repository-type to distribution base URL mapping for results JSON."""

    urls: dict[str, str] = Field(default_factory=dict)

    def get(self, repo_type: str) -> str | None:
        return self.urls.get(repo_type)

    def __getitem__(self, repo_type: str) -> str:
        return self.urls[repo_type]

    def items(self):
        return self.urls.items()

    def keys(self):
        return self.urls.keys()

    @classmethod
    def from_dict(cls, data: dict[str, str] | None) -> DistributionUrlMap:
        return cls(urls=dict(data or {}))

    def to_dict(self) -> dict[str, str]:
        return dict(self.urls)
