from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import httpx

from jawafdehi_agents.assets import ciaa_case_template_path, ciaa_instructions_path

from jawafdehi_agents.models import (
    CaseInitialization,
    Critique,
    DraftInput,
    PublishedCaseResult,
    PublishInput,
    SourceArtifact,
    SourceBundle,
)

from .runtime_clients import (
    DocumentConversionClient,
    LLMClient,
    NewsSearchClient,
    RemoteDocumentFetcher,
)
from .source_gatherers import WorkspaceSourceGatherer

logger = logging.getLogger(__name__)


class NGMClient(Protocol):
    async def fetch_case_details(self, case_number: str) -> str: ...


class SourceGatherer(Protocol):
    async def gather_sources(
        self, initialization: CaseInitialization
    ) -> SourceBundle: ...

    async def gather_press_release(
        self, initialization: CaseInitialization, source_bundle: SourceBundle
    ) -> SourceBundle: ...

    async def gather_charge_sheet(
        self, initialization: CaseInitialization, source_bundle: SourceBundle
    ) -> SourceBundle: ...

    async def gather_news_sources(
        self, initialization: CaseInitialization, source_bundle: SourceBundle
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


class SearchBackedNewsGatherer:
    def __init__(
        self,
        *,
        search_client: NewsSearchClient,
        fetcher: RemoteDocumentFetcher,
        converter: DocumentConversionClient,
    ) -> None:
        self.search_client = search_client
        self.fetcher = fetcher
        self.converter = converter

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "news"

    async def gather_news(self, source_bundle: SourceBundle) -> SourceBundle:
        hints: list[str] = []
        if source_bundle.press_release_artifact is not None:
            hints.append(source_bundle.press_release_artifact.title)
        if source_bundle.charge_sheet_artifact is not None:
            hints.append(source_bundle.charge_sheet_artifact.title)
        if not hints:
            hints.append(source_bundle.case_number)
        results = await self.search_client.search(source_bundle.case_number, hints)
        bundle = source_bundle
        for index, result in enumerate(results, start=1):
            slug = self._slugify(result["title"])
            raw_path = (
                source_bundle.workspace.sources_raw_dir
                / f"news-{index:02d}-{slug}.html"
            )
            markdown_path = (
                source_bundle.workspace.sources_markdown_dir
                / f"news-{index:02d}-{slug}.md"
            )
            downloaded_path = await self.fetcher.download(result["url"], raw_path)
            converted_markdown = await self.converter.convert_file_to_markdown(
                downloaded_path, markdown_path
            )
            markdown_path.write_text(
                (
                    f"# {result['title']}\n\n"
                    f"- URL: {result['url']}\n"
                    f"- Case number: {source_bundle.case_number}\n\n"
                    "## Converted content\n\n"
                    f"{converted_markdown.strip()}\n"
                ),
                encoding="utf-8",
            )
            artifact = SourceArtifact(
                source_type="news",
                title=result["title"],
                raw_path=downloaded_path,
                markdown_path=markdown_path,
                source_url=result["url"],
                external_url=result["url"],
                identifier=f"{index:02d}-{slug}",
                notes="Discovered through live news search and converted to markdown.",
            )
            raw_sources = list(bundle.raw_sources)
            markdown_sources = list(bundle.markdown_sources)
            if artifact.raw_path not in raw_sources:
                raw_sources.append(artifact.raw_path)
            if artifact.markdown_path not in markdown_sources:
                markdown_sources.append(artifact.markdown_path)
            bundle = bundle.model_copy(
                update={
                    "raw_sources": raw_sources,
                    "markdown_sources": markdown_sources,
                    "news_artifacts": [*bundle.news_artifacts, artifact],
                }
            )
        return bundle


class SourceGroundedDraftRefinementAgent:
    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    @staticmethod
    def _extract_markdown_section(document: str, heading: str) -> str:
        pattern = rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
        match = re.search(pattern, document)
        if not match:
            return ""
        return match.group(1).strip()

    @staticmethod
    def _load_markdown_sources(draft_input: DraftInput) -> str:
        sections: list[str] = []
        for path in draft_input.markdown_sources:
            if not path.exists():
                continue
            sections.append(
                f"\n# Source File: {path.name}\n\n{path.read_text(encoding='utf-8').strip()}"
            )
        return "\n\n".join(sections).strip()

    @staticmethod
    def _render_draft_from_payload(payload: dict[str, Any]) -> str:
        key_allegations = payload.get("key_allegations") or []
        if isinstance(key_allegations, list):
            rendered_allegations = "\n".join(
                f"- {item}" for item in key_allegations if str(item).strip()
            )
        else:
            rendered_allegations = str(key_allegations).strip()
        timeline_items = payload.get("timeline") or []
        if isinstance(timeline_items, list):
            rendered_timeline = "\n".join(
                f"- {item}" for item in timeline_items if str(item).strip()
            )
        else:
            rendered_timeline = str(timeline_items).strip()
        return (
            "# Jawafdehi Case Draft\n\n"
            "## Title\n"
            f"{str(payload.get('title', '')).strip()}\n\n"
            "## Short Description\n"
            f"{str(payload.get('short_description', '')).strip()}\n\n"
            "## Key Allegations\n"
            f"{rendered_allegations}\n\n"
            "## Timeline\n"
            f"{rendered_timeline}\n\n"
            "## Description\n"
            f"{str(payload.get('description', '')).strip()}\n\n"
            "## Missing Details\n"
            f"{str(payload.get('missing_details', '')).strip()}\n"
        )

    async def generate_draft(self, draft_input: DraftInput) -> str:
        instructions = ciaa_instructions_path().read_text(encoding="utf-8")
        template = ciaa_case_template_path().read_text(encoding="utf-8")
        case_details = draft_input.case_details_path.read_text(encoding="utf-8")
        source_markdown = self._load_markdown_sources(draft_input)
        payload = await self.llm_client.generate_json(
            system_prompt=(
                "You write Jawafdehi corruption case drafts in Nepali. "
                "Only use the supplied source material. Return JSON with keys: "
                "title, short_description, key_allegations, timeline, description, missing_details."
            ),
            user_prompt=(
                f"Instructions:\n{instructions}\n\n"
                f"Template:\n{template}\n\n"
                f"Case number: {draft_input.case_number}\n\n"
                f"Special Court extract:\n{case_details}\n\n"
                f"Source markdown:\n{source_markdown}"
            ),
        )
        return self._render_draft_from_payload(payload)

    async def critique_content(self, draft: str, draft_input: DraftInput) -> Critique:
        required_headings = [
            "## Title",
            "## Short Description",
            "## Key Allegations",
            "## Timeline",
            "## Description",
            "## Missing Details",
        ]
        missing_headings = [heading for heading in required_headings if heading not in draft]
        improvements: list[str] = []
        blockers: list[str] = []
        strengths: list[str] = []
        if missing_headings:
            blockers.append(
                "Missing required draft sections: " + ", ".join(missing_headings)
            )
        if len(draft_input.markdown_sources) < 3:
            blockers.append("Insufficient markdown sources were gathered before drafting.")
        if "example.invalid" in draft or "placeholder" in draft.lower() or "simulat" in draft.lower():
            blockers.append("Draft still contains placeholder or simulated content.")
        description = self._extract_markdown_section(draft, "Description")
        allegations = self._extract_markdown_section(draft, "Key Allegations")
        missing_details = self._extract_markdown_section(draft, "Missing Details")
        if len(description) < 500:
            improvements.append("Expand the description with evidence-grounded factual detail.")
        if allegations.count("- ") < 2:
            improvements.append("Provide at least two concrete allegation bullets.")
        if not missing_details:
            improvements.append("Document unresolved gaps in Missing Details.")
        if not blockers:
            strengths.append("Draft includes the required structured sections.")
            strengths.append("Draft was generated from live source artifacts and court extract.")
        if blockers:
            return Critique(
                score=2,
                outcome="blocked",
                strengths=strengths,
                improvements=improvements,
                blockers=blockers,
            )
        if improvements:
            return Critique(
                score=7,
                outcome="needs_revision",
                strengths=strengths,
                improvements=improvements,
                blockers=[],
            )
        return Critique(
            score=9,
            outcome="approved",
            strengths=[*strengths, "Draft meets minimum source-grounded publication checks."],
            improvements=[],
            blockers=[],
        )

    async def revise_content(
        self, draft: str, critique: Critique, draft_input: DraftInput
    ) -> str:
        case_details = draft_input.case_details_path.read_text(encoding="utf-8")
        source_markdown = self._load_markdown_sources(draft_input)
        payload = await self.llm_client.generate_json(
            system_prompt=(
                "Revise the Jawafdehi case draft in Nepali. Use only the supplied sources and "
                "address every critique item. Return JSON with keys: title, short_description, "
                "key_allegations, timeline, description, missing_details."
            ),
            user_prompt=(
                f"Current draft:\n{draft}\n\n"
                f"Critique JSON:\n{critique.model_dump_json(indent=2)}\n\n"
                f"Case details:\n{case_details}\n\n"
                f"Source markdown:\n{source_markdown}"
            ),
        )
        return self._render_draft_from_payload(payload)


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
        patchable_payload = {
            field: value for field, value in payload.items() if field != "case_type"
        }
        return [
            {"op": "replace", "path": f"/{field}", "value": value}
            for field, value in patchable_payload.items()
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
    from jawafdehi_agents.settings import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for live drafting and critique in jawafdehi-agents."
        )
    fetcher = RemoteDocumentFetcher()
    converter = DocumentConversionClient()
    llm_client = LLMClient(
        api_key=settings.openai_api_key,
        model=settings.llm_model,
        base_url=settings.openai_base_url,
    )
    return WorkflowDependencies(
        ngm_client=JawafdehiAPINGMClient(),
        source_gatherer=WorkspaceSourceGatherer(fetcher=fetcher, converter=converter),
        news_gatherer=SearchBackedNewsGatherer(
            search_client=NewsSearchClient(
                llm_client=llm_client,
                article_limit=settings.news_article_limit,
            ),
            fetcher=fetcher,
            converter=converter,
        ),
        draft_refinement_agent=SourceGroundedDraftRefinementAgent(llm_client=llm_client),
        publish_finalizer=JawafdehiAPIPublishFinalizer(),
    )


_CURRENT_DEPENDENCIES: WorkflowDependencies | None = None


def get_dependencies() -> WorkflowDependencies:
    global _CURRENT_DEPENDENCIES
    if _CURRENT_DEPENDENCIES is None:
        _CURRENT_DEPENDENCIES = build_default_dependencies()
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
