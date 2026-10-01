"""Shared helpers for model tests."""

from typing import cast

from pydantic import AnyHttpUrl


def _http_url(url: str) -> AnyHttpUrl:
    """String literal where models expect AnyHttpUrl (Pydantic still validates on construct)."""

    return cast(AnyHttpUrl, url)


def _dist_map(urls: dict[str, str]) -> dict[str, AnyHttpUrl]:
    """Dict literal for PulpResultsDocument.distributions (values are coerced at runtime)."""

    return cast(dict[str, AnyHttpUrl], urls)
