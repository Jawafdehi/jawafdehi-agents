from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

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
    SourceArtifact,
    SourceBundle,
    WorkspaceContext,
)
from jawafdehi_agents.workflows.core.ciaa_caseworker.tasks import (
    draft_and_refine_case_agent,
    gather_news_agent,
    gather_sources_agent,
    initialize_casework,
)
from jawafdehi_agents.workflows.core.ciaa_caseworker.workflow import (
    ciaa_caseworker_workflow,
)


class FakeNGMClient:
    async def fetch_case_details(self, case_number: str) -> str:
        return f"# Case Details\n\n- **Pradip Pariyar**\n\n{case_number}"


class FakeSourceGatherer:
    async def gather_sources(self, initialization: CaseInitialization) -> SourceBundle:
        raw_path = initialization.workspace.sources_raw_dir / "special-court-case-details.txt"
        markdown_path = (
            initialization.workspace.sources_markdown_dir / "special-court-case-details.md"
        )
        raw_path.write_text("raw case details", encoding="utf-8")
        markdown_path.write_text("markdown case details", encoding="utf-8")
        return SourceBundle(
            case_number=initialization.case_number,
            workspace=initialization.workspace,
            asset_root=initialization.asset_root,
            case_details_path=initialization.case_details_path,
            raw_sources=[raw_path],
            markdown_sources=[markdown_path],
            case_details_artifact=SourceArtifact(
                source_type="case_details",
                title="Case details",
                raw_path=raw_path,
                markdown_path=markdown_path,
            ),
        )

    async def gather_press_release(
        self, initialization: CaseInitialization, source_bundle: SourceBundle
    ) -> SourceBundle:
        raw_path = initialization.workspace.sources_raw_dir / "press-release.html"
        markdown_path = initialization.workspace.sources_markdown_dir / "press-release.md"
        raw_path.write_text("<html>press raw</html>", encoding="utf-8")
        markdown_path.write_text("# Press Release\n\npress markdown", encoding="utf-8")
        artifact = SourceArtifact(
            source_type="press_release",
            title="CIAA Press Release",
            raw_path=raw_path,
            markdown_path=markdown_path,
            source_url="https://ciaa.gov.np/pressrelease/example",
        )
        return source_bundle.model_copy(
            update={
                "raw_sources": [*source_bundle.raw_sources, raw_path],
                "markdown_sources": [*source_bundle.markdown_sources, markdown_path],
                "press_release_artifact": artifact,
            }
        )

    async def gather_charge_sheet(
        self, initialization: CaseInitialization, source_bundle: SourceBundle
    ) -> SourceBundle:
        assert source_bundle.press_release_artifact is not None
        raw_path = initialization.workspace.sources_raw_dir / "charge-sheet.pdf"
        markdown_path = initialization.workspace.sources_markdown_dir / "charge-sheet.md"
        raw_path.write_text("charge raw", encoding="utf-8")
        markdown_path.write_text("# Charge Sheet\n\ncharge markdown", encoding="utf-8")
        artifact = SourceArtifact(
            source_type="charge_sheet",
            title="Charge Sheet",
            raw_path=raw_path,
            markdown_path=markdown_path,
            source_url="https://ag.gov.np/charge-sheet.pdf",
        )
        return source_bundle.model_copy(
            update={
                "raw_sources": [*source_bundle.raw_sources, raw_path],
                "markdown_sources": [*source_bundle.markdown_sources, markdown_path],
                "charge_sheet_artifact": artifact,
            }
        )

    async def gather_news_sources(
        self, initialization: CaseInitialization, source_bundle: SourceBundle
    ) -> SourceBundle:
        return source_bundle


class FakeNewsGatherer:
    async def gather_news(self, source_bundle: SourceBundle) -> SourceBundle:
        raw_path = source_bundle.workspace.sources_raw_dir / "news-01.html"
        markdown_path = source_bundle.workspace.sources_markdown_dir / "news-01.md"
        raw_path.write_text("<html>news raw</html>", encoding="utf-8")
        markdown_path.write_text("# News\n\nnews markdown", encoding="utf-8")
        artifact = SourceArtifact(
            source_type="news",
            title="News Coverage",
            raw_path=raw_path,
            markdown_path=markdown_path,
            source_url="https://example.com/news",
            external_url="https://example.com/news",
        )
        return source_bundle.model_copy(
            update={
                "raw_sources": [*source_bundle.raw_sources, raw_path],
                "markdown_sources": [*source_bundle.markdown_sources, markdown_path],
                "news_artifacts": [*source_bundle.news_artifacts, artifact],
            }
        )


class SequenceDraftRefinementAgent:
    def __init__(self, critiques: list[Critique], *, draft_text: str | None = None) -> None:
        self.critiques = critiques
        self.revisions = 0
        self.generate_calls = 0
        self.draft_text = draft_text or (
            "# Jawafdehi Case Draft\n\n"
            "## Title\nनमुना मुद्दा\n\n"
            "## Short Description\nछोटो विवरण\n\n"
            "## Key Allegations\n- आरोप १\n- आरोप २\n\n"
            "## Timeline\n- 2082-01-01: दर्ता\n\n"
            "## Description\n"
            + ("विस्तृत विवरण।" * 60)
            + "\n\n## Missing Details\nथप पुष्टिकरण आवश्यक।\n"
        )

    async def generate_draft(self, draft_input: DraftInput) -> str:
        self.generate_calls += 1
        return self.draft_text

    async def critique_content(self, draft: str, draft_input: DraftInput) -> Critique:
        return self.critiques.pop(0)

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str:
        self.revisions += 1
        return self.draft_text


class FakePublishFinalizer:
    def __init__(self) -> None:
        self.calls = 0

    async def publish_and_finalize(
        self, publish_input: PublishInput
    ) -> PublishedCaseResult:
        self.calls += 1
        return PublishedCaseResult(case_id=7, entity_ids=[100], source_ids=["s1"])


def _build_workspace(case_number: str) -> WorkspaceContext:
    root_dir = Path(tempfile.mkdtemp(prefix=f"jawaf-test-{case_number}-"))
    logs_dir = root_dir / "logs"
    sources_raw_dir = root_dir / "sources" / "raw"
    sources_markdown_dir = root_dir / "sources" / "markdown"
    logs_dir.mkdir(parents=True, exist_ok=True)
    sources_raw_dir.mkdir(parents=True, exist_ok=True)
    sources_markdown_dir.mkdir(parents=True, exist_ok=True)
    return WorkspaceContext(
        root_dir=root_dir,
        logs_dir=logs_dir,
        sources_raw_dir=sources_raw_dir,
        sources_markdown_dir=sources_markdown_dir,
    )


def test_draft_and_refine_accepts_after_revision():
    critiques = [
        Critique(
            score=7,
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
                CIAACaseInput(case_number="081-CR-0046"),
                workspace=_build_workspace("081-CR-0046"),
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
                await ciaa_caseworker_workflow(
                    CIAACaseInput(case_number="081-CR-0046"),
                    workspace=_build_workspace("081-CR-0046"),
                )
        assert publisher.calls == 0

    asyncio.run(run_test())


def test_draft_and_refine_exhausts_iterations():
    critiques = [
        Critique(
            score=6,
            outcome=ReviewOutcome.needs_revision,
            strengths=[],
            improvements=["More sources"],
        ),
        Critique(
            score=7,
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
            CIAACaseInput(case_number="081-CR-0046"),
            workspace=_build_workspace("081-CR-0046"),
        )
        source_bundle = await gather_sources_agent(initialization)
        source_bundle = await gather_news_agent(source_bundle)
        assert source_bundle.press_release_artifact is not None
        assert source_bundle.charge_sheet_artifact is not None
        assert len(source_bundle.news_artifacts) == 1
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
