from __future__ import annotations

import tempfile
from pathlib import Path

from jawafdehi_agents.models import WorkspaceContext


def create_workspace(case_number: str) -> WorkspaceContext:
    root_dir = Path(tempfile.mkdtemp(prefix=f"jawaf-{case_number}-"))
    sources_raw_dir = root_dir / "sources" / "raw"
    sources_markdown_dir = root_dir / "sources" / "markdown"
    logs_dir = root_dir / "logs"
    memory_file = root_dir / "MEMORY.md"

    sources_raw_dir.mkdir(parents=True, exist_ok=True)
    sources_markdown_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("", encoding="utf-8")

    return WorkspaceContext(
        root_dir=root_dir,
        memory_file=memory_file,
        sources_raw_dir=sources_raw_dir,
        sources_markdown_dir=sources_markdown_dir,
        logs_dir=logs_dir,
    )
