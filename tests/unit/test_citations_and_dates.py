import json
from datetime import date
from pathlib import Path

import pytest

from eli_legal.legal.citations import CitationExtractor, normalise_citation
from eli_legal.legal.dates import find_dates, split_sentences
from eli_legal.legal.jurisdictions import JurisdictionRegistry
from eli_legal.settings import Settings

PACK_DIR = Settings(_env_file=None).jurisdictions_dir
REGISTRY = JurisdictionRegistry.from_dir(PACK_DIR)


def _examples() -> list[tuple[str, str, str]]:
    out = []
    for path in sorted(Path(PACK_DIR).glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        out += [(raw["code"], p["id"], p["example"]) for p in raw["citation_patterns"]]
    return out


@pytest.mark.parametrize(("code", "pattern_id", "example"), _examples())
def test_every_pack_recognises_its_own_example_citation(code, pattern_id, example):
    matches = CitationExtractor([REGISTRY.get(code)]).extract(f"See {example} on this point.")
    assert any(m.pattern_id == pattern_id and m.raw == example for m in matches), matches


def test_packs_cover_common_law_civil_law_supranational_and_international():
    families = {REGISTRY.get(c).legal_family for c in REGISTRY.codes()}
    assert {"common_law", "civil_law", "supranational", "international"} <= families


def test_no_shipped_pack_claims_to_be_validated_or_to_contain_rules_of_law():
    for code in REGISTRY.codes():
        pack = REGISTRY.get(code)
        assert not pack.validated, f"{code} must be validated by a qualified lawyer, not by us"
        assert pack.pack_status in {"structural", "fallback"}


def test_unknown_jurisdiction_falls_back_to_the_generic_pack():
    assert REGISTRY.get("ZZ").pack_status == "fallback"


def test_citation_keys_ignore_spacing_case_and_reporter_full_stops():
    assert normalise_citation("[2010] 2 I.R. 123") == normalise_citation("[2010]  2 ir 123")
    assert normalise_citation("Regulation (EC) No 44/2001") == "regulation (ec) 44/2001"
    assert normalise_citation("Case C‑311/18") == "c-311/18"


def test_statute_titles_drop_leading_words_and_reject_non_titles():
    extractor = CitationExtractor([REGISTRY.get("IE")])
    text = "Under the Arbitration Act 2010 and, in March, the Act 2010 as amended."
    assert [m.raw for m in extractor.extract(text)] == ["Arbitration Act 2010"]


def test_dates_in_several_conventions_and_languages():
    found = {
        d.text: d
        for d in find_dates("3rd March 2021; March 5, 2021; 2021-04-01; 12 mars 2020; 14.02.2019")
    }
    assert found["3rd March 2021"].value == date(2021, 3, 3)
    assert found["March 5, 2021"].value == date(2021, 3, 5)
    assert found["12 mars 2020"].value == date(2020, 3, 12)
    assert found["14.02.2019"].value == date(2019, 2, 14)


def test_ambiguous_numeric_date_follows_the_jurisdiction_and_is_flagged():
    day_first = find_dates("03/04/2021", date_order="dmy")[0]
    month_first = find_dates("03/04/2021", date_order="mdy")[0]
    assert (day_first.value, day_first.ambiguous) == (date(2021, 4, 3), True)
    assert month_first.value == date(2021, 3, 4)
    assert not find_dates("25/04/2021")[0].ambiguous


def test_sentence_splitting_survives_legal_abbreviations():
    text = (
        "Mr. Smith paid Acme Ltd. on 3 March 2021. See Smith v. Jones [2019] IESC 12. It was late."
    )
    assert split_sentences(text) == [
        "Mr. Smith paid Acme Ltd. on 3 March 2021.",
        "See Smith v. Jones [2019] IESC 12.",
        "It was late.",
    ]
