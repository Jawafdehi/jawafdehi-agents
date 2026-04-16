from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.models import CaseInitialization, SourceBundle

from .retrieve_charge_sheet import retrieve_charge_sheet_agent
from .retrieve_news_sources import retrieve_news_sources_agent
from .retrieve_press_release import retrieve_press_release_agent

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def gather_sources_agent(initialization: CaseInitialization) -> SourceBundle:
    logger.info("[%s] gather_sources: building source bundle", initialization.case_number)
    source_bundle = await get_dependencies().source_gatherer.gather_sources(
        initialization
    )
    source_bundle = await retrieve_press_release_agent(initialization, source_bundle)
    source_bundle = await retrieve_charge_sheet_agent(initialization, source_bundle)
    source_bundle = await retrieve_news_sources_agent(initialization, source_bundle)
    for path in source_bundle.raw_sources + source_bundle.markdown_sources:
        ensure_within_workspace(source_bundle.workspace.root_dir, path)
    logger.info(
        "[%s] gather_sources: produced %s raw and %s markdown sources",
        source_bundle.case_number,
        len(source_bundle.raw_sources),
        len(source_bundle.markdown_sources),
    )
    return source_bundle
