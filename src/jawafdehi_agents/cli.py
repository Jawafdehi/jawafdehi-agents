from __future__ import annotations

import typer

from jawafdehi_agents.run_service import RunService
from jawafdehi_agents.settings import get_settings

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main_callback() -> None:
    """Jawaf CLI."""
    get_settings()


@app.command("run")
def run(case_number: str) -> None:
    """Run the CIAA workflow for a single CIAA Special Court case number."""
    result = RunService().start_run(case_number)
    if result.published and result.case_id is not None:
        typer.echo(
            f"Published Jawafdehi case {result.case_id} for {result.case_number}"
        )
        raise typer.Exit(code=0)

    typer.echo(
        "Workflow stopped before publication "
        f"for {result.case_number} with outcome {result.final_outcome}"
    )
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
