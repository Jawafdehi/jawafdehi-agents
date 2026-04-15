from __future__ import annotations

from jawafdehi_agents.dependencies import get_dependencies
from jawafdehi_agents.flyte_compat import env, group, trace
from jawafdehi_agents.models import (
    ACCEPTED_REVIEW_OUTCOMES,
    Critique,
    DraftInput,
    RefinementIteration,
    RefinementResult,
    ReviewOutcome,
)
from jawafdehi_agents.workflows.ciaa_caseworker.helpers import (
    render_review_markdown,
    validate_output,
    write_text,
)


@trace
async def critique_content(draft: str, draft_input: DraftInput) -> Critique:
    return await get_dependencies().draft_refinement_agent.critique_content(
        draft, draft_input
    )


@trace
async def revise_content(
    draft: str, critique: Critique, draft_input: DraftInput
) -> str:
    return await get_dependencies().draft_refinement_agent.revise_content(
        draft, critique, draft_input
    )


@env.task(retries=3)
async def draft_and_refine_case_agent(
    draft_input: DraftInput,
    max_iterations: int = 3,
    quality_threshold: int = 8,
) -> RefinementResult:
    draft_path = draft_input.workspace.root_dir / "draft.md"
    review_path = draft_input.workspace.root_dir / "draft-review.md"

    draft = await get_dependencies().draft_refinement_agent.generate_draft(draft_input)
    write_text(draft_path, draft)
    validate_output(draft_path, draft_input.workspace.root_dir)

    iterations: list[RefinementIteration] = []

    for iteration in range(1, max_iterations + 1):
        with group(f"refinement-{iteration}"):
            critique = await critique_content(draft, draft_input)
            write_text(review_path, render_review_markdown(critique))
            validate_output(review_path, draft_input.workspace.root_dir)

            if (
                critique.outcome in ACCEPTED_REVIEW_OUTCOMES
                and critique.score >= quality_threshold
            ):
                iterations.append(
                    RefinementIteration(
                        iteration=iteration,
                        critique=critique,
                        revised=False,
                    )
                )
                return RefinementResult(
                    workspace=draft_input.workspace,
                    draft_path=draft_path,
                    review_path=review_path,
                    final_score=critique.score,
                    final_outcome=critique.outcome,
                    iterations=iterations,
                )

            if critique.outcome == ReviewOutcome.blocked:
                iterations.append(
                    RefinementIteration(
                        iteration=iteration,
                        critique=critique,
                        revised=False,
                    )
                )
                raise RuntimeError("Draft review was blocked")

            if iteration == max_iterations:
                iterations.append(
                    RefinementIteration(
                        iteration=iteration,
                        critique=critique,
                        revised=False,
                    )
                )
                raise RuntimeError("Draft refinement exhausted maximum iterations")

            draft = await revise_content(draft, critique, draft_input)
            write_text(draft_path, draft)
            validate_output(draft_path, draft_input.workspace.root_dir)
            iterations.append(
                RefinementIteration(
                    iteration=iteration,
                    critique=critique,
                    revised=True,
                )
            )

    raise RuntimeError("Draft refinement did not finish")
