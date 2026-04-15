from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from jawafdehi_agents.models import (
    CaseInitialization,
    Critique,
    DraftInput,
    PublishedCaseResult,
    PublishInput,
    SourceBundle,
)


class NGMClient(Protocol):
    async def fetch_case_details(self, case_number: str) -> str: ...


class SourceGatherer(Protocol):
    async def gather_sources(
        self, initialization: CaseInitialization
    ) -> SourceBundle: ...


class NewsGatherer(Protocol):
    async def gather_news(self, source_bundle: SourceBundle) -> SourceBundle: ...


class DraftRefinementAgent(Protocol):
    async def generate_draft(self, draft_input: DraftInput) -> str: ...

    async def critique_content(
        self, draft: str, draft_input: DraftInput
    ) -> Critique: ...

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str: ...


class PublishFinalizer(Protocol):
    async def publish_and_finalize(
        self, publish_input: PublishInput
    ) -> PublishedCaseResult: ...


class NotImplementedNGMClient:
    async def fetch_case_details(self, case_number: str) -> str:
        raise NotImplementedError(
            f"NGM client not configured for case number {case_number}"
        )


class NotImplementedSourceGatherer:
    async def gather_sources(self, initialization: CaseInitialization) -> SourceBundle:
        raise NotImplementedError("Source gathering is not configured yet")


class NotImplementedNewsGatherer:
    async def gather_news(self, source_bundle: SourceBundle) -> SourceBundle:
        raise NotImplementedError("News gathering is not configured yet")


class NotImplementedDraftRefinementAgent:
    async def generate_draft(self, draft_input: DraftInput) -> str:
        raise NotImplementedError("Draft generation is not configured yet")

    async def critique_content(self, draft: str, draft_input: DraftInput) -> Critique:
        raise NotImplementedError("Draft critique is not configured yet")

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str:
        raise NotImplementedError("Draft revision is not configured yet")


class NotImplementedPublishFinalizer:
    async def publish_and_finalize(
        self, publish_input: PublishInput
    ) -> PublishedCaseResult:
        raise NotImplementedError("Jawafdehi publication is not configured yet")


class WorkflowDependencies:
    def __init__(
        self,
        *,
        ngm_client: NGMClient,
        source_gatherer: SourceGatherer,
        news_gatherer: NewsGatherer,
        draft_refinement_agent: DraftRefinementAgent,
        publish_finalizer: PublishFinalizer,
    ) -> None:
        self.ngm_client = ngm_client
        self.source_gatherer = source_gatherer
        self.news_gatherer = news_gatherer
        self.draft_refinement_agent = draft_refinement_agent
        self.publish_finalizer = publish_finalizer


def build_default_dependencies() -> WorkflowDependencies:
    return WorkflowDependencies(
        ngm_client=NotImplementedNGMClient(),
        source_gatherer=NotImplementedSourceGatherer(),
        news_gatherer=NotImplementedNewsGatherer(),
        draft_refinement_agent=NotImplementedDraftRefinementAgent(),
        publish_finalizer=NotImplementedPublishFinalizer(),
    )


_CURRENT_DEPENDENCIES = build_default_dependencies()


def get_dependencies() -> WorkflowDependencies:
    return _CURRENT_DEPENDENCIES


@contextmanager
def use_dependencies(dependencies: WorkflowDependencies):
    global _CURRENT_DEPENDENCIES
    previous = _CURRENT_DEPENDENCIES
    _CURRENT_DEPENDENCIES = dependencies
    try:
        yield
    finally:
        _CURRENT_DEPENDENCIES = previous


def ensure_within_workspace(workspace_root: Path, path: Path) -> None:
    resolved_root = workspace_root.resolve()
    resolved_path = path.resolve()
    resolved_path.relative_to(resolved_root)
