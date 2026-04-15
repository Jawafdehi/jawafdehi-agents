from __future__ import annotations

from typer.testing import CliRunner

from jawafdehi_agents.cli import app
from jawafdehi_agents.dependencies import WorkflowDependencies
from jawafdehi_agents.models import (
    CaseInitialization,
    Critique,
    DraftInput,
    PublishedCaseResult,
    PublishInput,
    ReviewOutcome,
    SourceBundle,
)
from jawafdehi_agents.run_service import RunService


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
        news_path = source_bundle.workspace.sources_markdown_dir / "news-example.md"
        news_path.write_text("news", encoding="utf-8")
        return source_bundle.model_copy(
            update={
                "markdown_sources": [*source_bundle.markdown_sources, news_path],
            }
        )


class FakeDraftRefinementAgent:
    async def generate_draft(self, draft_input: DraftInput) -> str:
        return "# Draft"

    async def critique_content(self, draft: str, draft_input: DraftInput) -> Critique:
        return Critique(
            score=9,
            outcome=ReviewOutcome.approved,
            strengths=["Strong sourcing"],
            improvements=[],
            blockers=[],
        )

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str:
        return draft + "\n\nrevised"


class FakePublishFinalizer:
    async def publish_and_finalize(
        self, publish_input: PublishInput
    ) -> PublishedCaseResult:
        return PublishedCaseResult(case_id=42, entity_ids=[1], source_ids=["src-1"])


def build_dependencies() -> WorkflowDependencies:
    return WorkflowDependencies(
        ngm_client=FakeNGMClient(),
        source_gatherer=FakeSourceGatherer(),
        news_gatherer=FakeNewsGatherer(),
        draft_refinement_agent=FakeDraftRefinementAgent(),
        publish_finalizer=FakePublishFinalizer(),
    )


def test_cli_run_publishes_case(monkeypatch):
    runner = CliRunner()

    def fake_run_service(*args, **kwargs) -> RunService:
        return RunService(dependencies=build_dependencies())

    monkeypatch.setattr("jawafdehi_agents.cli.RunService", fake_run_service)
    result = runner.invoke(app, ["run", "081-CR-0046"])

    assert result.exit_code == 0
    assert "Published Jawafdehi case 42" in result.stdout


def test_cli_rejects_invalid_case_number():
    runner = CliRunner()
    result = runner.invoke(app, ["run", "bad-case-number"])
    assert result.exit_code != 0
