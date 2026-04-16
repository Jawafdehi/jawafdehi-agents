from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.models import (
    ACCEPTED_REVIEW_OUTCOMES,
    CIAACaseInput,
    DraftInput,
    PublishInput,
    WorkflowResult,
    WorkspaceContext,
)
from jawafdehi_agents.workflows.core.ciaa_caseworker.tasks import (
    draft_and_refine_case_agent,
    gather_news_agent,
    gather_sources_agent,
    initialize_casework,
    publish_and_finalize_case_agent,
)

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def ciaa_caseworker_workflow(
    case_input: CIAACaseInput,
    workspace: WorkspaceContext,
) -> WorkflowResult:
    logger.info("[%s] Workflow started", case_input.case_number)
    logger.info(
        "[%s] Step 1/5: initialize casework -> %s",
        case_input.case_number,
        workspace.root_dir,
    )
    initialization = await initialize_casework(case_input, workspace)
    logger.info(
        "[%s] Step 1/5 complete: case details prepared at %s",
        case_input.case_number,
        initialization.case_details_path,
    )

    logger.info("[%s] Step 2/5: gather sources", case_input.case_number)
    source_bundle = await gather_sources_agent(initialization)
    logger.info(
        "[%s] Step 2/5 complete: %s raw sources, %s markdown sources",
        case_input.case_number,
        len(source_bundle.raw_sources),
        len(source_bundle.markdown_sources),
    )

    logger.info("[%s] Step 3/5: gather news", case_input.case_number)
    source_bundle = await gather_news_agent(source_bundle)
    logger.info(
        "[%s] Step 3/5 complete: %s raw sources, %s markdown sources",
        case_input.case_number,
        len(source_bundle.raw_sources),
        len(source_bundle.markdown_sources),
    )

    logger.info("[%s] Step 4/5: draft and refine case", case_input.case_number)
    draft_input = DraftInput(
        case_number=source_bundle.case_number,
        workspace=source_bundle.workspace,
        asset_root=source_bundle.asset_root,
        case_details_path=source_bundle.case_details_path,
        raw_sources=source_bundle.raw_sources,
        markdown_sources=source_bundle.markdown_sources,
    )
    refinement_result = await draft_and_refine_case_agent(draft_input)
    logger.info(
        "[%s] Step 4/5 complete: outcome=%s score=%s iterations=%s draft=%s review=%s",
        case_input.case_number,
        refinement_result.final_outcome,
        refinement_result.final_score,
        len(refinement_result.iterations),
        refinement_result.draft_path,
        refinement_result.review_path,
    )

    if refinement_result.final_outcome not in ACCEPTED_REVIEW_OUTCOMES:
        logger.info(
            "[%s] Workflow stopping before publication because outcome %s is not publishable",
            case_input.case_number,
            refinement_result.final_outcome,
        )
        return WorkflowResult(
            case_number=case_input.case_number,
            published=False,
            final_outcome=refinement_result.final_outcome,
        )

    logger.info("[%s] Step 5/5: publish and finalize", case_input.case_number)
    published_case = await publish_and_finalize_case_agent(
        PublishInput(
            case_number=case_input.case_number,
            source_bundle=source_bundle,
            refinement_result=refinement_result,
        )
    )
    logger.info(
        "[%s] Step 5/5 complete: published case_id=%s updated_fields=%s entity_ids=%s source_ids=%s",
        case_input.case_number,
        published_case.case_id,
        published_case.updated_fields,
        published_case.entity_ids,
        published_case.source_ids,
    )
    return WorkflowResult(
        case_number=case_input.case_number,
        published=True,
        case_id=published_case.case_id,
        final_outcome=refinement_result.final_outcome,
    )
