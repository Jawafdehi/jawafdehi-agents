from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.models import SourceBundle

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def gather_news_agent(source_bundle: SourceBundle) -> SourceBundle:
    logger.debug("Starting news gathering for %s", source_bundle.case_number)
    updated_bundle = await get_dependencies().news_gatherer.gather_news(source_bundle)
    for path in updated_bundle.raw_sources + updated_bundle.markdown_sources:
        ensure_within_workspace(updated_bundle.workspace.root_dir, path)
    logger.debug(
        "News gathering now has %s markdown sources for %s",
        len(updated_bundle.markdown_sources),
        updated_bundle.case_number,
    )
    return updated_bundle
