from __future__ import annotations

import asyncio

from jawafdehi_agents.dependencies import (
    WorkflowDependencies,
    build_default_dependencies,
    use_dependencies,
)
from jawafdehi_agents.models import CIAACaseInput, WorkflowResult
from workflows.ciaa_caseworker.workflow import ciaa_caseworker_workflow


class RunService:
    def __init__(self, dependencies: WorkflowDependencies | None = None) -> None:
        self.dependencies = dependencies or build_default_dependencies()

    def start_run(self, case_number: str) -> WorkflowResult:
        case_input = CIAACaseInput(case_number=case_number)
        with use_dependencies(self.dependencies):
            return asyncio.run(ciaa_caseworker_workflow(case_input))
