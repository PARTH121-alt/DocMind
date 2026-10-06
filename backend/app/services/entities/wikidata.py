"""Wikidata entity lookups.

Wikidata gives typed, structured facts about real-world entities (people,
countries, companies, species, languages...) with no API key, which makes it a
good fit for "tell me about X" style questions. Values arrive as typed
datavalues - entity references, quantities, dates or strings - so each is
rendered to something readable and, where relevant, hyperlinked.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

UA = "Origin/1.0 (https://github.com/PARTH121-alt/DocMind; document Q&A assistant)"
API = "https://www.wikidata.org/w/api.php"
ENTITY_API = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

# ---------------------------------------------------------------------------
# Throttling and caching
# ---------------------------------------------------------------------------
# Wikimedia throttles unauthenticated clients hard and will drop connections
# when a client hammers it. Every request therefore passes through a
# serialising minimum-interval throttle plus an in-process TTL cache. Both are
# per worker; use a shared cache when running multiple workers.
_throttle_lock = threading.Lock()
_last_request_at = 0.0
_cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str):
    ttl = settings.wikidata_cache_ttl_s
    if not ttl:
        return None
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.time() - stored_at > ttl:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return value


def _cache_put(key: str, value) -> None:
    limit = settings.wikidata_cache_max
    if not limit:
        return
    with _cache_lock:
        _cache[key] = (time.time(), value)
        _cache.move_to_end(key)
        while len(_cache) > limit:
            _cache.popitem(last=False)


def _throttled_get(url: str, params: dict, timeout: float | None = None):
    """GET with a global minimum interval between Wikimedia requests."""
    global _last_request_at

    interval = (settings.wikidata_min_interval_ms or 0) / 1000.0
    with _throttle_lock:
        wait = interval - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()

    response = httpx.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=timeout or settings.wikidata_timeout_s,
    )
    response.raise_for_status()
    return response

# Properties rendered as readable facts, in display order.
# (property id, label, formatter)
FACT_SPECS: list[tuple[str, str, str]] = [
    ("P36", "Capital", "entity"),
    ("P37", "Official language", "entity"),
    ("P38", "Official language", "entity"),
    ("P47", "Shares border with", "entity"),
    ("P30", "Continent", "entity"),
    ("P131", "Located in", "entity"),
    ("P17", "Country", "entity"),
    ("P1082", "Population", "number"),
    ("P2046", "Area", "area"),
    ("P1083", "Source code", "plain"),
    ("P112", "Founded by", "entity"),
    ("P169", "Chief executive", "entity"),
    ("P1037", "Director", "entity"),
    ("P170", "Creator", "entity"),
    ("P178", "Developer", "entity"),
    ("P400", "Platform", "entity"),
    ("P1416", "Affiliation", "entity"),
    ("P277", "Programming language", "entity"),
    ("P31", "Instance of", "entity"),
    ("P279", "Subclass of", "entity"),
    ("P106", "Occupation", "entity"),
    ("P569", "Born", "date"),
    ("P570", "Died", "date"),
    ("P19", "Place of birth", "entity"),
    ("P27", "Citizenship", "entity"),
    ("P54", "Member of", "entity"),
    ("P488", "Chairperson", "entity"),
    ("P1454", "Legal form", "entity"),
    ("P159", "Headquarters", "entity"),
    ("P452", "Industry", "entity"),
    ("P740", "Location of formation", "entity"),
    ("P17x", "", ""),  # placeholder removed at load time
]
FACT_SPECS = [s for s in FACT_SPECS if s[0] != "P17x"]

# Properties that accumulate a value per date/census; show only the best one.
SINGLE_VALUE_PREFER_TOP = {"P1082", "P2046", "P571", "P576", "P569", "P570"}

# Preferred properties per label, so "Official language" prefers P37 over P38.
PRIMARY_FOR_LABEL: dict[str, str] = {
    "Official language": "P37",
}


@dataclass
class EntityFact:
    label: str
    value: str
    property_id: str = ""
    entity_ids: list[str] = field(default_factory=list)
    url: str | None = None


@dataclass
class EntityCard:
    qid: str
    label: str
    description: str = ""
    facts: list[EntityFact] = field(default_factory=list)
    wikipedia_url: str | None = None
    image: str | None = None
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "label": self.label,
            "description": self.description,
            "wikipedia_url": self.wikipedia_url,
            "image": self.image,
            "aliases": self.aliases[:5],
            "facts": [
                {
                    "label": f.label,
                    "value": f.value,
                    "entity_ids": f.entity_ids[:8],
                    "url": f.url,
                }
                for f in self.facts
            ],
        }

    def fact(self, label: str) -> EntityFact | None:
        for f in self.facts:
            if f.label.lower() == label.lower():
                return f
        return None

    def lead_in(self, property_label: str = "") -> str:
        """A short, direct sentence; the card carries the full structure.

        When the question named a property ("capital of France") the answer
        leads with exactly that value, which is what the reader asked for.
        """
        if property_label:
            fact = self.fact(property_label)
            if fact:
                return f"The {property_label.lower()} of **{self.label}** is **{fact.value}**."
            # Property was asked for but is not in this entity's fact set.
            if self.facts:
                names = ", ".join(f.label.lower() for f in self.facts[:4])
                return (
                    f"Wikidata has no {property_label.lower()} recorded for "
                    f"**{self.label}**. It does record: {names}."
                )
        if self.description:
            return f"**{self.label}** - {self.description}."
        return f"**{self.label}**"

    def to_markdown(self) -> str:
        """Full table fallback, used when the card UI is unavailable."""
        lines = [self.lead_in(), ""]
        lines += ["| Property | Value |", "| --- | --- |"]
        for fact in self.facts:
            lines.append(f"| {fact.label} | {fact.value} |")
        if self.wikipedia_url:
            lines += ["", f"Source: Wikidata {self.qid} - {self.wikipedia_url}"]
        return "\n".join(lines)


def _fmt_number(amount: str) -> str:
    try:
        return f"{int(float(amount)):,}"
    except (TypeError, ValueError):
        return amount


def _fmt_date(value: dict) -> str:
    raw = value.get("time", "")
    m = re.match(r"^([+-])(\d{4,})-(\d{2})-(\d{2})", raw or "")
    if not m:
        return raw
    sign, year, month, day = m.groups()
    year = year.lstrip("+").lstrip("0") or "0"
    # Wikidata time precision: 11 = day, 10 = month, 9 = year, 8 = decade,
    # 7 = century. Anything coarser is approximate.
    precision = value.get("precision", 11)
    era = " BC" if sign == "-" else ""
    if precision <= 7:
        return f"{year}s{era}" if sign == "+" else f"{year} BC"
    if precision == 8:
        return f"{year[:3]}0s{era}"
    if precision == 9:
        return f"{year}{era}"
    if precision == 10:
        return f"{int(month)}/{year}{era}"
    return f"{int(day)}/{int(month)}/{year}{era}"


def _fmt_area(value: dict) -> str:
    amount = _fmt_number(value.get("amount", ""))
    unit_url = value.get("unit", "")
    # Q712226 is square kilometre, Q1618220 square mile.
    if "Q712226" in unit_url:
        return f"{amount} km²"
    if "Q1618220" in unit_url:
        return f"{amount} mi²"
    return amount


def _render_value(raw, kind: str) -> tuple[str, list[str], str | None]:
    """Return (text, referenced entity ids, url) for a datavalue."""
    if raw is None:
        return ("", [], None)
    if isinstance(raw, dict):
        if "id" in raw:  # entity reference
            return ("", [raw["id"]], f"https://www.wikidata.org/wiki/{raw['id']}")
        if "amount" in raw:
            return (_fmt_area(raw) if kind == "area" else _fmt_number(raw["amount"]), [], None)
        if "time" in raw:
            return (_fmt_date(raw), [], None)
        if "text" in raw:
            return (str(raw["text"]), [], None)
        return (str(raw), [], None)
    return (str(raw), [], None)


# Wikidata ranks a claim as "preferred" | "normal" | "deprecated".
_RANK_ORDER = {"preferred": 3, "normal": 2, "deprecated": 1}


def _by_preference(claims: list[dict]) -> list[dict]:
    """Sort claims so the best-supported one comes first."""
    return sorted(
        claims,
        key=lambda c: -_RANK_ORDER.get(str(c.get("rank", "normal")).lower(), 0),
    )


def _labels_for(ids: list[str]) -> dict[str, str]:
    """Resolve entity/property ids to English labels, one batched request."""
    ids = [i for i in ids if i]
    out: dict[str, str] = {}
    for start in range(0, len(ids), 50):
        batch = ids[start : start + 50]
        cache_key = "labels:" + "|".join(sorted(batch))
        cached = _cache_get(cache_key)
        if isinstance(cached, dict):
            out.update(cached)
            continue
        try:
            response = _throttled_get(
                API,
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels",
                    "languages": "en",
                    "format": "json",
                },
            )
            resolved = {
                key: entity.get("labels", {}).get("en", {}).get("value", key)
                for key, entity in response.json().get("entities", {}).items()
            }
            _cache_put(cache_key, resolved)
            out.update(resolved)
        except Exception as exc:
            logger.debug("label batch failed: %s", exc)
            for key in batch:
                out.setdefault(key, key)
    return out


def search_entity(name: str, language: str = "en") -> dict | None:
    """Find the best matching Wikidata item for a name."""
    if not name.strip():
        return None

    cache_key = f"search:{language}:{name.strip().lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        response = _throttled_get(
            API,
            {
                "action": "wbsearchentities",
                "search": name,
                "language": language,
                "uselang": language,
                "format": "json",
                "limit": 1,
                "type": "item",
            },
        )
        results = response.json().get("search") or []
    except Exception as exc:
        logger.info("wikidata search failed for %r: %s", name, exc)
        return None

    hit = results[0] if results else None
    _cache_put(cache_key, hit)
    return hit


def get_entity(qid: str, wanted_properties: list[str] | None = None) -> EntityCard | None:
    """Fetch an entity and render the configured facts."""
    cache_key = f"entity:{qid}"
    cached = _cache_get(cache_key)
    if isinstance(cached, dict):
        entity = cached
    else:
        try:
            response = _throttled_get(ENTITY_API.format(qid), {})
            entity = response.json()["entities"][qid]
            _cache_put(cache_key, entity)
        except Exception as exc:
            logger.info("wikidata fetch failed for %s: %s", qid, exc)
            return None

    label = entity.get("labels", {}).get("en", {}).get("value", qid)
    description = entity.get("descriptions", {}).get("en", {}).get("value", "")

    sitelink = entity.get("sitelinks", {}).get("enwiki", {})
    wikipedia_url = (
        f"https://en.wikipedia.org/wiki/{sitelink['title'].replace(' ', '_')}"
        if sitelink.get("title")
        else None
    )

    image = None
    p18 = entity.get("claims", {}).get("P18")
    if p18:
        raw = p18[0]["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(raw, str):
            # Without ?width= Special:FilePath serves the full-size original,
            # which for photographs is many megabytes.
            image = (
                "https://commons.wikimedia.org/wiki/Special:FilePath/"
                + raw.replace(" ", "_")
                + "?width=240"
            )

    aliases = [
        a["value"]
        for a in entity.get("aliases", {}).get("en", [])[:5]
    ]

    wanted = wanted_properties or [spec[0] for spec in FACT_SPECS]
    facts: list[EntityFact] = []
    referenced: list[str] = []

    # Collect every referenced entity id first so labels resolve in one batch.
    for prop in wanted:
        for claim in entity.get("claims", {}).get(prop, [])[:40]:
            raw = claim["mainsnak"].get("datavalue", {}).get("value")
            _, ids, _ = _render_value(raw, "entity")
            referenced.extend(ids)
    prop_labels = _labels_for([p for p in wanted])
    referenced_labels = _labels_for(sorted(set(referenced)))

    used_labels: set[str] = set()
    for prop, prop_label, kind in FACT_SPECS:
        if prop not in wanted:
            continue
        # Skip a secondary property when the primary one already answered it.
        if PRIMARY_FOR_LABEL.get(prop_label) and prop != PRIMARY_FOR_LABEL[prop_label]:
            continue
        if prop_label in used_labels:
            continue

        claims = _by_preference(entity.get("claims", {}).get(prop, []))
        # Population-like properties carry one claim per census; the best
        # ranked one is the current estimate, so do not list them all.
        limit = 1 if prop in SINGLE_VALUE_PREFER_TOP else 3
        if kind == "entity":
            # Historical/former values usually sit at "normal" rank. Prefer
            # only the "preferred" ones, falling back to normal if there are none.
            good = [c for c in claims if str(c.get("rank", "normal")).lower() == "preferred"]
            claims = good or [c for c in claims if str(c.get("rank", "normal")).lower() == "normal"]

        rendered: list[str] = []
        ids: list[str] = []
        url: str | None = None
        for claim in claims[:limit]:
            raw = claim["mainsnak"].get("datavalue", {}).get("value")
            text, ref_ids, ref_url = _render_value(raw, kind)
            if not text and ref_ids:
                # An entity reference: show its label, not its Q-id.
                text = ", ".join(
                    referenced_labels.get(i, i) for i in ref_ids[:4]
                )
            if text:
                rendered.append(text)
                url = url or ref_url
            ids.extend(ref_ids)
        if not rendered:
            continue

        used_labels.add(prop_label)
        facts.append(
            EntityFact(
                label=prop_label or prop_labels.get(prop, prop),
                value=", ".join(rendered),
                property_id=prop,
                entity_ids=[i for i in ids if i in referenced_labels],
                url=url,
            )
        )

    # A country entity that lists itself under "Country" adds nothing.
    facts = [
        f
        for f in facts
        if not (f.property_id == "P17" and f.value.strip().lower() == label.strip().lower())
    ]

    return EntityCard(
        qid=qid,
        label=label,
        description=description,
        facts=facts,
        wikipedia_url=wikipedia_url,
        image=image,
        aliases=aliases,
    )
