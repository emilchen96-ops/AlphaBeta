"""N01 manual and RSS/Atom adapters with deterministic fixture parsing."""

from __future__ import annotations

import asyncio
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol, cast
from urllib.parse import urlparse

from alphadesk_domain.information import (
    InformationError,
    InformationSource,
    InformationSourceType,
    RawDocumentDraft,
)

type RssFetcher = Callable[[str, float, int], Awaitable[bytes]]


class InformationSourceAdapter(Protocol):
    async def fetch(self, source: InformationSource) -> list[RawDocumentDraft]: ...


class ManualInformationAdapter:
    def create(
        self,
        *,
        title: str,
        content: str,
        source_url: str | None,
        published_at: datetime | None,
    ) -> RawDocumentDraft:
        return RawDocumentDraft(
            title=title,
            content=content,
            source_url=source_url,
            published_at=published_at,
            metadata={"input_type": "MANUAL"},
        )

    async def fetch(self, source: InformationSource) -> list[RawDocumentDraft]:
        del source
        raise InformationError("INFORMATION_MANUAL_FETCH_UNSUPPORTED", "manual input is push-only")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, *names: str) -> str | None:
    wanted = set(names)
    for child in node:
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return None


def _clean_markup(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class RSSInformationAdapter:
    def __init__(
        self,
        fetcher: RssFetcher | None = None,
        *,
        timeout_seconds: float = 10,
        max_bytes: int = 2_000_000,
    ) -> None:
        self._fetcher = fetcher or _fetch_url
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    async def fetch(self, source: InformationSource) -> list[RawDocumentDraft]:
        if source.source_type is not InformationSourceType.RSS or not source.base_url:
            raise InformationError("INFORMATION_SOURCE_NOT_RSS", "source is not an RSS feed")
        try:
            async with asyncio.timeout(self._timeout + 1):
                payload = await self._fetcher(source.base_url, self._timeout, self._max_bytes)
            return self.parse(payload)
        except InformationError:
            raise
        except (OSError, TimeoutError, ET.ParseError) as exc:
            raise InformationError("INFORMATION_RSS_FETCH_FAILED", "RSS ingestion failed") from exc

    @staticmethod
    def parse(payload: bytes) -> list[RawDocumentDraft]:
        root = ET.fromstring(payload)
        nodes = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
        drafts: list[RawDocumentDraft] = []
        for node in nodes:
            title = _child_text(node, "title")
            content = _child_text(node, "content", "description", "summary")
            if not title or not content:
                continue
            link = _child_text(node, "link")
            if link is None:
                for child in node:
                    if _local_name(child.tag) == "link" and child.attrib.get("href"):
                        link = child.attrib["href"]
                        break
            drafts.append(
                RawDocumentDraft(
                    title=_clean_markup(title),
                    content=_clean_markup(content),
                    external_id=_child_text(node, "guid", "id"),
                    source_url=link,
                    published_at=_date(_child_text(node, "pubdate", "published", "updated")),
                    metadata={"input_type": "RSS"},
                )
            )
        return drafts


async def _fetch_url(url: str, timeout_seconds: float, max_bytes: int) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InformationError("INFORMATION_RSS_URL_INVALID", "RSS URL must use HTTP or HTTPS")

    def read() -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "AlphaDesk-N01/1.0"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = cast(bytes, response.read(max_bytes + 1))
        if len(payload) > max_bytes:
            raise InformationError("INFORMATION_RSS_TOO_LARGE", "RSS payload is too large")
        return payload

    return await asyncio.to_thread(read)
