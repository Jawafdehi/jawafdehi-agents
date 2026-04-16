from __future__ import annotations

import logging

import flyte

from jawafdehi_agents.assets import ciaa_workflow_root
from jawafdehi_agents.dependencies import get_dependencies
from jawafdehi_agents.models import CaseInitialization, CIAACaseInput, WorkspaceContext
from jawafdehi_agents.workflows.core.ciaa_caseworker.helpers import write_text

logger = logging.getLogger(__name__)

env = flyte.TaskEnvironment(name="jawafdehi_agents")


@env.task
async def initialize_casework(
    case_input: CIAACaseInput,
    workspace: WorkspaceContext,
) -> CaseInitialization:
    dependencies = get_dependencies()
    asset_root = ciaa_workflow_root()
    case_details_path = workspace.root_dir / f"special:{case_input.case_number}.md"

    logger.info("[%s] initialize_casework: fetching NGM case details", case_input.case_number)
    case_details = await dependencies.ngm_client.fetch_case_details(
        case_input.case_number
    )
    write_text(case_details_path, case_details)
    logger.info("[%s] initialize_casework: wrote case details to %s", case_input.case_number, case_details_path)

    return CaseInitialization(
        case_number=case_input.case_number,
        workspace=workspace,
        asset_root=asset_root,
        case_details_path=case_details_path,
    )
