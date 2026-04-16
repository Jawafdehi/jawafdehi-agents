from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.dependencies import get_dependencies
from jawafdehi_agents.models import PublishedCaseResult, PublishInput

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task(retries=3)
async def publish_and_finalize_case_agent(
    publish_input: PublishInput,
) -> PublishedCaseResult:
    logger.info("[%s] publish_and_finalize: starting API publication", publish_input.case_number)
    result = await get_dependencies().publish_finalizer.publish_and_finalize(
        publish_input
    )
    logger.info(
        "[%s] publish_and_finalize: API returned case_id=%s",
        publish_input.case_number,
        result.case_id,
    )
    return result
