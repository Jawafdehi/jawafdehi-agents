# Jawafdehi Agents

Flyte-based agent orchestration service for Jawafdehi workflows.

## Development

Copy [` .env.example `](services/jawafdehi-agents/.env.example) to `.env` and set [`JAWAFDEHI_API_TOKEN`](services/jawafdehi-agents/src/jawafdehi_agents/settings.py:18) before running the CLI.

Install dependencies with Poetry:

```bash
poetry install
```

Run tests:

```bash
poetry run pytest
```

Format and lint:

```bash
./scripts/format.sh
./scripts/format.sh --check
```

Run the CLI:

```bash
poetry run jawaf run 081-CR-0046
```
