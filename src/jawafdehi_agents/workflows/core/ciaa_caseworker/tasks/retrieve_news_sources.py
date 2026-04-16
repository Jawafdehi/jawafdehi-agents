from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.models import CaseInitialization, SourceBundle

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def retrieve_news_sources_agent(
    initialization: CaseInitialization,
    source_bundle: SourceBundle,
) -> SourceBundle:
    logger.debug("Retrieving news sources for %s", initialization.case_number)
    if source_bundle.press_release_artifact is None:
        raise RuntimeError("News retrieval requires a press release artifact first")
    if source_bundle.charge_sheet_artifact is None:
        raise RuntimeError("News retrieval requires a charge sheet artifact first")
    updated_bundle = await get_dependencies().source_gatherer.gather_news_sources(
        initialization,
        source_bundle,
    )
    for artifact in updated_bundle.news_artifacts:
        ensure_within_workspace(updated_bundle.workspace.root_dir, artifact.raw_path)
        ensure_within_workspace(updated_bundle.workspace.root_dir, artifact.markdown_path)
    return updated_bundle
