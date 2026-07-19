from datetime import UTC, datetime
from decimal import Decimal

import pytest

from alphadesk_domain.information import (
    EventInstrumentLink,
    MarketEvent,
    MarketEventType,
    normalize_text,
    normalized_content_hash,
)
from alphadesk_domain.information_adapters import RSSInformationAdapter

RSS = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'><channel><title>Fixture</title>
<item><guid>news-1</guid><title> Company   News </title>
<link>https://example.test/1</link><pubDate>Fri, 17 Jul 2026 08:00:00 GMT</pubDate>
<description><![CDATA[<p>Important &amp; factual update.</p>]]></description></item>
</channel></rss>"""

ATOM = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'><entry><id>a-1</id><title>Atom title</title>
<link href='https://example.test/a'/><updated>2026-07-17T09:00:00Z</updated>
<summary>Atom content</summary></entry></feed>"""


def test_normalization_and_hash_are_stable() -> None:
    assert normalize_text("\uff21  \n B", "value") == "A B"
    assert normalized_content_hash("A  B", " C\nD ") == normalized_content_hash("A B", "C D")


def test_rss_and_atom_fixture_parsing() -> None:
    rss = RSSInformationAdapter.parse(RSS)[0]
    atom = RSSInformationAdapter.parse(ATOM)[0]
    assert rss.external_id == "news-1"
    assert rss.content == "Important & factual update."
    assert rss.published_at == datetime(2026, 7, 17, 8, tzinfo=UTC)
    assert atom.source_url == "https://example.test/a"
    assert atom.published_at == datetime(2026, 7, 17, 9, tzinfo=UTC)


def test_importance_and_confidence_reject_float_or_out_of_range() -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    with pytest.raises(ValueError, match="Decimal"):
        MarketEvent(
            information_item_id=__import__("uuid").uuid4(),
            event_type=MarketEventType.OTHER,
            title="event",
            event_at=now,
            importance=0.5,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="between"):
        EventInstrumentLink(
            event_id=__import__("uuid").uuid4(),
            instrument_id=__import__("uuid").uuid4(),
            confidence=Decimal("1.1"),
        )
