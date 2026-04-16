from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.models import CaseInitialization, SourceBundle

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def retrieve_press_release_agent(
    initialization: CaseInitialization,
    source_bundle: SourceBundle,
) -> SourceBundle:
    logger.info("[%s] gather_sources.retrieve_press_release: starting", initialization.case_number)
    updated_bundle = await get_dependencies().source_gatherer.gather_press_release(
        initialization,
        source_bundle,
    )
    if updated_bundle.press_release_artifact is None:
        raise RuntimeError(
            f"Press release retrieval did not produce an artifact for {initialization.case_number}"
        )
    artifact = updated_bundle.press_release_artifact
    ensure_within_workspace(updated_bundle.workspace.root_dir, artifact.raw_path)
    ensure_within_workspace(updated_bundle.workspace.root_dir, artifact.markdown_path)
    logger.info(
        "[%s] gather_sources.retrieve_press_release: saved raw=%s markdown=%s",
        initialization.case_number,
        artifact.raw_path,
        artifact.markdown_path,
    )
    return updated_bundle
