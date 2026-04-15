from __future__ import annotations

from jawafdehi_agents.assets import ciaa_workflow_root
from jawafdehi_agents.dependencies import get_dependencies
from jawafdehi_agents.flyte_compat import env
from jawafdehi_agents.models import CaseInitialization, CIAACaseInput
from jawafdehi_agents.workflows.ciaa_caseworker.helpers import write_text
from jawafdehi_agents.workspace import create_workspace


@env.task
async def initialize_casework(case_input: CIAACaseInput) -> CaseInitialization:
    dependencies = get_dependencies()
    workspace = create_workspace(case_input.case_number)
    asset_root = ciaa_workflow_root()
    case_details_path = workspace.root_dir / f"case_details-{case_input.case_number}.md"
    summary_log_path = workspace.logs_dir / "case-summary.md"

    case_details = await dependencies.ngm_client.fetch_case_details(
        case_input.case_number
    )
    write_text(case_details_path, case_details)
    write_text(summary_log_path, f"# Case Summary\n\n{case_input.case_number}\n")

    return CaseInitialization(
        case_number=case_input.case_number,
        workspace=workspace,
        asset_root=asset_root,
        case_details_path=case_details_path,
        summary_log_path=summary_log_path,
    )
