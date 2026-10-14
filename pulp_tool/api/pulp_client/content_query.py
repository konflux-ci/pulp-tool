"""Content query, distribution URL building, and RPM lookup helpers for ``PulpClient``."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import httpx

from ...models.pulp_label_values import normalize_signed_by_value_for_pulp
from ...utils.constants import DEFAULT_CHUNK_SIZE, SUPPORTED_ARCHITECTURES
from ...utils.rpm_operations import parse_rpm_filename_to_nvr
from .distribution_urls import (
    build_rpm_distribution_url,
    build_rpm_packages_url_for_arch,
    rpm_distribution_base_url_from_labels,
)
from .helpers import EMPTY_RESPONSE_REQUEST, dedupe_results_by_pulp_href


def _normalize_signed_by_query_values(values: Sequence[str | None]) -> list[str]:
    """Apply the same signed_by substitution as upload so ``pulp_label_select`` queries work server-side."""
    result: list[str] = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        result.append(normalize_signed_by_value_for_pulp(s))
    return result


def _normalize_signed_by_query_string(signed_by: str) -> str:
    s = str(signed_by).strip()
    return normalize_signed_by_value_for_pulp(s) if s else s


def _filter_rpm_results_by_signed_by_labels(results: list[Any], signed_by_values: list[str]) -> list[Any]:
    """
    Keep RPM JSON rows whose pulp_labels.signed_by equals one of signed_by_values (exact, stripped).

    Used when Pulp's label filter cannot represent the value: ``pulp_label_select`` splits on commas
    before parsing terms, and pulpcore rejects storing label values containing comma or parentheses—
    clients may still pass raw strings when calling helpers, so match those client-side when needed.
    """
    wanted = {v.strip() for v in signed_by_values if v is not None and str(v).strip()}
    if not wanted:
        return list(results)
    out: list[Any] = []
    for item in results:
        labels = item.get("pulp_labels")
        if not isinstance(labels, dict):
            continue
        raw = labels.get("signed_by")
        if raw is None:
            continue
        raw_s = str(raw).strip()
        if raw_s in wanted or normalize_signed_by_value_for_pulp(raw_s) in wanted:
            out.append(item)
    return out


def _signed_by_values_require_client_label_filter(signed_by_values: Sequence[str | None]) -> bool:
    """True if any value must not be embedded in ``pulp_label_select=`` (comma or parentheses)."""
    for v in signed_by_values:
        if v is None:
            continue
        s = str(v)
        if "," in s or "(" in s or ")" in s:
            return True
    return False


class PulpClientContentQueryMixin:
    """Mixin: content discovery, RPM queries, and distribution URL construction."""

    # ============================================================================
    # Content Query Methods (migrated from ContentQueryMixin)
    # ============================================================================

    @staticmethod
    @lru_cache(maxsize=256)
    def _get_content_type_from_href(pulp_href: str) -> str:
        """
        Determine content type from pulp_href (cached for performance).

        Args:
            pulp_href: The Pulp href path

        Returns:
            Content type string (e.g., "rpm.package", "file.file", "unknown")
        """
        if "/rpm/packages/" in pulp_href:
            return "rpm.package"
        elif "/file/files/" in pulp_href:
            return "file.file"
        return "unknown"

    def _rpm_distribution_base_url_from_labels(
        self,
        labels: dict[str, str],
        *,
        target_arch_repo_build_scoped: bool = False,
    ) -> str:
        """Build RPM distribution base URL when using ``--target-arch-repo`` (per-arch base paths)."""
        return rpm_distribution_base_url_from_labels(
            base_url=str(self.config["base_url"]),
            namespace=self.namespace if isinstance(self.namespace, str) else "",
            labels=labels,
            target_arch_repo_build_scoped=target_arch_repo_build_scoped,
        )

    def _build_rpm_packages_url_for_arch(
        self,
        arch: str,
        relative_path: str,
        *,
        labels: dict[str, str] | None = None,
        target_arch_repo_build_scoped: bool = False,
    ) -> str:
        """Build RPM content URL under per-arch distribution (namespace/arch/Packages/...)."""
        return build_rpm_packages_url_for_arch(
            base_url=str(self.config["base_url"]),
            namespace=self.namespace if isinstance(self.namespace, str) else "",
            arch=arch,
            relative_path=relative_path,
            labels=labels,
            target_arch_repo_build_scoped=target_arch_repo_build_scoped,
        )

    def _build_rpm_distribution_url(
        self,
        relative_path: str,
        distribution_urls: dict[str, str],
        labels: dict[str, str] | None = None,
        *,
        target_arch_repo: bool = False,
        target_arch_repo_build_scoped: bool = False,
    ) -> str:
        """Build distribution URL for RPM artifacts (Packages/<lowercase-first-of-basename>/<basename>)."""
        return build_rpm_distribution_url(
            base_url=str(self.config["base_url"]),
            namespace=self.namespace if isinstance(self.namespace, str) else "",
            relative_path=relative_path,
            distribution_urls=distribution_urls,
            labels=labels,
            target_arch_repo=target_arch_repo,
            target_arch_repo_build_scoped=target_arch_repo_build_scoped,
        )

    @staticmethod
    def _build_file_distribution_url(
        relative_path: str, labels: dict[str, str], distribution_urls: dict[str, str]
    ) -> str:
        """Build distribution URL for file artifacts (logs, SBOM, etc.)."""
        # Check if relative_path contains arch prefix
        parts = relative_path.split("/", 1)
        if len(parts) == 2:
            arch, _ = parts
            if arch in SUPPORTED_ARCHITECTURES:
                logs_url = distribution_urls.get("logs", "")
                if logs_url:
                    return f"{logs_url}{relative_path}"

        # No arch prefix - determine type from filename
        filename_lower = relative_path.lower()
        if "sbom" in filename_lower:
            sbom_url = distribution_urls.get("sbom", "")
            if sbom_url:
                return f"{sbom_url}{relative_path}"
        else:
            # Likely a log file
            logs_url = distribution_urls.get("logs", "")
            if logs_url:
                arch = labels.get("arch", "")
                if arch:
                    return f"{logs_url}{arch}/{relative_path}"
                return f"{logs_url}{relative_path}"

        return relative_path

    def _build_artifact_distribution_url(
        self,
        relative_path: str,
        is_rpm: bool,
        labels: dict[str, str],
        distribution_urls: dict[str, str],
        *,
        target_arch_repo: bool = False,
        target_arch_repo_build_scoped: bool = False,
    ) -> str:
        """
        Build distribution URL for an artifact based on its type and relative path.

        Args:
            relative_path: Relative path of the artifact (e.g., filename or arch/filename)
            is_rpm: Whether this is an RPM artifact
            labels: Labels from content (may contain arch, etc.)
            distribution_urls: Dictionary mapping repo_type to distribution base URL
            target_arch_repo: When True, RPM URLs use per-arch paths from labels (or sanitized fallback)
            target_arch_repo_build_scoped: When True with target_arch_repo, use ``{build_id}/{arch}`` paths

        Returns:
            Full distribution URL for the artifact
        """
        if is_rpm:
            return self._build_rpm_distribution_url(
                relative_path,
                distribution_urls,
                labels=labels,
                target_arch_repo=target_arch_repo,
                target_arch_repo_build_scoped=target_arch_repo_build_scoped,
            )
        return self._build_file_distribution_url(relative_path, labels, distribution_urls)

    def find_content(self, search_type: str, search_value: str) -> httpx.Response:
        """
        Find content by various criteria.

        Args:
            search_type: Type of search ('build_id' or 'href')
            search_value: Value to search for

        Returns:
            Response object containing content matching the search criteria
        """
        if search_type == "build_id":
            url = self._url(f"api/v3/content/?pulp_label_select=build_id~{search_value}")
        elif search_type == "href":
            url = self._url(f"api/v3/content/?pulp_href__in={search_value}")
        else:
            raise ValueError(f"Unknown search type: {search_type}")

        response = self.session.get(url, timeout=self.timeout, **self.request_params)
        self._check_response(response, "find content")
        return response

    def get_file_locations(self, artifacts: list[dict[str, str]]) -> httpx.Response:
        """
        Get file locations for artifacts using the Pulp artifacts API.

        Args:
            artifacts: List of artifact dictionaries containing hrefs

        Returns:
            Response object containing file location information
        """
        hrefs = [list(artifact.values())[0] for artifact in artifacts]
        url = self._url("api/v3/artifacts/")
        params = {"pulp_href__in": ",".join(hrefs)}

        logging.debug("Querying %d artifacts from Pulp", len(hrefs))

        return self._chunked_get(
            url, params=params, chunk_param="pulp_href__in", timeout=self.timeout, chunk_size=20, **self.request_params
        )

    def _build_rpm_packages_url(self) -> str:
        """Build URL for RPM packages endpoint."""
        return self._url("api/v3/content/rpm/packages/")

    def get_rpm_by_pkgIDs(self, pkg_ids: list[str]) -> httpx.Response:
        """
        Get RPMs by package IDs.

        Args:
            pkg_ids: List of package IDs (checksums) to search for

        Returns:
            Response object containing RPM information for matching package IDs
        """
        url = self._build_rpm_packages_url()
        params = {"pkgId__in": ",".join(pkg_ids)}
        return self._chunked_get(
            url, params=params, chunk_param="pkgId__in", timeout=self.timeout, **self.request_params
        )

    async def async_get_rpm_by_pkgIDs(self, pkg_ids: list[str]) -> httpx.Response:
        """
        Get RPMs by package IDs asynchronously.

        Args:
            pkg_ids: List of package IDs (checksums) to search for

        Returns:
            Response object containing RPM information for matching package IDs
        """
        url = self._build_rpm_packages_url()
        params = {"pkgId__in": ",".join(pkg_ids)}
        return await self.async_get(url, params=params)

    def get_rpm_by_filenames(self, filenames: list[str]) -> httpx.Response:
        """
        Get RPMs by filename (e.g. package-1.0-1.el10.x86_64.rpm).

        Parses filenames to name+version+release (NVR) and searches Pulp by those
        fields instead of filename, for compatibility with instances that do not
        support filename filtering.

        Args:
            filenames: List of RPM filenames or paths to search for

        Returns:
            Response object containing RPM packages matching the NVRs
        """
        return self._run_async(self.async_get_rpm_by_filenames(filenames))

    async def async_get_rpm_by_filenames(self, filenames: list[str]) -> httpx.Response:
        """
        Get RPMs by filename asynchronously. Parses filenames to NVR and queries by name+version+release.
        """
        nvrs = self._filenames_to_nvrs(filenames)
        if not nvrs:
            return httpx.Response(
                200,
                content=json.dumps({"count": 0, "results": []}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )
        return await self.async_get_rpm_by_nvr([(n, v, r) for n, v, r in nvrs])

    def _filenames_to_nvrs(self, filenames: list[str]) -> list[tuple[str, str, str]]:
        """Parse filenames to NVRs, skipping unparseable with warning. Deduplicates."""
        seen: set[tuple[str, str, str]] = set()
        result: list[tuple[str, str, str]] = []
        for fname in filenames:
            nvr = parse_rpm_filename_to_nvr(fname)
            if nvr is None:
                logging.warning("Skipping unparseable RPM filename: %s", fname)
                continue
            if nvr not in seen:
                seen.add(nvr)
                result.append(nvr)
        return result

    async def async_get_rpm_by_nvr(self, nvrs: list[tuple[str, str, str]]) -> httpx.Response:
        """
        Get RPMs by name+version+release. Single NVR uses simple params; multiple use q expression.
        """
        url = self._build_rpm_packages_url()
        if not nvrs:
            return httpx.Response(
                200,
                content=json.dumps({"count": 0, "results": []}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        if len(nvrs) == 1:
            n, v, r = nvrs[0]
            params = {"name": n, "version": v, "release": r}
            return await self.async_get(url, params=params)

        # Multiple NVRs: q=(name="a" AND version="1" AND release="2") OR ...
        # Use chunk_size=1 to stay under Pulp expression complexity limit (packages.redhat.com)
        chunk_size = 1
        chunks = [nvrs[i : i + chunk_size] for i in range(0, len(nvrs), chunk_size)]

        async def fetch_chunk(chunk: list[tuple[str, str, str]]) -> list:
            nvr_parts = [f'(name="{n}" AND version="{v}" AND release="{r}")' for n, v, r in chunk]
            q_expr = " OR ".join(nvr_parts)
            params = {"q": q_expr}
            response = await self._get_async_session().get(
                url, params=params, timeout=self.timeout, **self.request_params
            )
            self._check_response(response, "get RPM by NVR")
            return response.json().get("results", [])

        tasks = [fetch_chunk(chunk) for chunk in chunks]
        raw: list[Any] = []
        for chunk_results in await asyncio.gather(*tasks):
            raw.extend(chunk_results)
        all_results = dedupe_results_by_pulp_href(raw)

        aggregated = {"count": len(all_results), "results": all_results}
        return httpx.Response(
            200,
            content=json.dumps(aggregated).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )

    def get_rpm_by_signed_by(self, signed_by_values: list[str]) -> httpx.Response:
        """
        Get RPMs by signed_by pulp label (pulp_labels.signed_by).

        Uses Pulp complex filtering: q='pulp_label_select="signed_by=X" OR ...'

        Args:
            signed_by_values: List of signed_by values to search for

        Returns:
            Response object containing RPM packages matching the signed_by values
        """
        return self._run_async(self.async_get_rpm_by_signed_by(signed_by_values))

    async def async_get_rpm_by_signed_by(self, signed_by_values: list[str]) -> httpx.Response:
        """
        Get RPMs by signed_by asynchronously.

        Args:
            signed_by_values: List of signed_by values to search for

        Returns:
            Response object containing RPM packages
        """
        url = self._build_rpm_packages_url()
        if not signed_by_values:
            return httpx.Response(
                200,
                content=json.dumps({"count": 0, "results": []}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        normalized_signed = _normalize_signed_by_query_values(signed_by_values)
        if not normalized_signed:
            return httpx.Response(
                200,
                content=json.dumps({"count": 0, "results": []}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        if _signed_by_values_require_client_label_filter(normalized_signed):
            return await self._async_get_rpm_by_signed_by_paginate_filter_labels(normalized_signed)

        # Pulp limits q expression complexity to 8. (A OR B OR C OR D) = 7.
        chunk_size = 4
        chunks = [normalized_signed[i : i + chunk_size] for i in range(0, len(normalized_signed), chunk_size)]

        if len(chunks) == 1:
            q_parts = [f'pulp_label_select="signed_by={v}"' for v in chunks[0]]
            q_expr = " OR ".join(q_parts)
            params = {"q": q_expr}
            return await self.async_get(url, params=params)

        async def fetch_chunk(chunk: list[str]) -> list:
            q_parts = [f'pulp_label_select="signed_by={v}"' for v in chunk]
            q_expr = " OR ".join(q_parts)
            params = {"q": q_expr}
            response = await self._get_async_session().get(
                url, params=params, timeout=self.timeout, **self.request_params
            )
            self._check_response(response, "get RPM by signed_by")
            return response.json().get("results", [])

        tasks = [fetch_chunk(chunk) for chunk in chunks]
        raw: list[Any] = []
        for chunk_results in await asyncio.gather(*tasks):
            raw.extend(chunk_results)
        all_results = dedupe_results_by_pulp_href(raw)

        aggregated = {"count": len(all_results), "results": all_results}
        return httpx.Response(
            200,
            content=json.dumps(aggregated).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )

    async def _async_get_rpm_by_signed_by_paginate_filter_labels(self, signed_by_values: list[str]) -> httpx.Response:
        """
        List RPM packages with pagination (no ``pulp_label_select``), filter by exact signed_by labels.

        Used when values contain commas (Pulp LabelFilter splits on comma).
        """
        url = self._build_rpm_packages_url()
        params: dict[str, str | int] = {"limit": 100}
        all_matching: list[Any] = []
        next_url: str | None = None

        while True:
            req_url = next_url if next_url else url
            req_params: dict[str, str | int] | None = None if next_url else params
            response = await self._get_async_session().get(
                req_url,
                params=req_params,
                timeout=self.timeout,
                **self.request_params,
            )
            self._check_response(response, "get RPM by signed_by (paginated label filter)")
            data = response.json()
            page = data.get("results", [])
            all_matching.extend(_filter_rpm_results_by_signed_by_labels(page, signed_by_values))
            next_url = data.get("next")
            if not next_url:
                break

        filtered = dedupe_results_by_pulp_href(all_matching)
        return httpx.Response(
            200,
            content=json.dumps({"count": len(filtered), "results": filtered}).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )

    def get_rpm_by_checksums_and_signed_by(self, checksums: list[str], signed_by: str) -> httpx.Response:
        """
        Get RPMs by checksums AND signed_by in a single query (server-side filter).

        Uses q=(pkgId="x" OR pkgId="y") AND pulp_label_select="signed_by=key"
        """
        return self._run_async(self.async_get_rpm_by_checksums_and_signed_by(checksums, signed_by))

    async def async_get_rpm_by_checksums_and_signed_by(self, checksums: list[str], signed_by: str) -> httpx.Response:
        """Get RPMs by checksums and signed_by in a single query."""
        url = self._build_rpm_packages_url()
        if not checksums:
            return httpx.Response(
                200,
                content=json.dumps({"count": 0, "results": []}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        signed_by_q = _normalize_signed_by_query_string(signed_by)

        if _signed_by_values_require_client_label_filter([signed_by_q]):
            params = {"pkgId__in": ",".join(checksums)}
            response = await self._chunked_get_async(
                url,
                params=params,
                chunk_param="pkgId__in",
                chunk_size=DEFAULT_CHUNK_SIZE,
                timeout=self.timeout,
                **self.request_params,
            )
            self._check_response(response, "get RPM by checksums (signed_by client label filter)")
            pkg_rows = response.json().get("results", [])
            filtered = _filter_rpm_results_by_signed_by_labels(pkg_rows, [signed_by_q])
            all_results = dedupe_results_by_pulp_href(filtered)
            return httpx.Response(
                200,
                content=json.dumps({"count": len(all_results), "results": all_results}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        # Pulp limits q expression complexity to 8. (A OR B OR C) AND pulp_label_select = 7.
        chunk_size = 3
        chunks = [checksums[i : i + chunk_size] for i in range(0, len(checksums), chunk_size)]
        signed_by_filter = f'pulp_label_select="signed_by={signed_by_q}"'

        if len(chunks) == 1:
            pkg_parts = [f'pkgId="{c}"' for c in chunks[0]]
            identity_expr = " OR ".join(pkg_parts)
            q_expr = f"({identity_expr}) AND {signed_by_filter}"
            params = {"q": q_expr}
            return await self.async_get(url, params=params)

        async def fetch_chunk(chunk: list[str]) -> list:
            pkg_parts = [f'pkgId="{c}"' for c in chunk]
            identity_expr = " OR ".join(pkg_parts)
            q_expr = f"({identity_expr}) AND {signed_by_filter}"
            params = {"q": q_expr}
            response = await self._get_async_session().get(
                url, params=params, timeout=self.timeout, **self.request_params
            )
            self._check_response(response, "get RPM by checksums and signed_by")
            return response.json().get("results", [])

        tasks = [fetch_chunk(chunk) for chunk in chunks]
        raw: list[Any] = []
        for chunk_results in await asyncio.gather(*tasks):
            raw.extend(chunk_results)
        all_results = dedupe_results_by_pulp_href(raw)
        aggregated = {"count": len(all_results), "results": all_results}
        return httpx.Response(
            200,
            content=json.dumps(aggregated).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )

    def get_rpm_by_filenames_and_signed_by(self, filenames: list[str], signed_by: str) -> httpx.Response:
        """
        Get RPMs by filenames AND signed_by. Parses filenames to NVR and queries by name+version+release.
        """
        return self._run_async(self.async_get_rpm_by_filenames_and_signed_by(filenames, signed_by))

    async def async_get_rpm_by_filenames_and_signed_by(self, filenames: list[str], signed_by: str) -> httpx.Response:
        """Get RPMs by filenames and signed_by. Parses to NVR, then tries combined query; falls back on 400/500."""
        nvrs = self._filenames_to_nvrs(filenames)
        if not nvrs:
            return httpx.Response(
                200,
                content=json.dumps({"count": 0, "results": []}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        nvr_list = [(n, v, r) for n, v, r in nvrs]
        signed_by_q = _normalize_signed_by_query_string(signed_by)
        if _signed_by_values_require_client_label_filter([signed_by_q]):
            resp = await self.async_get_rpm_by_nvr(nvr_list)
            self._check_response(resp, "get RPM by NVR (signed_by client label filter)")
            filtered = _filter_rpm_results_by_signed_by_labels(resp.json().get("results", []), [signed_by_q])
            deduped = dedupe_results_by_pulp_href(filtered)
            return httpx.Response(
                200,
                content=json.dumps({"count": len(deduped), "results": deduped}).encode("utf-8"),
                request=EMPTY_RESPONSE_REQUEST,
            )

        try:
            response = await self._fetch_rpm_by_nvr_and_signed_by_combined(nvr_list, signed_by_q)
            if response.status_code in (400, 500):
                raise httpx.HTTPStatusError(
                    f"Combined query returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return response
        except (httpx.HTTPStatusError, httpx.HTTPError, ValueError):
            return await self._fetch_rpm_by_nvr_and_signed_by_fallback(nvr_list, signed_by_q)

    async def _fetch_rpm_by_nvr_and_signed_by_combined(
        self, nvrs: list[tuple[str, str, str]], signed_by: str
    ) -> httpx.Response:
        """Single-query path: q=(name+version+release) OR ... AND pulp_label_select="signed_by=key"."""
        url = self._build_rpm_packages_url()
        # Use chunk_size=1 to stay under Pulp expression complexity limit (packages.redhat.com)
        chunk_size = 1
        chunks = [nvrs[i : i + chunk_size] for i in range(0, len(nvrs), chunk_size)]
        signed_by_filter = f'pulp_label_select="signed_by={signed_by}"'

        if len(nvrs) == 1:
            n, v, r = nvrs[0]
            params = {"name": n, "version": v, "release": r, "q": signed_by_filter}
            return await self.async_get(url, params=params)

        async def fetch_chunk(chunk: list[tuple[str, str, str]]) -> list:
            nvr_parts = [f'(name="{n}" AND version="{v}" AND release="{r}")' for n, v, r in chunk]
            identity_expr = " OR ".join(nvr_parts)
            q_expr = f"({identity_expr}) AND {signed_by_filter}"
            params = {"q": q_expr}
            response = await self._get_async_session().get(
                url, params=params, timeout=self.timeout, **self.request_params
            )
            if response.status_code in (400, 500):
                raise httpx.HTTPStatusError(
                    f"Combined query returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            self._check_response(response, "get RPM by NVR and signed_by")
            return response.json().get("results", [])

        tasks = [fetch_chunk(chunk) for chunk in chunks]
        raw: list[Any] = []
        for chunk_results in await asyncio.gather(*tasks):
            raw.extend(chunk_results)
        all_results = dedupe_results_by_pulp_href(raw)
        aggregated = {"count": len(all_results), "results": all_results}
        return httpx.Response(
            200,
            content=json.dumps(aggregated).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )

    async def _fetch_rpm_by_nvr_and_signed_by_fallback(
        self, nvrs: list[tuple[str, str, str]], signed_by: str
    ) -> httpx.Response:
        """Fallback: when NVRs >= 5, get by signed_by first and filter by NVR (1 call vs N+1).
        Otherwise get by NVR, get by signed_by, intersect by pulp_href."""
        if len(nvrs) >= 5:
            return await self._fetch_rpm_by_signed_by_then_filter_nvr(nvrs, signed_by)
        by_nvr_resp = await self.async_get_rpm_by_nvr(nvrs)
        self._check_response(by_nvr_resp, "get RPM by NVR (fallback)")
        by_signed_resp = await self.async_get_rpm_by_signed_by([signed_by])
        self._check_response(by_signed_resp, "get RPM by signed_by (fallback)")

        by_hrefs = {r["pulp_href"]: r for r in by_nvr_resp.json().get("results", [])}
        by_signed_hrefs = {r["pulp_href"] for r in by_signed_resp.json().get("results", [])}
        intersected = [by_hrefs[href] for href in by_signed_hrefs if href in by_hrefs]
        return httpx.Response(
            200,
            content=json.dumps({"count": len(intersected), "results": intersected}).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )

    async def _fetch_rpm_by_signed_by_then_filter_nvr(
        self, nvrs: list[tuple[str, str, str]], signed_by: str
    ) -> httpx.Response:
        """Fetch all packages by signed_by (paginated), filter by NVR locally. Reduces N+1 to 1 call."""
        url = self._build_rpm_packages_url()
        nvr_set = set(nvrs)
        params: dict[str, str | int] = {"q": f'pulp_label_select="signed_by={signed_by}"', "limit": 100}
        all_results: list[Any] = []
        next_url: str | None = None

        while True:
            req_url = next_url if next_url else url
            req_params: dict[str, str | int] | None = None if next_url else params
            response = await self._get_async_session().get(
                req_url,
                params=req_params,
                timeout=self.timeout,
                **self.request_params,
            )
            self._check_response(response, "get RPM by signed_by (paginated)")
            data = response.json()
            results = data.get("results", [])
            for r in results:
                nvr = (r.get("name"), r.get("version"), r.get("release"))
                if nvr in nvr_set:
                    all_results.append(r)
            next_url = data.get("next")
            if not next_url:
                break

        filtered = dedupe_results_by_pulp_href(all_results)
        return httpx.Response(
            200,
            content=json.dumps({"count": len(filtered), "results": filtered}).encode("utf-8"),
            request=EMPTY_RESPONSE_REQUEST,
        )
