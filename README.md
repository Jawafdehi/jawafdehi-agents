# Jawafdehi Agents

Superseded by `services/jawafdehi-agentspan`.

This service captured the earlier Flyte-based CIAA orchestration experiment. The active CIAA caseworker implementation now lives in `services/jawafdehi-agentspan` and uses AgentSpan.

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

## License

Licensed under the [Hippocratic License 3.0](./LICENSE), an [Ethical Source](https://ethicalsource.dev) license. See [LICENSING.md](./LICENSING.md) for details.
```
