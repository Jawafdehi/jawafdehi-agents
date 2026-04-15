from __future__ import annotations

from jawafdehi_agents.flyte_compat import env
from jawafdehi_agents.models import (
    ACCEPTED_REVIEW_OUTCOMES,
    CIAACaseInput,
    DraftInput,
    PublishInput,
    WorkflowResult,
)
from workflows.ciaa_caseworker.draft_and_refine_case_agent import (
    draft_and_refine_case_agent,
)
from workflows.ciaa_caseworker.gather_news_agent import gather_news_agent
from workflows.ciaa_caseworker.gather_sources_agent import gather_sources_agent
from workflows.ciaa_caseworker.initialize_casework import initialize_casework
from workflows.ciaa_caseworker.publish_and_finalize_case_agent import (
    publish_and_finalize_case_agent,
)


@env.task
async def ciaa_caseworker_workflow(case_input: CIAACaseInput) -> WorkflowResult:
    initialization = await initialize_casework(case_input)
    source_bundle = await gather_sources_agent(initialization)
    source_bundle = await gather_news_agent(source_bundle)
    draft_input = DraftInput(
        case_number=source_bundle.case_number,
        workspace=source_bundle.workspace,
        asset_root=source_bundle.asset_root,
        case_details_path=source_bundle.case_details_path,
        raw_sources=source_bundle.raw_sources,
        markdown_sources=source_bundle.markdown_sources,
    )
    refinement_result = await draft_and_refine_case_agent(draft_input)

    if refinement_result.final_outcome not in ACCEPTED_REVIEW_OUTCOMES:
        return WorkflowResult(
            case_number=case_input.case_number,
            published=False,
            final_outcome=refinement_result.final_outcome,
        )

    published_case = await publish_and_finalize_case_agent(
        PublishInput(
            case_number=case_input.case_number,
            source_bundle=source_bundle,
            refinement_result=refinement_result,
        )
    )
    return WorkflowResult(
        case_number=case_input.case_number,
        published=True,
        case_id=published_case.case_id,
        final_outcome=refinement_result.final_outcome,
    )
