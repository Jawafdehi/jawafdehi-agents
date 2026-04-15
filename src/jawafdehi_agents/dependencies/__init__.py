from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import httpx

from jawafdehi_agents.models import (
    CaseInitialization,
    Critique,
    DraftInput,
    PublishedCaseResult,
    PublishInput,
    SourceBundle,
)

logger = logging.getLogger(__name__)


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


class JawafdehiAPINGMClient:
    def __init__(self, court_identifier: str = "special") -> None:
        self.court_identifier = court_identifier

    @staticmethod
    def _sql_quote(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _rows_to_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") or {}
        columns = data.get("columns") or []
        rows = data.get("rows") or []
        records: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(columns):
                raise RuntimeError(
                    "Malformed proxy payload: "
                    f"row {index} has "
                    f"{len(row) if isinstance(row, list) else 'non-list'} values "
                    f"for {len(columns)} columns"
                )
            records.append(dict(zip(columns, row, strict=True)))
        return records

    @staticmethod
    def _format_markdown(
        court_info: dict[str, Any],
        case_info: dict[str, Any],
        hearings: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> str:
        markdown_lines: list[str] = []
        court_name_en = (
            court_info.get("full_name_english", "Unknown Court")
            if court_info
            else "Unknown Court"
        )
        court_name_np = court_info.get("full_name_nepali", "") if court_info else ""
        case_no = (
            case_info.get("case_number", "Unknown Case")
            if case_info
            else "Unknown Case"
        )

        markdown_lines.append(f"# Case Extract: {case_no}")
        markdown_lines.append(f"**Court:** {court_name_en} ({court_name_np})")

        if not case_info:
            markdown_lines.append(
                "\n*Could not find metadata for this exact case number and court.*"
            )
            return "\n".join(markdown_lines)

        markdown_lines.append("\n## Case Information")
        markdown_lines.append("| Property | Value |")
        markdown_lines.append("|---|---|")

        props = [
            ("Case Type", "case_type"),
            ("Status", "case_status"),
            ("Registration Date (AD)", "registration_date_ad"),
            ("Registration Date (BS)", "registration_date_bs"),
            ("Division", "division"),
            ("Category", "category"),
            ("Section", "section"),
            ("Priority", "priority"),
            ("Original Case Number", "original_case_number"),
            ("Verdict Date (AD)", "verdict_date_ad"),
            ("Verdict Date (BS)", "verdict_date_bs"),
            ("Verdict Judge", "verdict_judge"),
        ]

        def default_serializer(obj: Any) -> str:
            return str(obj)

        for label, key in props:
            value = case_info.get(key)
            if value is not None and value != "":
                markdown_lines.append(f"| **{label}** | {value} |")

        if entities:
            markdown_lines.append("\n## Entities Involved")

            plaintiffs = [
                entity
                for entity in entities
                if str(entity.get("side")).lower() == "plaintiff"
            ]
            defendants = [
                entity
                for entity in entities
                if str(entity.get("side")).lower() == "defendant"
            ]
            others = [
                entity
                for entity in entities
                if str(entity.get("side")).lower() not in ["plaintiff", "defendant"]
            ]

            if plaintiffs:
                markdown_lines.append("\n### Plaintiffs")
                for entity in plaintiffs:
                    nes = (
                        f" (NES ID: {entity.get('nes_id')})"
                        if entity.get("nes_id")
                        else ""
                    )
                    addr = (
                        f" - {entity.get('address')}" if entity.get("address") else ""
                    )
                    markdown_lines.append(
                        f"- **{entity.get('name', 'Unknown')}**{addr}{nes}"
                    )

            if defendants:
                markdown_lines.append("\n### Defendants")
                for entity in defendants:
                    nes = (
                        f" (NES ID: {entity.get('nes_id')})"
                        if entity.get("nes_id")
                        else ""
                    )
                    addr = (
                        f" - {entity.get('address')}" if entity.get("address") else ""
                    )
                    markdown_lines.append(
                        f"- **{entity.get('name', 'Unknown')}**{addr}{nes}"
                    )

            if others:
                markdown_lines.append("\n### Other Entities")
                for entity in others:
                    nes = (
                        f" (NES ID: {entity.get('nes_id')})"
                        if entity.get("nes_id")
                        else ""
                    )
                    side = f"[{entity.get('side')}] " if entity.get("side") else ""
                    addr = (
                        f" - {entity.get('address')}" if entity.get("address") else ""
                    )
                    markdown_lines.append(
                        f"- {side}**{entity.get('name', 'Unknown')}**{addr}{nes}"
                    )

        if hearings:
            markdown_lines.append("\n## Hearing History")
            for hearing in sorted(
                hearings, key=lambda item: str(item.get("hearing_date_ad", ""))
            ):
                date_ad = hearing.get("hearing_date_ad")
                date_bs = hearing.get("hearing_date_bs", "Unknown Date")
                date_str = f"{date_bs} ({date_ad})" if date_ad else f"{date_bs}"

                markdown_lines.append(
                    f"\n### {date_str} - {hearing.get('decision_type', 'Hearing')}"
                )

                judge = hearing.get(
                    "judge_names", hearing.get("bench", "Unknown Bench")
                )
                markdown_lines.append(f"- **Judges / Bench:** {judge}")

                if hearing.get("bench_type"):
                    markdown_lines.append(
                        f"- **Bench Type:** {hearing.get('bench_type')}"
                    )

                if hearing.get("case_status"):
                    markdown_lines.append(
                        f"- **Case Status:** {hearing.get('case_status')}"
                    )

                if hearing.get("lawyer_names"):
                    markdown_lines.append(
                        f"- **Lawyers:** {hearing.get('lawyer_names')}"
                    )

                if hearing.get("remarks"):
                    markdown_lines.append(f"\n> **Remarks:** {hearing.get('remarks')}")

        markdown_lines.append("\n---")
        markdown_lines.append("\n## Appendix: Raw Data")
        markdown_lines.append(
            "*This section contains unformatted raw database records "
            "for reference and data integrity.*"
        )

        if case_info:
            markdown_lines.append("\n### Full Case Record")
            markdown_lines.append("```json")
            markdown_lines.append(
                json.dumps(
                    case_info,
                    indent=2,
                    ensure_ascii=False,
                    default=default_serializer,
                )
            )
            markdown_lines.append("```")

        if hearings:
            markdown_lines.append("\n### Hearing Records")
            sorted_hearings = sorted(
                hearings, key=lambda item: str(item.get("hearing_date_ad", ""))
            )
            for index, hearing in enumerate(sorted_hearings, start=1):
                date_ad = hearing.get("hearing_date_ad")
                date_bs = hearing.get("hearing_date_bs", "Unknown Date")
                date_str = f"{date_bs} ({date_ad})" if date_ad else f"{date_bs}"
                decision = hearing.get("decision_type", "Hearing")
                markdown_lines.append(
                    f"\n#### Hearing {index}: {date_str} — {decision}"
                )
                markdown_lines.append("```json")
                markdown_lines.append(
                    json.dumps(
                        hearing,
                        indent=2,
                        ensure_ascii=False,
                        default=default_serializer,
                    )
                )
                markdown_lines.append("```")

        return "\n".join(markdown_lines)

    async def _execute_proxy_query(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        token: str,
        query: str,
        timeout: float = 15,
    ) -> dict[str, Any]:
        response = await client.post(
            f"{base_url}/api/ngm/query_judicial",
            json={"query": query, "timeout": timeout},
            headers={"Authorization": f"Token {token}"},
            timeout=30.0,
        )

        try:
            payload: dict[str, Any] = response.json()
        except ValueError:
            payload = {
                "success": False,
                "error": f"Non-JSON response from proxy ({response.status_code})",
                "raw": response.text,
            }

        if not response.is_success or not payload.get("success"):
            raise RuntimeError(
                f"NGM proxy query failed ({response.status_code}): "
                f"{json.dumps(payload, ensure_ascii=False)}"
            )

        return payload

    async def fetch_case_details(self, case_number: str) -> str:
        try:
            from pydantic import ValidationError

            from jawafdehi_agents.settings import get_settings

            settings = get_settings()
        except (ImportError, ValidationError) as exc:
            raise RuntimeError(
                "NGM client requires Jawafdehi API configuration. "
                "Set JAWAFDEHI_API_TOKEN before running the workflow."
            ) from exc

        base_url = settings.jawafdehi_api_base_url.rstrip("/")
        token = settings.jawafdehi_api_token.strip()
        if not token:
            raise RuntimeError("NGM client requires a non-empty JAWAFDEHI_API_TOKEN.")

        court_id_sql = self._sql_quote(self.court_identifier)
        case_no_sql = self._sql_quote(case_number)

        async with httpx.AsyncClient() as client:
            court_payload = await self._execute_proxy_query(
                client,
                base_url=base_url,
                token=token,
                query=(
                    "SELECT * FROM courts "
                    f"WHERE identifier = '{court_id_sql}' "
                    "LIMIT 1"
                ),
            )
            court_rows = self._rows_to_dicts(court_payload)
            court_info = court_rows[0] if court_rows else {}

            case_payload = await self._execute_proxy_query(
                client,
                base_url=base_url,
                token=token,
                query=(
                    "SELECT * FROM court_cases "
                    f"WHERE court_identifier = '{court_id_sql}' "
                    f"AND case_number = '{case_no_sql}' "
                    "LIMIT 1"
                ),
            )
            case_rows = self._rows_to_dicts(case_payload)
            case_info = case_rows[0] if case_rows else {}

            entities_payload = await self._execute_proxy_query(
                client,
                base_url=base_url,
                token=token,
                query=(
                    "SELECT * FROM court_case_entities "
                    f"WHERE court_identifier = '{court_id_sql}' "
                    f"AND case_number = '{case_no_sql}'"
                ),
            )
            entities = self._rows_to_dicts(entities_payload)

            hearings_payload = await self._execute_proxy_query(
                client,
                base_url=base_url,
                token=token,
                query=(
                    "SELECT * FROM court_case_hearings "
                    f"WHERE court_identifier = '{court_id_sql}' "
                    f"AND case_number = '{case_no_sql}'"
                ),
            )
            hearings = self._rows_to_dicts(hearings_payload)

        return self._format_markdown(court_info, case_info, hearings, entities)


class WorkspaceSourceGatherer:
    async def gather_sources(self, initialization: CaseInitialization) -> SourceBundle:
        logger.debug(
            "Preparing workspace-backed source bundle for %s",
            initialization.case_number,
        )
        raw_case_details_path = (
            initialization.workspace.sources_raw_dir / "special-court-case-details.txt"
        )
        markdown_case_details_path = (
            initialization.workspace.sources_markdown_dir
            / "special-court-case-details.md"
        )
        case_details = initialization.case_details_path.read_text(encoding="utf-8")
        raw_case_details_path.write_text(case_details, encoding="utf-8")
        markdown_case_details_path.write_text(case_details, encoding="utf-8")
        logger.debug(
            "Workspace-backed sources created at %s and %s for %s",
            raw_case_details_path,
            markdown_case_details_path,
            initialization.case_number,
        )
        return SourceBundle(
            case_number=initialization.case_number,
            workspace=initialization.workspace,
            asset_root=initialization.asset_root,
            case_details_path=initialization.case_details_path,
            raw_sources=[raw_case_details_path],
            markdown_sources=[markdown_case_details_path],
        )


class NoOpNewsGatherer:
    async def gather_news(self, source_bundle: SourceBundle) -> SourceBundle:
        logger.debug(
            "No additional news integration configured for %s; preserving %s markdown sources",
            source_bundle.case_number,
            len(source_bundle.markdown_sources),
        )
        return source_bundle


class DeterministicDraftRefinementAgent:
    @staticmethod
    def _extract_markdown_section(document: str, heading: str) -> str:
        pattern = rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
        match = re.search(pattern, document)
        if not match:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _derive_title(case_number: str, case_details: str) -> str:
        defendant_match = re.search(r"(?m)^- \*\*(.+?)\*\*", case_details)
        if defendant_match:
            return (
                f"Special Court corruption case {case_number} involving "
                f"{defendant_match.group(1)}"
            )
        return f"Special Court corruption case {case_number}"

    async def generate_draft(self, draft_input: DraftInput) -> str:
        logger.debug(
            "Generating deterministic draft body for %s", draft_input.case_number
        )
        case_details = draft_input.case_details_path.read_text(encoding="utf-8")
        title = self._derive_title(draft_input.case_number, case_details)
        short_description = (
            f"Structured draft for Special Court case {draft_input.case_number} "
            "prepared from judicial extraction records."
        )
        key_allegations = (
            "- The case has been extracted from the Special Court judicial record.\n"
            "- Facts still require supporting primary-source and reporting enrichment."
        )
        timeline = "- Registration recorded in Special Court data extract."
        description = (
            "This draft was generated from the Special Court judicial extract captured "
            "during workflow initialization.\n\n"
            "## Judicial Extract\n\n"
            f"{case_details.strip()}"
        )
        missing_details = (
            "Additional source documents, corroborating media coverage, and entity "
            "resolution should be added in a later workflow revision."
        )
        return (
            "# Jawafdehi Case Draft\n\n"
            "## Title\n"
            f"{title}\n\n"
            "## Short Description\n"
            f"{short_description}\n\n"
            "## Key Allegations\n"
            f"{key_allegations}\n\n"
            "## Timeline\n"
            f"{timeline}\n\n"
            "## Description\n"
            f"{description}\n\n"
            "## Missing Details\n"
            f"{missing_details}\n"
        )

    async def critique_content(self, draft: str, draft_input: DraftInput) -> Critique:
        logger.debug(
            "Running deterministic draft critique for %s", draft_input.case_number
        )
        required_headings = [
            "## Title",
            "## Short Description",
            "## Key Allegations",
            "## Description",
            "## Missing Details",
        ]
        missing = [heading for heading in required_headings if heading not in draft]
        if missing:
            return Critique(
                score=4,
                outcome="needs_revision",
                strengths=["Draft file was generated successfully."],
                improvements=[
                    "Add the required draft sections before publication: "
                    + ", ".join(missing)
                ],
                blockers=[],
            )
        return Critique(
            score=9,
            outcome="approved",
            strengths=[
                "Draft contains the required publishing sections.",
                "Draft is grounded in the Special Court case extract.",
            ],
            improvements=[],
            blockers=[],
        )

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str:
        logger.debug(
            "Applying deterministic draft revision for %s with %s improvements",
            draft_input.case_number,
            len(critique.improvements),
        )
        if "## Missing Details" not in draft:
            return (
                draft
                + "\n\n## Missing Details\nWorkflow revision inserted this section.\n"
            )
        return draft


class JawafdehiAPIPublishFinalizer:
    @staticmethod
    def _extract_markdown_section(document: str, heading: str) -> str:
        pattern = rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
        match = re.search(pattern, document)
        if not match:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _extract_bullets(section_body: str) -> list[str]:
        return [
            line[2:].strip()
            for line in section_body.splitlines()
            if line.strip().startswith("- ") and line[2:].strip()
        ]

    @staticmethod
    def _build_create_payload(
        publish_input: PublishInput, draft_text: str
    ) -> dict[str, Any]:
        title = (
            JawafdehiAPIPublishFinalizer._extract_markdown_section(draft_text, "Title")
            or f"Special Court corruption case {publish_input.case_number}"
        )
        short_description = JawafdehiAPIPublishFinalizer._extract_markdown_section(
            draft_text, "Short Description"
        )
        description = JawafdehiAPIPublishFinalizer._extract_markdown_section(
            draft_text, "Description"
        )
        missing_details = JawafdehiAPIPublishFinalizer._extract_markdown_section(
            draft_text, "Missing Details"
        )
        key_allegations = JawafdehiAPIPublishFinalizer._extract_bullets(
            JawafdehiAPIPublishFinalizer._extract_markdown_section(
                draft_text, "Key Allegations"
            )
        )
        payload: dict[str, Any] = {
            "title": title,
            "case_type": "CORRUPTION",
            "short_description": short_description,
            "description": description,
            "key_allegations": key_allegations,
            "tags": ["ciaa", "special-court", "agent-generated"],
            "court_cases": [f"special:{publish_input.case_number}"],
            "missing_details": missing_details or None,
        }
        return payload

    @staticmethod
    def _build_patch_operations(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"op": "replace", "path": f"/{field}", "value": value}
            for field, value in payload.items()
        ]

    @staticmethod
    def _extract_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        results = payload.get("results")
        if isinstance(results, list):
            return results
        return []

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        token: str,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await client.request(
            method,
            url,
            json=json_body,
            params=params,
            headers={"Authorization": f"Token {token}"},
            timeout=30.0,
        )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Jawafdehi API returned non-JSON response ({response.status_code})"
            ) from exc
        if not response.is_success:
            raise RuntimeError(
                f"Jawafdehi API request failed ({response.status_code}): "
                f"{json.dumps(payload, ensure_ascii=False)}"
            )
        return payload

    async def _find_existing_case_id(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        token: str,
        case_number: str,
    ) -> int | None:
        logger.debug("Searching for existing Jawafdehi case for %s", case_number)
        payload = await self._request_json(
            client,
            "GET",
            f"{base_url}/api/cases/",
            token=token,
            params={"case_type": "CORRUPTION", "search": case_number},
        )
        target = f"special:{case_number}"
        for result in self._extract_results(payload):
            court_cases = result.get("court_cases") or []
            if target in court_cases:
                logger.debug(
                    "Matched existing Jawafdehi case id=%s for %s",
                    result.get("id"),
                    case_number,
                )
                return result.get("id")
        return None

    async def publish_and_finalize(
        self, publish_input: PublishInput
    ) -> PublishedCaseResult:
        from jawafdehi_agents.settings import get_settings

        settings = get_settings()
        base_url = settings.jawafdehi_api_base_url.rstrip("/")
        token = settings.jawafdehi_api_token.strip()
        if not token:
            raise RuntimeError(
                "Publish finalizer requires a non-empty JAWAFDEHI_API_TOKEN."
            )
        draft_text = publish_input.refinement_result.draft_path.read_text(
            encoding="utf-8"
        )
        payload = self._build_create_payload(publish_input, draft_text)
        logger.debug(
            "Publishing %s to Jawafdehi API with payload fields: %s",
            publish_input.case_number,
            sorted(payload.keys()),
        )
        async with httpx.AsyncClient() as client:
            case_id = await self._find_existing_case_id(
                client,
                base_url=base_url,
                token=token,
                case_number=publish_input.case_number,
            )
            if case_id is None:
                logger.debug(
                    "No existing Jawafdehi case found for %s; creating new draft case",
                    publish_input.case_number,
                )
                response_payload = await self._request_json(
                    client,
                    "POST",
                    f"{base_url}/api/cases/",
                    token=token,
                    json_body=payload,
                )
                updated_fields = sorted(payload.keys())
            else:
                operations = self._build_patch_operations(payload)
                logger.debug(
                    "Updating existing Jawafdehi case id=%s for %s with %s patch ops",
                    case_id,
                    publish_input.case_number,
                    len(operations),
                )
                response_payload = await self._request_json(
                    client,
                    "PATCH",
                    f"{base_url}/api/cases/{case_id}/",
                    token=token,
                    json_body=operations,
                )
                updated_fields = [
                    operation["path"].removeprefix("/") for operation in operations
                ]
        result_case_id = int(response_payload["id"])
        logger.debug(
            "Jawafdehi API publication complete for %s as case id=%s",
            publish_input.case_number,
            result_case_id,
        )
        return PublishedCaseResult(
            case_id=result_case_id,
            updated_fields=updated_fields,
        )


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
        ngm_client=JawafdehiAPINGMClient(),
        source_gatherer=WorkspaceSourceGatherer(),
        news_gatherer=NoOpNewsGatherer(),
        draft_refinement_agent=DeterministicDraftRefinementAgent(),
        publish_finalizer=JawafdehiAPIPublishFinalizer(),
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
