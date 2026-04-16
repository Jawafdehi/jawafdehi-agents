from __future__ import annotations

import asyncio
import logging

from jawafdehi_agents.dependencies import (
    WorkflowDependencies,
    build_default_dependencies,
    use_dependencies,
)
from jawafdehi_agents.logging_utils import configure_run_logging
from jawafdehi_agents.otel_utils import configure_console_tracing
from jawafdehi_agents.models import CIAACaseInput, WorkflowResult
from jawafdehi_agents.workflows.core.ciaa_caseworker.workflow import (
    ciaa_caseworker_workflow,
)
from jawafdehi_agents.workspace import create_workspace


class RunService:
    def __init__(self, dependencies: WorkflowDependencies | None = None) -> None:
        self.dependencies = dependencies or build_default_dependencies()

    def start_run(self, case_number: str) -> WorkflowResult:
        case_input = CIAACaseInput(case_number=case_number)
        workspace = create_workspace(case_input.case_number)
        log_path = configure_run_logging(workspace.logs_dir, case_input.case_number)
        configure_console_tracing()
        logger = logging.getLogger(__name__)
        logger.debug("Starting workflow run for %s", case_input.case_number)
        logger.debug("Run workspace initialized at %s", workspace.root_dir)
        logger.debug("Verbose log file configured at %s", log_path)
        with use_dependencies(self.dependencies):
            try:
                return asyncio.run(
                    ciaa_caseworker_workflow(case_input, workspace=workspace)
                )
            finally:
                logger.debug("Workflow run finished for %s", case_input.case_number)
