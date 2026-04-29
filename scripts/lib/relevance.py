"""Relevance + tag semantic helpers for Berlin Gastro News selection.

Keeps the editorial line:
- Tier-1 gastro sources (AHGZ, DEHOGA, BMEL) always count as gastro.
- Generic-source articles count only if title+summary trip a German/English
  keyword matcher.
- Tag/content semantic validation rejects clearly off-topic tag picks
  (e.g. ``gastro-law`` on a story about international AI M&A).
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple


# ── Source pools ────────────────────────────────────────────────

GASTRO_TIER1_SOURCES = frozenset({
    "ahgz-gastro",
    "ahgz-all",
    "ahgz-suppliers",
    "dehoga-berlin",
    "bmel",
})

GASTRO_TIER2_SOURCES = frozenset({
    "efsa-press",
    "ec-press",
})


# ── Keyword sets ────────────────────────────────────────────────
# Lower-cased; matched as case-insensitive substrings with simple word
# boundaries where helpful.

GASTRO_KEYWORDS_DE = (
    # Establishment & roles
    "restaurant", "café", "cafe", "gaststätte", "gaststaette", "gaststätten",
    "gastronomie", "gastgewerbe", "wirt", "wirtshaus", "kneipe", "biergarten",
    "imbiss", "lokal", "schenke", "kantine", "mensa", "betriebsgastronomie",
    "bäcker", "baecker", "bäckerei", "metzger", "fleischer", "konditorei",
    "brauerei", "brauer",
    # Hotellerie
    "hotel", "hotellerie", "hotelgewerbe", "beherbergung",
    "tourismus", "tourist",
    # Food chain
    "lebensmittel", "lebensmittelhandel", "supermarkt", "discounter",
    "speisen", "getränke", "getraenke", "wein", "bier", "alkohol",
    "ernährung", "ernaehrung", "küche", "kueche",
    # Industry orgs / regulation
    "dehoga", "iha", "ahgz",
    "mehrwertsteuer", "vat", "umsatzsteuer", "gewerbesteuer",
    "mindestlohn", "tarifvertrag",
    "hygiene", "lebensmittelhygiene", "lebensmittelsicherheit",
    "tierhaltungskennzeichnung", "lebensmittelrecht", "gaststättengesetz",
    "zuckersteuer", "zuckerabgabe",
    # Berlin local hooks
    "berlin", "spreewald", "brandenburg",
)

GASTRO_KEYWORDS_EN = (
    "restaurant", "cafe", "café", "hotel", "hospitality", "gastronomy",
    "catering", "food service", "minimum wage", "vat",
    "dehoga", "berlin", "beverage", "brewery", "canteen",
    "food safety", "food hygiene", "food regulation",
)

# Generic German/English tokens that, by themselves, are too broad to
# count as gastro relevance. Always require at least one *non*-broad
# keyword in addition to these.
GASTRO_BROAD_TOKENS = frozenset({
    "berlin", "lebensmittel", "tourismus",
})


def _has_keyword(text: str, keywords: Iterable[str]) -> List[str]:
    """Return matching keywords in ``text`` (case-insensitive)."""
    if not text:
        return []
    text_lower = text.lower()
    hits = []
    for kw in keywords:
        if kw in text_lower:
            hits.append(kw)
    return hits


def is_gastro_relevant(source_id: Optional[str],
                       title: str,
                       summary: str,
                       lang: str = "de") -> Tuple[bool, str, List[str]]:
    """Decide whether an article is gastro-relevant.

    Returns ``(relevant, reason, hits)``:
      - ``relevant=True`` if source is in the gastro pool, or if title /
        summary contain a non-broad gastro keyword, or contain a broad
        token together with another keyword.
      - ``reason`` is a short string explaining the decision.
      - ``hits`` is the list of matched keywords (may be empty).
    """
    if source_id and source_id in GASTRO_TIER1_SOURCES:
        return True, "tier1-source", []
    if source_id and source_id in GASTRO_TIER2_SOURCES:
        return True, "tier2-source", []

    text = f"{title or ''}\n{summary or ''}"
    keywords = GASTRO_KEYWORDS_DE if lang == "de" else GASTRO_KEYWORDS_EN
    hits = _has_keyword(text, keywords)
    if not hits:
        return False, "no-keyword-match", []
    non_broad = [h for h in hits if h not in GASTRO_BROAD_TOKENS]
    if non_broad:
        return True, "keyword-match", hits
    # Only broad tokens — needs at least 2 distinct broad tokens
    # OR co-occurrence with a category we trust. We keep the rule
    # strict: broad-only is not enough.
    if len(set(hits)) >= 2:
        return True, "multi-broad-token", hits
    return False, "broad-only", hits


def classify_pool(source_id: Optional[str],
                  title: str,
                  summary: str,
                  lang: str = "de") -> str:
    """Return ``"gastro"``, ``"keyword"`` or ``"general"`` for selection."""
    if source_id and source_id in GASTRO_TIER1_SOURCES:
        return "gastro"
    if source_id and source_id in GASTRO_TIER2_SOURCES:
        return "gastro"
    relevant, _, _ = is_gastro_relevant(source_id, title, summary, lang)
    return "keyword" if relevant else "general"


# ── Tag semantic rules ──────────────────────────────────────────

VALID_TAGS = frozenset({
    "gastro-law", "tax-finance", "labor-staffing", "energy-cost",
    "supply-food", "hygiene-safety", "digital-tech", "real-estate",
    "events-marketing", "trends-consumer", "geopolitics-trade",
    "berlin-local",
})


# Keyword regex (case-insensitive) per tag. A tag is "supported" if any
# regex matches the article text OR the source is in the tag's allowed
# sources. Conservative — most tags accept multiple cues.
TAG_RULES = {
    "gastro-law": {
        "patterns": [
            r"gaststätte", r"gaststaette", r"gaststättengesetz",
            r"hygieneverordnung", r"lebensmittelgesetz",
            r"lebensmittelrecht", r"gastronomie\w*\s*(steuer|recht|gesetz)",
            r"mehrwertsteuer.{0,30}(gastro|restaurant|speisen)",
            r"speisensteuer", r"zuckerabgabe", r"zuckersteuer",
            r"tierhaltungskennzeichnung",
            r"vat.{0,20}(restaurant|hospitality)",
        ],
        "sources": ["ahgz-gastro", "ahgz-all", "dehoga-berlin", "bmel"],
    },
    "tax-finance": {
        "patterns": [
            r"steuer", r"mehrwertsteuer", r"\bvat\b", r"umsatzsteuer",
            r"subvention", r"zuschuss", r"förderprogramm",
            r"gewerbesteuer", r"lohnsteuer", r"reichensteuer",
            r"finanz\w+", r"haushalt", r"sparpaket",
        ],
        "sources": [],
    },
    "labor-staffing": {
        "patterns": [
            r"mindestlohn", r"tarifvertrag", r"arbeitsmarkt",
            r"fachkräfte", r"fachkraefte", r"saisonkraft",
            r"arbeitskraft", r"einwanderung", r"migration\w*\s*arbeit",
            r"personalmangel", r"stellenabbau", r"kündigung",
            r"\bjob(s)?\b",
        ],
        "sources": [],
    },
    "energy-cost": {
        "patterns": [
            r"energie\w*", r"strom\w*", r"gas\w*preis", r"erdgas",
            r"heizung", r"benzin", r"diesel", r"kraftstoff",
            r"ölpreis", r"oelpreis", r"co2", r"emission",
            r"erneuerbar", r"solar", r"wind",
        ],
        "sources": [],
    },
    "supply-food": {
        "patterns": [
            r"lebensmittel", r"rohstoff", r"importe", r"export",
            r"butter", r"milch", r"käse", r"fleisch", r"fisch",
            r"getreide", r"gemüse", r"obst", r"zucker",
            r"agrar", r"landwirtschaft", r"erzeuger",
            r"supply.{0,5}chain", r"lieferkette",
        ],
        "sources": ["bmel"],
    },
    "hygiene-safety": {
        "patterns": [
            r"hygiene", r"lebensmittelsicherheit", r"food.{0,5}safety",
            r"keime", r"salmonell", r"listerien",
            r"rückruf", r"recall", r"kontamin",
            r"bse", r"vogelgrippe", r"schweinegrippe",
            r"\befsa\b", r"behörde.{0,30}gesundheit",
        ],
        "sources": ["bmel", "efsa-press"],
    },
    "digital-tech": {
        "patterns": [
            r"\bki\b", r"\bai\b", r"künstliche intelligenz",
            r"digital\w+", r"online.{0,5}(bestell|liefer)",
            r"saas", r"app", r"plattform", r"software",
            r"chatbot", r"reservierung\w*\s*system",
        ],
        "sources": [],
    },
    "real-estate": {
        "patterns": [
            r"immobilien", r"miete", r"pacht", r"gewerbe(miete|raum)",
            r"\bbau\w*", r"sanierung", r"leerstand",
            r"shopping.{0,5}mall", r"einzelhandel.{0,15}fläche",
        ],
        "sources": [],
    },
    "events-marketing": {
        "patterns": [
            r"event", r"festival", r"messe", r"kongress",
            r"marketing", r"kampagne", r"branding", r"werbung",
            r"pop.{0,3}up", r"opening", r"eröffnung",
        ],
        "sources": [],
    },
    "trends-consumer": {
        "patterns": [
            r"konsum\w*", r"verbraucher", r"trend",
            r"nachfrage", r"absatz", r"umsatz",
            r"preise", r"inflation", r"rezession",
            r"discounter", r"premium", r"bio",
        ],
        "sources": [],
    },
    "geopolitics-trade": {
        "patterns": [
            r"china", r"\busa\b", r"trump", r"zoll", r"tariff",
            r"sanktion", r"handelskrieg", r"handelsabkommen",
            r"\beu\b", r"brexit", r"iran", r"russland", r"ukraine",
            r"opec", r"weltwirtschaft", r"export.{0,10}beschränkung",
        ],
        "sources": ["scmp", "politico-eu", "euobserver", "dw-en", "dw-de"],
    },
    "berlin-local": {
        "patterns": [
            r"berlin", r"brandenburg", r"spree\w*", r"senat",
            r"bezirk", r"kreuzberg", r"mitte", r"prenzlauer",
            r"charlottenburg", r"neukölln", r"friedrichshain",
            r"\bber\b",  # BER airport
        ],
        "sources": ["dehoga-berlin"],
    },
}


def _compile_patterns(patterns: Iterable[str]) -> List[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_TAG_RE_CACHE: dict = {}


def _patterns_for(tag: str) -> List[re.Pattern]:
    if tag not in _TAG_RE_CACHE:
        rule = TAG_RULES.get(tag)
        _TAG_RE_CACHE[tag] = _compile_patterns(rule["patterns"]) if rule else []
    return _TAG_RE_CACHE[tag]


def validate_tags(tags: Sequence[str],
                  source_id: Optional[str],
                  title: str = "",
                  summary: str = "",
                  body: str = "") -> Tuple[bool, List[str]]:
    """Check that each tag is supported by content or source.

    Returns ``(ok, warnings)``. A tag is supported when:
      - it is in ``VALID_TAGS``, AND
      - source matches the tag's allowed sources, OR
      - any pattern matches title/summary/body, OR
      - the tag has no patterns / sources defined (open-tag fallback).
    """
    text = "\n".join(s for s in (title, summary, body) if s)
    warnings: List[str] = []
    for tag in tags:
        if tag not in VALID_TAGS:
            warnings.append(f"unknown-tag:{tag}")
            continue
        rule = TAG_RULES.get(tag)
        if not rule:
            continue  # tag has no constraint → accept
        if source_id and source_id in rule.get("sources", ()):
            continue
        patterns = _patterns_for(tag)
        if any(p.search(text) for p in patterns):
            continue
        warnings.append(
            f"tag-not-supported:{tag} (source={source_id or 'n/a'})"
        )
    return (not warnings), warnings


# ── Importance boost ────────────────────────────────────────────

CATEGORY_BOOST = {
    "gastronomie": 12,
    "hotellerie": 8,
    "food-safety": 10,
    "berlin": 10,
    "regulations": 4,
    "subsidies": 3,
}


def gastro_score_boost(source_id: Optional[str],
                       categories: Sequence[str]) -> int:
    """Return importance bonus to apply on top of the base score."""
    boost = 0
    if source_id in GASTRO_TIER1_SOURCES:
        boost += 25
    elif source_id in GASTRO_TIER2_SOURCES:
        boost += 12
    for c in categories:
        boost += CATEGORY_BOOST.get(c, 0)
    return boost
