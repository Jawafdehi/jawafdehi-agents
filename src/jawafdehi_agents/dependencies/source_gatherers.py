from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from jawafdehi_agents.assets import ciaa_ag_index_path, ciaa_press_releases_path
from jawafdehi_agents.models import CaseInitialization, SourceArtifact, SourceBundle

from .runtime_clients import DocumentConversionClient, RemoteDocumentFetcher

logger = logging.getLogger(__name__)


class WorkspaceSourceGatherer:
    """Workspace-backed source gatherer using real downloads and markdown conversion."""

    def __init__(
        self,
        *,
        fetcher: RemoteDocumentFetcher | None = None,
        converter: DocumentConversionClient | None = None,
    ) -> None:
        self.fetcher = fetcher or RemoteDocumentFetcher()
        self.converter = converter or DocumentConversionClient()

    def _base_bundle(self, initialization: CaseInitialization) -> SourceBundle:
        raw_case_details_path = (
            initialization.workspace.sources_raw_dir / "special-court-case-details.txt"
        )
        markdown_case_details_path = (
            initialization.workspace.sources_markdown_dir / "special-court-case-details.md"
        )
        case_details = initialization.case_details_path.read_text(encoding="utf-8")
        raw_case_details_path.write_text(case_details, encoding="utf-8")
        markdown_case_details_path.write_text(case_details, encoding="utf-8")
        return SourceBundle(
            case_number=initialization.case_number,
            workspace=initialization.workspace,
            asset_root=initialization.asset_root,
            case_details_path=initialization.case_details_path,
            raw_sources=[raw_case_details_path],
            markdown_sources=[markdown_case_details_path],
            case_details_artifact=SourceArtifact(
                source_type="case_details",
                title="Special Court case details",
                raw_path=raw_case_details_path,
                markdown_path=markdown_case_details_path,
                notes="Workspace bootstrap copy of initialized case details.",
            ),
        )

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "source"

    @staticmethod
    def _extract_primary_defendant(case_details: str) -> str | None:
        bold_match = re.search(r"(?m)^- \*\*(.+?)\*\*", case_details)
        if bold_match:
            return bold_match.group(1).strip()
        defendant_match = re.search(r"(?im)^- .*defendant.*?:\s*(.+)$", case_details)
        if defendant_match:
            return defendant_match.group(1).strip()
        return None

    @staticmethod
    def _append_artifact(bundle: SourceBundle, artifact: SourceArtifact) -> SourceBundle:
        raw_sources = list(bundle.raw_sources)
        markdown_sources = list(bundle.markdown_sources)
        if artifact.raw_path not in raw_sources:
            raw_sources.append(artifact.raw_path)
        if artifact.markdown_path not in markdown_sources:
            markdown_sources.append(artifact.markdown_path)
        return bundle.model_copy(
            update={
                "raw_sources": raw_sources,
                "markdown_sources": markdown_sources,
            }
        )

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _find_press_release_row(
        self, initialization: CaseInitialization
    ) -> dict[str, str] | None:
        case_details = initialization.case_details_path.read_text(encoding="utf-8")
        primary_defendant = self._extract_primary_defendant(case_details)
        rows = self._read_csv(ciaa_press_releases_path())
        charge_sheet_row = self._find_charge_sheet_row(initialization)
        charge_title = (charge_sheet_row or {}).get("title") or ""
        search_terms = [initialization.case_number, charge_title]
        if primary_defendant:
            search_terms.append(primary_defendant)
        normalized_terms = [
            self._normalize_text(term) for term in search_terms if term and term.strip()
        ]
        for row in rows:
            haystacks = [
                self._normalize_text(row.get("title") or ""),
                self._normalize_text(row.get("full_text") or ""),
            ]
            if any(term and any(term in haystack for haystack in haystacks) for term in normalized_terms):
                return row
        return None

    def _find_charge_sheet_row(
        self, initialization: CaseInitialization
    ) -> dict[str, str] | None:
        rows = self._read_csv(ciaa_ag_index_path())
        for row in rows:
            if (row.get("case_number") or "").strip().upper() == initialization.case_number:
                return row
        return None

    async def gather_sources(self, initialization: CaseInitialization) -> SourceBundle:
        logger.debug(
            "Preparing workspace-backed source bundle for %s",
            initialization.case_number,
        )
        return self._base_bundle(initialization)

    async def gather_press_release(
        self, initialization: CaseInitialization, bundle: SourceBundle
    ) -> SourceBundle:
        row = self._find_press_release_row(initialization)
        if row is None:
            raise RuntimeError(
                f"No CIAA press release row matched case {initialization.case_number}"
            )
        press_id = (row.get("press_id") or initialization.case_number.lower()).strip()
        title = (row.get("title") or "").strip()
        source_url = (row.get("source_url") or "").strip()
        publication_date = (row.get("publication_date") or "").strip()
        full_text = (row.get("full_text") or "").strip()
        if not source_url:
            raise RuntimeError(
                f"Matched CIAA press release for {initialization.case_number} is missing source_url"
            )
        raw_path = (
            initialization.workspace.sources_raw_dir / f"ciaa-press-release-{press_id}.html"
        )
        markdown_path = (
            initialization.workspace.sources_markdown_dir / f"ciaa-press-release-{press_id}.md"
        )
        await self.fetcher.download(source_url, raw_path)
        converted_markdown = await self.converter.convert_file_to_markdown(
            raw_path, markdown_path
        )
        if full_text and self._normalize_text(full_text) not in self._normalize_text(
            converted_markdown
        ):
            markdown_path.write_text(
                (
                    f"# {title}\n\n"
                    f"- Publication date: {publication_date or 'unknown'}\n"
                    f"- Source URL: {source_url}\n\n"
                    "## CIAA structured text\n\n"
                    f"{full_text}\n\n"
                    "## Converted page\n\n"
                    f"{converted_markdown.strip()}\n"
                ),
                encoding="utf-8",
            )
        artifact = SourceArtifact(
            source_type="press_release",
            title=title or f"CIAA press release for {initialization.case_number}",
            raw_path=raw_path,
            markdown_path=markdown_path,
            source_url=source_url,
            identifier=press_id,
            notes="Downloaded from CIAA and converted to markdown.",
        )
        bundle = self._append_artifact(bundle, artifact)
        return bundle.model_copy(update={"press_release_artifact": artifact})

    async def gather_charge_sheet(
        self, initialization: CaseInitialization, bundle: SourceBundle
    ) -> SourceBundle:
        row = self._find_charge_sheet_row(initialization)
        if row is None:
            raise RuntimeError(
                f"No AG index row found for case {initialization.case_number}"
            )
        title = (row.get("title") or "").strip()
        pdf_url = (row.get("pdf_url") or "").strip()
        filing_date = (row.get("filing_date") or "").strip()
        if not pdf_url:
            raise RuntimeError(
                f"AG index row for {initialization.case_number} is missing pdf_url"
            )
        raw_path = await self.fetcher.download_with_detected_extension(
            pdf_url,
            initialization.workspace.sources_raw_dir
            / f"charge-sheet-{initialization.case_number}",
        )
        markdown_path = (
            initialization.workspace.sources_markdown_dir
            / f"charge-sheet-{initialization.case_number}.md"
        )
        converted_markdown = await self.converter.convert_file_to_markdown(
            raw_path, markdown_path
        )
        markdown_path.write_text(
            (
                f"# {title or f'Charge sheet for {initialization.case_number}'}\n\n"
                f"- Filing date: {filing_date or 'unknown'}\n"
                f"- PDF URL: {pdf_url}\n"
                f"- Case number: {initialization.case_number}\n\n"
                "## Converted content\n\n"
                f"{converted_markdown.strip()}\n"
            ),
            encoding="utf-8",
        )
        artifact = SourceArtifact(
            source_type="charge_sheet",
            title=title or f"Charge sheet for {initialization.case_number}",
            raw_path=raw_path,
            markdown_path=markdown_path,
            source_url=pdf_url,
            identifier=initialization.case_number,
            notes="Downloaded from AG index and converted to markdown.",
        )
        bundle = self._append_artifact(bundle, artifact)
        return bundle.model_copy(update={"charge_sheet_artifact": artifact})

    async def gather_news_sources(
        self, initialization: CaseInitialization, bundle: SourceBundle
    ) -> SourceBundle:
        logger.debug(
            "Skipping pre-news placeholder generation for %s; runtime news discovery runs in gather_news",
            initialization.case_number,
        )
        return bundle
