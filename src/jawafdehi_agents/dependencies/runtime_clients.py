from __future__ import annotations

import json
import logging
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


class DocumentConversionClient:
    def __init__(self, *, enable_plugins: bool = True) -> None:
        self.enable_plugins = enable_plugins

    async def convert_file_to_markdown(self, file_path: Path, output_path: Path) -> str:
        if not file_path.exists() or not file_path.is_file():
            raise RuntimeError(f"Cannot convert missing file: {file_path}")
        from markitdown import MarkItDown

        converter = MarkItDown(enable_plugins=self.enable_plugins)
        try:
            result = converter.convert_uri(file_path.resolve().as_uri())
        except Exception as exc:  # pragma: no cover - library exceptions vary
            raise RuntimeError(f"Document conversion failed for {file_path}: {exc}") from exc
        markdown = result.markdown.strip()
        if not markdown:
            raise RuntimeError(f"Document conversion returned empty markdown for {file_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown + "\n", encoding="utf-8")
        return markdown


class RemoteDocumentFetcher:
    def __init__(self, *, timeout: float = 60.0) -> None:
        self.timeout = timeout

    @staticmethod
    def _guess_extension(url: str, content_type: str | None) -> str:
        normalized = url.lower().split("?")[0]
        for extension in (".pdf", ".docx", ".doc", ".html", ".htm", ".txt"):
            if normalized.endswith(extension):
                return extension
        if content_type:
            lowered = content_type.lower()
            if "pdf" in lowered:
                return ".pdf"
            if "wordprocessingml" in lowered:
                return ".docx"
            if "msword" in lowered:
                return ".doc"
            if "html" in lowered:
                return ".html"
            if "text/plain" in lowered:
                return ".txt"
        return ".bin"

    async def download(self, url: str, output_path: Path) -> Path:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.get(url, headers=headers)
        if not response.is_success:
            raise RuntimeError(f"Download failed for {url} ({response.status_code})")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return output_path

    async def download_with_detected_extension(self, url: str, output_stem: Path) -> Path:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout) as client:
            response = await client.get(url, headers=headers)
        if not response.is_success:
            raise RuntimeError(f"Download failed for {url} ({response.status_code})")
        extension = self._guess_extension(url, response.headers.get("content-type"))
        output_path = output_stem.with_suffix(extension)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return output_path


class NewsSearchClient:
    def __init__(
        self,
        *,
        llm_client: "LLMClient",
        article_limit: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self.llm_client = llm_client
        self.article_limit = article_limit
        self.timeout = timeout

    @staticmethod
    def _extract_candidates(html: str) -> list[dict[str, str]]:
        pattern = re.compile(
            r'<a[^>]+class="[^\"]*result__a[^\"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        results: list[dict[str, str]] = []
        for match in pattern.finditer(html):
            title = re.sub(r"<[^>]+>", "", match.group("title"))
            title = unescape(title).strip()
            url = unescape(match.group("url")).strip()
            if not title or not url.startswith("http"):
                continue
            results.append({"title": title, "url": url})
        return results

    async def _generate_queries(self, case_number: str, hints: list[str]) -> list[str]:
        payload = await self.llm_client.generate_json(
            system_prompt=(
                "You generate web search queries for Nepali corruption-case news discovery. "
                "Return JSON with a `queries` array only. Queries must be high-recall, non-redundant, "
                "and suitable for general web search engines. Prefer Nepali and English query variants when useful."
            ),
            user_prompt=(
                f"Case number: {case_number}\n"
                f"Hints: {json.dumps(hints, ensure_ascii=False)}\n\n"
                "Generate 4 to 8 search queries that maximize the chance of finding relevant news coverage. "
                "Include the case number in some queries, but do not rely on it exclusively because news reports may omit it. "
                "Use likely allegations, institutions, accused names, locations, and Nepali transliterations when hinted."
            ),
        )
        queries = payload.get("queries")
        if not isinstance(queries, list):
            raise RuntimeError("LLM news search planner must return a `queries` array.")
        normalized_queries: list[str] = []
        seen: set[str] = set()
        for query in queries:
            if not isinstance(query, str):
                continue
            cleaned = query.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized_queries.append(cleaned)
        if not normalized_queries:
            raise RuntimeError(f"LLM did not generate usable news queries for {case_number}")
        return normalized_queries[:8]

    async def _rank_candidates(
        self,
        *,
        case_number: str,
        hints: list[str],
        candidates: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        payload = await self.llm_client.generate_json(
            system_prompt=(
                "You select the most relevant news results for a Nepali corruption case. "
                "Return JSON with a `selected_urls` array only. Choose URLs that are most likely to discuss the same case, "
                "not generic corruption coverage."
            ),
            user_prompt=(
                f"Case number: {case_number}\n"
                f"Hints: {json.dumps(hints, ensure_ascii=False)}\n"
                f"Max selections: {self.article_limit}\n\n"
                "Candidate search results:\n"
                f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n\n"
                "Select up to the max number of URLs that are most likely directly relevant to this case."
            ),
        )
        selected_urls = payload.get("selected_urls")
        if not isinstance(selected_urls, list):
            raise RuntimeError("LLM news ranker must return a `selected_urls` array.")
        selected_lookup = {
            url.strip()
            for url in selected_urls
            if isinstance(url, str) and url.strip()
        }
        ranked_results = [
            candidate for candidate in candidates if candidate["url"] in selected_lookup
        ]
        return ranked_results[: self.article_limit]

    async def search(self, case_number: str, hints: list[str]) -> list[dict[str, str]]:
        hint_values = [hint.strip() for hint in hints if hint and hint.strip()]
        queries = await self._generate_queries(case_number, hint_values)
        unique_results: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for query in queries:
                url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
                response = await client.get(url, headers={"User-Agent": USER_AGENT})
                if not response.is_success:
                    logger.warning(
                        "News search request failed for %s query=%s status=%s",
                        case_number,
                        query,
                        response.status_code,
                    )
                    continue
                for result in self._extract_candidates(response.text):
                    result_url = result["url"]
                    if result_url in seen_urls:
                        continue
                    seen_urls.add(result_url)
                    unique_results.append(result)
        if not unique_results:
            logger.warning("No news search results found for %s using LLM-generated queries", case_number)
            return []
        ranked_results = await self._rank_candidates(
            case_number=case_number,
            hints=hint_values,
            candidates=unique_results,
        )
        if ranked_results:
            return ranked_results
        logger.warning(
            "LLM news ranker did not select any results for %s; falling back to first %s candidates",
            case_number,
            self.article_limit,
        )
        return unique_results[: self.article_limit]


class LLMClient:
    def __init__(self, *, api_key: str, model: str, base_url: str | None = None) -> None:
        self.model = model
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        response = await self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
            text={"format": {"type": "json_object"}},
        )
        text = response.output_text.strip()
        if not text:
            raise RuntimeError("LLM returned empty output")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM did not return valid JSON: {text}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("LLM JSON response must be an object")
        return payload
