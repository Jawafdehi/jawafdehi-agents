from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.models import CaseInitialization, SourceBundle

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def gather_sources_agent(initialization: CaseInitialization) -> SourceBundle:
    logger.debug("Starting source gathering for %s", initialization.case_number)
    source_bundle = await get_dependencies().source_gatherer.gather_sources(
        initialization
    )
    for path in source_bundle.raw_sources + source_bundle.markdown_sources:
        ensure_within_workspace(source_bundle.workspace.root_dir, path)
    logger.debug(
        "Source gathering produced %s raw and %s markdown sources for %s",
        len(source_bundle.raw_sources),
        len(source_bundle.markdown_sources),
        source_bundle.case_number,
    )
    return source_bundle
