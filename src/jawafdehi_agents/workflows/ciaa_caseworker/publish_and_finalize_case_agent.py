from __future__ import annotations

from jawafdehi_agents.dependencies import get_dependencies
from jawafdehi_agents.flyte_compat import env
from jawafdehi_agents.models import PublishedCaseResult, PublishInput


@env.task(retries=3)
async def publish_and_finalize_case_agent(
    publish_input: PublishInput,
) -> PublishedCaseResult:
    return await get_dependencies().publish_finalizer.publish_and_finalize(
        publish_input
    )
