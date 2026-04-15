from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints

CASE_NUMBER_PATTERN = r"^\d{3}-[A-Z]{2,5}-\d{4}$"
AcceptedCIAACaseNumber = Annotated[
    str,
    BeforeValidator(
        lambda value: value.strip().upper() if isinstance(value, str) else value
    ),
    StringConstraints(
        pattern=CASE_NUMBER_PATTERN,
    ),
]


class CIAACaseInput(BaseModel):
    case_number: AcceptedCIAACaseNumber


class ReviewOutcome(str, Enum):
    approved = "approved"
    approved_with_minor_edits = "approved_with_minor_edits"
    needs_revision = "needs_revision"
    blocked = "blocked"


ACCEPTED_REVIEW_OUTCOMES = {
    ReviewOutcome.approved,
    ReviewOutcome.approved_with_minor_edits,
}


class WorkspaceContext(BaseModel):
    root_dir: Path
    logs_dir: Path
    sources_raw_dir: Path
    sources_markdown_dir: Path


class CaseInitialization(BaseModel):
    case_number: str
    workspace: WorkspaceContext
    asset_root: Path
    case_details_path: Path


class SourceBundle(BaseModel):
    case_number: str
    workspace: WorkspaceContext
    asset_root: Path
    case_details_path: Path
    raw_sources: list[Path] = Field(default_factory=list)
    markdown_sources: list[Path] = Field(default_factory=list)


class DraftInput(BaseModel):
    case_number: str
    workspace: WorkspaceContext
    asset_root: Path
    case_details_path: Path
    raw_sources: list[Path] = Field(default_factory=list)
    markdown_sources: list[Path] = Field(default_factory=list)


class Critique(BaseModel):
    score: int = Field(ge=1, le=10)
    outcome: ReviewOutcome
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class RefinementIteration(BaseModel):
    iteration: int
    critique: Critique
    revised: bool


class RefinementResult(BaseModel):
    workspace: WorkspaceContext
    draft_path: Path
    review_path: Path
    final_score: int
    final_outcome: ReviewOutcome
    iterations: list[RefinementIteration] = Field(default_factory=list)


class PublishInput(BaseModel):
    case_number: str
    source_bundle: SourceBundle
    refinement_result: RefinementResult


class PublishedCaseResult(BaseModel):
    case_id: int
    entity_ids: list[int] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    updated_fields: list[str] = Field(default_factory=list)


class WorkflowResult(BaseModel):
    case_number: str
    published: bool
    case_id: int | None = None
    final_outcome: ReviewOutcome
