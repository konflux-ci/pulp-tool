"""Side-tag RPM promotion during pull transfer."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from ..api import PulpClient
from ..models.artifacts import ArtifactData, PulledArtifacts
from ..models.context import PullContext
from ..utils import PulpHelper, determine_build_id, extract_metadata_from_artifacts
from ..utils.error_handling import handle_generic_error
from ..utils.pulp_results_document import SideTagRpmTransfer, resolve_predecessor_href, side_tag_upload_labels
from ..utils.pulp_tasks import wait_for_successful_task
from ..utils.rpm_operations import calculate_sha256_checksum, upload_rpms_parallel


@dataclass(frozen=True, slots=True)
class SideTagUploadResult:
    """RPMs promoted to a side-tag repository and its distribution base URL."""

    transfers: list[SideTagRpmTransfer]
    distribution_base_url: str = ""


def upload_rpms_to_side_tag_repository(
    pulp_client: PulpClient,
    pulled_artifacts: PulledArtifacts,
    artifact_data: ArtifactData,
    context: PullContext,
) -> SideTagUploadResult:
    """
    Re-upload downloaded RPMs to the side-tag RPM repository with lineage labels.

    Mainline upload is unchanged; this runs only when ``context.side_tag`` is set.
    """
    side_tag = (context.side_tag or "").strip()
    if not side_tag or not pulled_artifacts.rpms:
        return SideTagUploadResult([], "")

    parent_package = extract_metadata_from_artifacts(pulled_artifacts, "parent_package")
    helper = PulpHelper(pulp_client, parent_package=parent_package)
    build_id = determine_build_id(context, pulled_artifacts=pulled_artifacts)  # type: ignore[arg-type]
    side_tag_repo_href, distribution_base_url = helper.ensure_side_tag_rpm_repository(build_id, side_tag)

    namespace = context.namespace or extract_metadata_from_artifacts(pulled_artifacts, "namespace")
    cluster = context.cluster

    rpm_infos: list[tuple[str, dict[str, str], str]] = []
    artifact_keys: list[str] = []
    source_artifacts = artifact_data.artifacts

    for artifact_key, artifact_file in pulled_artifacts.rpms.items():
        source_meta = source_artifacts.get(artifact_key)
        source_dict = source_meta.model_dump() if source_meta is not None else {"labels": artifact_file.labels}
        predecessor = resolve_predecessor_href(source_dict)
        labels = side_tag_upload_labels(
            dict(artifact_file.labels),
            side_tag=side_tag,
            source_pulp_href=predecessor,
            namespace=namespace,
            build_id=build_id,
            cluster=cluster,
        )
        rpm_infos.append((artifact_file.file, labels, artifact_file.arch or "noarch"))
        artifact_keys.append(artifact_key)

    logging.warning("Uploading %d RPM file(s) to side-tag repository '%s'", len(rpm_infos), side_tag)
    rpm_pairs, rpm_errors = upload_rpms_parallel(pulp_client, rpm_infos)
    if rpm_errors:
        for err in rpm_errors:
            logging.error("Side-tag RPM upload error: %s", err)

    rpm_hrefs = [href for _path, href in rpm_pairs]
    if rpm_hrefs:
        try:
            add_task = pulp_client.add_content(side_tag_repo_href, rpm_hrefs)
            wait_for_successful_task(pulp_client, add_task.pulp_href, "add RPMs to side-tag repository")
        except (httpx.HTTPError, ValueError, KeyError) as e:
            handle_generic_error(e, "add RPMs to side-tag repository")
            raise

    transfers: list[SideTagRpmTransfer] = []
    path_to_key = {info[0]: key for info, key in zip(rpm_infos, artifact_keys, strict=True)}
    distribution_urls = {"rpms": distribution_base_url.rstrip("/") + "/"}

    for rpm_path, pulp_href in rpm_pairs:
        key = path_to_key.get(rpm_path)
        if not key:
            continue
        sha256 = calculate_sha256_checksum(rpm_path)
        basename = os.path.basename(rpm_path)
        dist_url = pulp_client._build_artifact_distribution_url(  # pylint: disable=protected-access
            basename,
            True,
            dict(pulled_artifacts.rpms[key].labels),
            distribution_urls,
        )
        transfers.append(
            SideTagRpmTransfer(
                artifact_key=key,
                pulp_href=pulp_href,
                sha256=sha256,
                distribution_url=dist_url,
            )
        )

    return SideTagUploadResult(transfers, distribution_base_url)


__all__ = ["SideTagUploadResult", "upload_rpms_to_side_tag_repository"]
