from __future__ import annotations

from jawafdehi_agents.dependencies import ensure_within_workspace, get_dependencies
from jawafdehi_agents.flyte_compat import env
from jawafdehi_agents.models import SourceBundle


@env.task
async def gather_news_agent(source_bundle: SourceBundle) -> SourceBundle:
    updated_bundle = await get_dependencies().news_gatherer.gather_news(source_bundle)
    for path in updated_bundle.raw_sources + updated_bundle.markdown_sources:
        ensure_within_workspace(updated_bundle.workspace.root_dir, path)
    return updated_bundle
