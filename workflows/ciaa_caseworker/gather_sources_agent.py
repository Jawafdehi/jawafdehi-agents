from __future__ import annotations

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.flyte_compat import env
from jawafdehi_agents.models import CaseInitialization, SourceBundle


@env.task
async def gather_sources_agent(initialization: CaseInitialization) -> SourceBundle:
    source_bundle = await get_dependencies().source_gatherer.gather_sources(
        initialization
    )
    for path in source_bundle.raw_sources + source_bundle.markdown_sources:
        ensure_within_workspace(source_bundle.workspace.root_dir, path)
    return source_bundle
