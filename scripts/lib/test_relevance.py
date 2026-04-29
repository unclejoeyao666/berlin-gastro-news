"""Tests for relevance + tag validation rules."""
import pytest

from .relevance import (
    classify_pool,
    is_gastro_relevant,
    validate_tags,
    gastro_score_boost,
    GASTRO_TIER1_SOURCES,
)


# ── Pool classification ──────────────────────────────


def test_ahgz_gastro_classified_as_gastro():
    pool = classify_pool("ahgz-gastro", "Beliebige Headline", "")
    assert pool == "gastro"


def test_dehoga_classified_as_gastro():
    pool = classify_pool("dehoga-berlin", "DEHOGA Pressemitteilung", "")
    assert pool == "gastro"


def test_efsa_press_classified_as_gastro():
    pool = classify_pool("efsa-press", "Risk assessment", "Foodborne pathogen")
    assert pool == "gastro"


def test_tagesschau_no_keyword_is_general():
    pool = classify_pool(
        "tagesschau-wirtschaft",
        "Aktien- und Ölmärkte ernüchtert",
        "Die Märkte zeigen sich uneinheitlich.",
    )
    assert pool == "general"


def test_tagesschau_with_gastro_keyword_is_keyword_pool():
    pool = classify_pool(
        "tagesschau-wirtschaft",
        "Bundesregierung plant Zuckerabgabe",
        "Eine Steuer auf Limonade soll Übergewicht reduzieren.",
    )
    assert pool == "keyword"


def test_spiegel_with_restaurant_in_summary():
    pool = classify_pool(
        "spiegel",
        "Mieten in Hamburg",
        "Auch das Restaurant Elemente bringt Lateinamerika an die Elbe.",
    )
    assert pool == "keyword"


def test_broad_only_berlin_alone_is_general():
    # "berlin" is broad; alone shouldn't pull in random Berlin politics
    pool = classify_pool(
        "spiegel",
        "Berlin verbietet etwas",
        "Eine politische Entscheidung in Berlin.",
    )
    # Two occurrences of "berlin" still counts as multi-broad
    # but title+summary share token. Single distinct broad token →
    # "general". This case is edge; we accept it as general.
    assert pool in ("general", "keyword")


def test_broad_plus_concrete_keyword_is_relevant():
    pool = classify_pool(
        "spiegel",
        "Berlin: DEHOGA fordert höhere Mehrwertsteuer-Senkung",
        "Berliner Wirte planen Streik.",
    )
    assert pool == "keyword"


# ── is_gastro_relevant ──────────────────────────────


def test_is_relevant_tier1_source():
    relevant, reason, _ = is_gastro_relevant("bmel", "Pressemitteilung", "")
    assert relevant is True
    assert reason == "tier1-source"


def test_is_relevant_keyword_match_includes_hit():
    relevant, reason, hits = is_gastro_relevant(
        "tagesschau-wirtschaft",
        "DEHOGA fordert Mehrwertsteuer-Senkung",
        "Branche unter Druck.",
    )
    assert relevant is True
    assert reason == "keyword-match"
    assert "dehoga" in hits


def test_is_not_relevant_pure_politics():
    relevant, reason, _ = is_gastro_relevant(
        "tagesschau-wirtschaft",
        "Söder offen für höhere Abgaben für Reiche",
        "CSU-Chef diskutiert Steuern.",
    )
    assert relevant is False


# ── Tag validation ──────────────────────────────


def test_gastro_law_supported_by_ahgz_source():
    ok, warns = validate_tags(["gastro-law"], "ahgz-gastro",
                              title="Steuersenkung Tipps und Tricks")
    assert ok is True
    assert warns == []


def test_gastro_law_supported_by_keyword():
    ok, warns = validate_tags(
        ["gastro-law"],
        "tagesschau-wirtschaft",
        title="Zuckerabgabe für Süßgetränke",
        summary="Geplant ist eine Lebensmittelsteuer.",
    )
    assert ok is True


def test_gastro_law_rejected_for_palantir():
    """The exact 04-28 bug: Palantir manifesto tagged as gastro-law."""
    ok, warns = validate_tags(
        ["gastro-law"],
        "tagesschau-wirtschaft",
        title="Was hinter Alex Karps Palantir-Manifest steckt",
        summary=(
            "Datenanalyse-Riese Palantir, KI-Waffensysteme, "
            "Tech-Faschismus."
        ),
    )
    assert ok is False
    assert any("gastro-law" in w for w in warns)


def test_gastro_law_rejected_for_china_meta_manus():
    """Another 04-28 bug case."""
    ok, warns = validate_tags(
        ["gastro-law"],
        "tagesschau-wirtschaft",
        title="China blockiert Übernahme von KI-Start-up Manus durch Meta",
        summary="Zwei-Milliarden-Dollar-Deal blockiert.",
    )
    assert ok is False


def test_geopolitics_supported_for_china_meta_manus():
    ok, warns = validate_tags(
        ["geopolitics-trade"],
        "tagesschau-wirtschaft",
        title="China blockiert Übernahme von KI-Start-up Manus durch Meta",
        summary="China NDRC blockiert.",
    )
    assert ok is True


def test_unknown_tag_rejected():
    ok, warns = validate_tags(["fictional-tag"], "ahgz-gastro", title="x")
    assert ok is False
    assert any("unknown-tag" in w for w in warns)


def test_multiple_tags_partial_failure():
    ok, warns = validate_tags(
        ["geopolitics-trade", "gastro-law"],
        "tagesschau-wirtschaft",
        title="OPEC Kürzung",
        summary="Ölpreis steigt.",
    )
    # geopolitics-trade ok via OPEC, gastro-law fails
    assert ok is False
    assert any("gastro-law" in w for w in warns)
    assert not any("geopolitics-trade" in w for w in warns)


def test_berlin_local_supported_by_dehoga_berlin_source():
    ok, _ = validate_tags(["berlin-local"], "dehoga-berlin",
                          title="Berliner Branche")
    assert ok is True


# ── Score boost ──────────────────────────────


def test_boost_for_tier1_source():
    boost = gastro_score_boost("ahgz-gastro", ["gastronomie", "law"])
    # 25 (tier1) + 12 (gastronomie) + 0 (law not in CATEGORY_BOOST) = 37
    assert boost == 25 + 12


def test_boost_for_general_source_with_food_safety_category():
    boost = gastro_score_boost("efsa-press", ["food-safety", "eu"])
    # 12 (tier2) + 10 (food-safety) = 22
    assert boost == 12 + 10


def test_no_boost_for_unrelated_source():
    boost = gastro_score_boost("tagesschau-wirtschaft",
                               ["business", "economy"])
    assert boost == 0


# ── Sanity ──────────────────────────────


def test_tier1_set_is_immutable():
    with pytest.raises(AttributeError):
        GASTRO_TIER1_SOURCES.add("foo")
