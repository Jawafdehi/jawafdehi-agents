from __future__ import annotations

from pathlib import Path

from jawafdehi_agents.dependencies import ensure_within_workspace
from jawafdehi_agents.models import Critique


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_review_markdown(critique: Critique) -> str:
    strengths = "\n".join(f"- {item}" for item in critique.strengths) or "- None"
    improvements = "\n".join(f"- {item}" for item in critique.improvements) or "- None"
    blockers = "\n".join(f"- {item}" for item in critique.blockers) or "- None"
    return (
        "# Draft Review\n\n"
        f"## Score\n\n{critique.score}\n\n"
        f"## Outcome\n\n**`{critique.outcome.value}`**\n\n"
        "## Strengths\n\n"
        f"{strengths}\n\n"
        "## Improvements\n\n"
        f"{improvements}\n\n"
        "## Blockers\n\n"
        f"{blockers}\n"
    )


def validate_output(path: Path, workspace_root: Path) -> None:
    ensure_within_workspace(workspace_root, path)
    if not path.is_file():
        raise RuntimeError(f"Expected output file was not created: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"Expected output file is empty: {path}")
