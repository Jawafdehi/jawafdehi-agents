from __future__ import annotations

import asyncio

import pytest

from jawafdehi_agents.dependencies import WorkflowDependencies, use_dependencies
from jawafdehi_agents.models import (
    CaseInitialization,
    CIAACaseInput,
    Critique,
    DraftInput,
    PublishedCaseResult,
    PublishInput,
    ReviewOutcome,
    SourceBundle,
)
from jawafdehi_agents.workflows.ciaa_caseworker.draft_and_refine_case_agent import (
    draft_and_refine_case_agent,
)
from jawafdehi_agents.workflows.ciaa_caseworker.gather_news_agent import (
    gather_news_agent,
)
from jawafdehi_agents.workflows.ciaa_caseworker.gather_sources_agent import (
    gather_sources_agent,
)
from jawafdehi_agents.workflows.ciaa_caseworker.initialize_casework import (
    initialize_casework,
)
from jawafdehi_agents.workflows.ciaa_caseworker.workflow import (
    ciaa_caseworker_workflow,
)


class FakeNGMClient:
    async def fetch_case_details(self, case_number: str) -> str:
        return f"# Case Details\n\n{case_number}"


class FakeSourceGatherer:
    async def gather_sources(self, initialization: CaseInitialization) -> SourceBundle:
        raw_path = initialization.workspace.sources_raw_dir / "charge-sheet.pdf"
        markdown_path = (
            initialization.workspace.sources_markdown_dir / "charge-sheet.md"
        )
        raw_path.write_text("raw", encoding="utf-8")
        markdown_path.write_text("markdown", encoding="utf-8")
        return SourceBundle(
            case_number=initialization.case_number,
            workspace=initialization.workspace,
            asset_root=initialization.asset_root,
            case_details_path=initialization.case_details_path,
            raw_sources=[raw_path],
            markdown_sources=[markdown_path],
        )


class FakeNewsGatherer:
    async def gather_news(self, source_bundle: SourceBundle) -> SourceBundle:
        news_path = source_bundle.workspace.sources_markdown_dir / "news.md"
        news_path.write_text("news", encoding="utf-8")
        return source_bundle.model_copy(
            update={
                "markdown_sources": [*source_bundle.markdown_sources, news_path],
            }
        )


class SequenceDraftRefinementAgent:
    def __init__(self, critiques: list[Critique]) -> None:
        self.critiques = critiques
        self.revisions = 0
        self.generate_calls = 0

    async def generate_draft(self, draft_input: DraftInput) -> str:
        self.generate_calls += 1
        return "# Draft"

    async def critique_content(self, draft: str, draft_input: DraftInput) -> Critique:
        return self.critiques.pop(0)

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str:
        self.revisions += 1
        return draft + "\n\nrevised"


class FakePublishFinalizer:
    def __init__(self) -> None:
        self.calls = 0

    async def publish_and_finalize(
        self, publish_input: PublishInput
    ) -> PublishedCaseResult:
        self.calls += 1
        return PublishedCaseResult(case_id=7, entity_ids=[100], source_ids=["s1"])


def test_draft_and_refine_accepts_after_revision():
    critiques = [
        Critique(
            score=6,
            outcome=ReviewOutcome.needs_revision,
            strengths=[],
            improvements=["Needs more detail"],
        ),
        Critique(
            score=9,
            outcome=ReviewOutcome.approved,
            strengths=["Good now"],
            improvements=[],
        ),
    ]
    draft_agent = SequenceDraftRefinementAgent(critiques=critiques)
    publisher = FakePublishFinalizer()
    dependencies = WorkflowDependencies(
        ngm_client=FakeNGMClient(),
        source_gatherer=FakeSourceGatherer(),
        news_gatherer=FakeNewsGatherer(),
        draft_refinement_agent=draft_agent,
        publish_finalizer=publisher,
    )

    async def run_test():
        with use_dependencies(dependencies):
            result = await ciaa_caseworker_workflow(
                CIAACaseInput(case_number="081-CR-0046")
            )
        assert result.published is True
        assert result.case_id == 7
        assert result.final_outcome == ReviewOutcome.approved
        assert draft_agent.revisions == 1
        assert publisher.calls == 1

    asyncio.run(run_test())


def test_draft_and_refine_blocks_publication():
    critiques = [
        Critique(
            score=2,
            outcome=ReviewOutcome.blocked,
            strengths=[],
            improvements=[],
            blockers=["Unsupported allegation"],
        )
    ]
    draft_agent = SequenceDraftRefinementAgent(critiques=critiques)
    publisher = FakePublishFinalizer()
    dependencies = WorkflowDependencies(
        ngm_client=FakeNGMClient(),
        source_gatherer=FakeSourceGatherer(),
        news_gatherer=FakeNewsGatherer(),
        draft_refinement_agent=draft_agent,
        publish_finalizer=publisher,
    )

    async def run_test():
        with use_dependencies(dependencies):
            with pytest.raises(RuntimeError, match="Draft review was blocked"):
                await ciaa_caseworker_workflow(CIAACaseInput(case_number="081-CR-0046"))
        assert publisher.calls == 0

    asyncio.run(run_test())


def test_draft_and_refine_exhausts_iterations():
    critiques = [
        Critique(
            score=5,
            outcome=ReviewOutcome.needs_revision,
            strengths=[],
            improvements=["More sources"],
        ),
        Critique(
            score=6,
            outcome=ReviewOutcome.needs_revision,
            strengths=[],
            improvements=["Still incomplete"],
        ),
    ]
    draft_agent = SequenceDraftRefinementAgent(critiques=critiques)
    dependencies = WorkflowDependencies(
        ngm_client=FakeNGMClient(),
        source_gatherer=FakeSourceGatherer(),
        news_gatherer=FakeNewsGatherer(),
        draft_refinement_agent=draft_agent,
        publish_finalizer=FakePublishFinalizer(),
    )

    async def run_test():
        initialization = await initialize_casework(
            CIAACaseInput(case_number="081-CR-0046")
        )
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
        with pytest.raises(
            RuntimeError, match="Draft refinement exhausted maximum iterations"
        ):
            await draft_and_refine_case_agent(draft_input, max_iterations=2)

    async def wrapped():
        with use_dependencies(dependencies):
            await run_test()

    asyncio.run(wrapped())
