"""Searching by meaning, linking by meaning, and the benchmarks that measure them.

The embedding model here is a stand-in that maps words of the same meaning to the same
direction, so a test can say exactly which passages are close. No model file is needed."""

import json
import math
import re
from dataclasses import replace
from pathlib import Path

import pytest

from eli_legal.adapters.inference import embedding as embedding_mod
from eli_legal.adapters.inference.local import NullInference
from eli_legal.adapters.sources.local_corpus import LocalCorpusConnector, import_records
from eli_legal.cli import main
from eli_legal.domain.enums import ClaimKind
from eli_legal.domain.models import Claim, Issue, Run
from eli_legal.evaluation import linking, research
from eli_legal.legal.case_law_retriever import KEYWORD_TOOL, CaseLawRetriever
from eli_legal.legal.issue_mapper import IssueMapper
from eli_legal.legal.llm import LegalModel
from eli_legal.legal.semantic import WINDOW_CHARS, SemanticIndex, windows
from eli_legal.legal.source_registry import RegisteredSource
from eli_legal.persistence.sqlite import Store
from tests.conftest import case_text

SENSES = [
    {"accept", "accepted", "acceptance", "keep", "keeping", "kept", "retain", "retains"},
    {"reject", "rejection", "return", "back"},
    {"time", "late", "lateness", "delay", "punctual", "essence"},
    {"pay", "paid", "payment", "price", "invoice"},
    {"dismiss", "dismissed", "dismissal", "sacked", "fired", "job"},
    {"delete", "erase", "erasure", "forgotten", "remove"},
    {"ship", "ships", "vessel", "cargo"},
]


class Senses:
    """An embedding model in miniature: one direction per sense, words of a sense alike."""

    available = True
    reason = ""

    def __init__(self, model_id="senses@test"):
        self.model_id = model_id
        self.calls = 0

    def embed(self, texts, *, kind):
        self.calls += 1
        out = []
        for text in texts:
            words = re.findall(r"[a-z]+", text.lower())
            v = [sum(1.0 for w in words if w in sense) for sense in SENSES] + [0.05]
            norm = math.sqrt(sum(x * x for x in v))
            out.append([x / norm for x in v])
        return out


class Broken(Senses):
    def embed(self, texts, *, kind):
        raise RuntimeError("the model file is damaged")


SOURCE = RegisteredSource(
    source_id="corpus", name="Corpus", approved=True, jurisdictions=frozenset({"XX"})
)
RECORDS = [
    {"citation": "Sale Act 1979", "jurisdiction": "XX", "kind": "legislation", "passages": [
        {"locator": "s.35", "heading": "Acceptance.",
         "text": "(1) The buyer is deemed to have accepted the goods when, after a reasonable "
                 "time, he retains them without intimating that he has rejected them."},
        {"locator": "s.10", "heading": "Stipulations about time.",
         "text": "(1) Stipulations as to time of payment are not of the essence of a contract of "
                 "sale."},
        {"locator": "s.90", "heading": "Carriage by sea.",
         "text": "Goods carried in ships are at the risk of the owner of the cargo."},
    ]},
]  # fmt: skip


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "s.db")
    import_records(s, SOURCE, [(f"{n}.json", r) for n, r in enumerate(RECORDS)])
    return s


def _retriever(store, embedder=None, mode="hybrid"):
    semantic = SemanticIndex(store, embedder) if embedder else None
    if semantic:
        semantic.ensure(["corpus"])
    return CaseLawRetriever({"corpus": LocalCorpusConnector(store, SOURCE)}, semantic, mode)


QUERY = "Whether the purchaser could still send the items back, having kept the items for months"


def test_meaning_finds_a_provision_put_in_other_words(store):
    by_words = _retriever(store).search(jurisdictions=["XX"], query=QUERY)
    assert "s.35" not in [h.passage.locator for h in by_words], "no word of s.35 is asked"
    ranked = _retriever(store, Senses()).ranked(jurisdictions=["XX"], query=QUERY)
    assert ranked[0].hit.passage.locator == "s.35"
    assert ranked[0].found_by == "meaning"
    issue = Issue(matter_id="m", run_id="r", label=QUERY)
    [first, *_] = _retriever(store, Senses()).propositions_for_issue(
        matter_id="m", run_id="r", issue=issue, jurisdictions=["XX"]
    )
    assert first.evidence[0].locator == "s.35" and "found by meaning" in first.origin
    assert first.text in store.passages_for(first.authority_id)[0].text, "quoted word for word"


def test_without_a_model_research_ranks_by_words_and_says_so(store):
    retriever = _retriever(store, None)
    assert not retriever.by_meaning and retriever.method == KEYWORD_TOOL
    with_model = _retriever(store, Senses())
    assert with_model.method.startswith(f"{KEYWORD_TOOL}+meaning:senses@test;rrf/")


def test_vectors_are_kept_per_model_and_go_with_their_passage(store):
    index = SemanticIndex(store, Senses())
    first = index.ensure(["corpus"])
    assert (first.indexed_now, first.total, first.missing) == (3, 3, 0)
    assert index.ensure(["corpus"]).indexed_now == 0, "embedded once"
    assert SemanticIndex(store, Senses("other@test")).ensure(["corpus"]).indexed_now == 3
    import_records(store, SOURCE, [("0.json", RECORDS[0])])  # the act is replaced
    assert index.ensure(["corpus"]).indexed_now == 3, "a replaced passage loses its vectors"


def test_a_budget_leaves_the_rest_to_be_found_by_words(store):
    coverage = SemanticIndex(store, Senses()).ensure(["corpus"], budget=1)
    assert (coverage.indexed_now, coverage.missing, coverage.complete) == (1, 2, False)


def test_a_long_passage_is_embedded_in_windows_under_its_heading(store):
    [passage] = [p for p in store.passages_for(store.list_authorities()[0].authority_id)][:1]
    long = replace(passage, text=" ".join(["The buyer shall pay the price."] * 80))
    parts = windows(long)
    assert len(parts) > 2 and all(p.startswith("Acceptance.\n") for p in parts)
    assert all(len(p) <= WINDOW_CHARS + len("Acceptance.\n") for p in parts)


def test_an_embedding_model_is_never_asked_for_more_than_it_was_trained_on(tmp_path, monkeypatch):
    """A text longer than the model's positions stops llama.cpp, and the program with it."""
    seen = {}

    class Llama:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def embed(self, texts, truncate=True):
            return [[1.0, 0.0] for _ in texts]

    model = tmp_path / "bge-small-en-v1.5-f16.gguf"
    model.write_bytes(b"GGUF" + bytes(64))
    monkeypatch.setattr(embedding_mod.gpu_runtime, "llama", lambda: type("M", (), {"Llama": Llama}))
    for trained, expected in ((512, 512), (8192, 2048), (0, 512)):
        monkeypatch.setattr(embedding_mod.gguf_sizes, "trained_context", lambda p, t=trained: t)
        embedder = embedding_mod.GgufEmbedder(model)
        embedder.embed(["a passage"], kind="document")
        assert embedder.context == expected
        assert seen["n_ctx"] == seen["n_batch"] == seen["n_ubatch"] == expected
    assert embedding_mod.prefixes("nomic-embed-text-v1.5.Q4_K_M.gguf")[0] == "search_query: "
    assert embedding_mod.prefixes("bge-small-en-v1.5-f16.gguf")[0].startswith("Represent this")


def test_facts_are_linked_to_the_issue_they_mean_without_sharing_its_words():
    issues = [
        Issue(matter_id="m", run_id="r", label="Whether the employer lawfully fired her"),
        Issue(matter_id="m", run_id="r", label="Whether the invoice was settled late"),
    ]
    facts = [
        Claim(matter_id="m", run_id="r", text=t, kind=ClaimKind.FACT)
        for t in (
            "She was dismissed on 4 March.",
            "Her job ended without warning.",
            "The payment arrived after the due date.",
            "The office is in Examplia City.",
        )
    ]
    store = Store(":memory:")
    IssueMapper(LegalModel(NullInference()), semantic=SemanticIndex(store, Senses())).link_facts(
        issues=issues, facts=facts
    )
    fired, paid = issues[0].issue_id, issues[1].issue_id
    assert [f.issue_ids for f in facts] == [[fired], [fired], [paid], []]


def test_a_run_records_how_research_ranked_and_the_report_says_it(demo):
    sv, mid = demo
    sv.ctx.embedder = Senses()
    run = sv.runs.start(mid, actor_id="sec.byrne")
    stored = sv.ctx.store.get(Run, mid, run.run_id)
    assert stored.tool_versions["retrieval"].startswith(f"{KEYWORD_TOOL}+meaning:senses@test")
    assert stored.tool_versions["linking"].startswith("words+meaning:senses@test")
    warnings = sv.runs.summary(mid, run.run_id, actor_id="arb.keane")["report"]["warnings"]
    assert any(w.startswith("research_by_meaning:") and "senses" in w for w in warnings)


def test_a_model_that_fails_leaves_research_by_words_and_the_report_says_so(demo):
    sv, mid = demo
    sv.ctx.embedder = Broken()
    run = sv.runs.start(mid, actor_id="sec.byrne")
    stored = sv.ctx.store.get(Run, mid, run.run_id)
    assert stored.tool_versions["retrieval"] == KEYWORD_TOOL
    assert (
        "could not run (RuntimeError: the model file is damaged)"
        in (stored.tool_versions["retrieval_note"])
    )
    warnings = sv.runs.summary(mid, run.run_id, actor_id="arb.keane")["report"]["warnings"]
    assert any(w.startswith("research_by_words:") for w in warnings)
    assert any(w.startswith("research_partial:") for w in warnings)


def test_every_provision_in_the_research_benchmark_is_in_its_corpus():
    have = {
        research.provision(r["citation"], p["locator"])
        for r in research.corpus_records()
        for p in r["passages"]
    }
    cases = research.load_cases()
    assert len(cases) == 70
    for case in cases:
        assert any(g == 2 for g in case.relevant.values()), case.case_id
        for wanted in case.relevant:
            assert any(h == wanted or h.startswith(f"{wanted} ") for h in have), wanted
    for dispute in linking.load():
        for fact in dispute["facts"]:
            assert set(fact["issues"]) <= set(dispute["issues"])


def test_research_by_words_does_not_fall_below_what_was_measured(tmp_path):
    """The benchmark's figures for research by words, as measured for 0.8 (recall at 10 0.657,
    MRR 0.600, nDCG at 10 0.543, governing provisions offered 0.442): a regression fails here."""
    out = research.run(tmp_path, methods=["keyword"])
    [words] = out["results"]
    assert out["corpus"]["passages"] == 2563
    assert words["recall_10"] >= 0.655 and words["mrr"] >= 0.595 and words["ndcg_10"] >= 0.54
    assert words["governing_offered"] >= 0.44


def test_the_benchmarks_run_from_the_command_line(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_LEGAL_DB_PATH", str(tmp_path / "data" / "eli.sqlite3"))
    assert main(["evaluate", "linking", "--json", "--embedding", "none"]) == 0
    out = json.loads(capsys.readouterr().out)
    [words] = out["linking"]["results"]
    assert words["method"] == "words" and out["linking"]["facts"] == 50
    assert Path(tmp_path / "data" / "evaluation" / "linking.db").exists()


def test_an_administrator_can_embed_a_source_ahead_of_any_run(demo):
    from eli_legal.demo import SOURCE_ID
    from eli_legal.domain.errors import InferenceUnavailable, PolicyDenied

    sv, _mid = demo
    with pytest.raises(InferenceUnavailable, match="searching by meaning is off"):
        sv.sources.index(SOURCE_ID, actor_id="admin")
    sv.ctx.embedder = Senses()
    with pytest.raises(PolicyDenied):
        sv.sources.index(SOURCE_ID, actor_id="sec.byrne")
    coverage = sv.sources.index(SOURCE_ID, actor_id="admin")
    assert coverage.complete and coverage.indexed_now == coverage.total > 0
    [event] = [e for e in sv.ctx.audit.events(matter_id="-") if e["event_type"] == "source_indexed"]
    assert event["actor_id"] == "admin" and event["subject_id"] == SOURCE_ID


def test_what_a_party_says_of_an_authority_is_shown_beside_its_closest_passage_in_meaning(demo):
    """Chosen during the run and kept with the finding, so the approved report is rebuilt the
    same without the model; the report says how it was chosen."""
    sv, mid = demo
    sv.ctx.embedder = Senses()
    run = sv.runs.start(mid, actor_id="sec.byrne")
    cited = [
        c
        for c in sv.ctx.store.list(Claim, mid, run_id=run.run_id)
        if c.kind is ClaimKind.PARTY_AUTHORITY and c.authority_id
    ]
    assert cited
    for claim in cited:
        own = {p.passage_id for p in sv.ctx.store.passages_for(claim.authority_id)}
        assert claim.closest_passage_id in own
    report = sv.runs.summary(mid, run.run_id, actor_id="arb.keane")["report"]
    assert "; closest in meaning)" in case_text(sv, report["path"])


def test_nothing_derived_from_a_case_outlives_its_purge(demo):
    """Vectors of a case's issues, facts and party statements are never stored; only vectors of
    the legal sources' passages are, and those hold no case material."""
    sv, mid = demo
    sv.ctx.embedder = Senses()
    sv.runs.start(mid, actor_id="sec.byrne")
    store = sv.ctx.store
    tables = {r[0] for r in store._all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "text_vectors" not in tables
    orphans = store._all(
        "SELECT count(*) FROM passage_vectors v "
        "LEFT JOIN passages p ON p.passage_id = v.passage_id WHERE p.passage_id IS NULL"
    )
    assert orphans[0][0] == 0, "every stored vector belongs to a legal source's passage"
    before = store._all("SELECT count(*) FROM passage_vectors")[0][0]
    assert before > 0
    sv.matters.close(mid, actor_id="arb.keane", purge_content=True, reason="Retention ended.")
    from eli_legal.domain.models import Claim, Issue

    assert not store.list(Claim, mid) and not store.list(Issue, mid)
    assert store._all("SELECT count(*) FROM passage_vectors")[0][0] == before, (
        "the legal sources' vectors are not the case's to purge"
    )


def test_a_fact_linked_by_meaning_alone_is_marked_for_the_reviewer(demo):
    """Meaning finds more links than words, and some are wrong: each one made by meaning alone
    is recorded with the fact and marked in the report."""
    sv, mid = demo
    sv.ctx.embedder = Senses()
    run = sv.runs.start(mid, actor_id="sec.byrne")
    facts = [c for c in sv.ctx.store.list(Claim, mid, run_id=run.run_id) if c.meaning_issue_ids]
    assert facts, "the demonstration's papers give links by meaning alone"
    for fact in facts:
        assert set(fact.meaning_issue_ids) <= set(fact.issue_ids)
    report = sv.runs.summary(mid, run.run_id, actor_id="arb.keane")["report"]
    assert "by meaning only: check it bears on this issue" in case_text(sv, report["path"])


def test_meaning_links_are_recorded_apart_from_links_by_words():
    issues = [Issue(matter_id="m", run_id="r", label="Whether the employer lawfully fired her")]
    issues.append(Issue(matter_id="m", run_id="r", label="Whether the invoice was settled late"))
    facts = [
        Claim(matter_id="m", run_id="r", text=t, kind=ClaimKind.FACT)
        for t in ("She was dismissed on 4 March.", "The employer fired her lawfully, it says.",
                  "The payment arrived after the due date.", "The office is in Examplia City.")
    ]  # fmt: skip
    IssueMapper(
        LegalModel(NullInference()), semantic=SemanticIndex(Store(":memory:"), Senses())
    ).link_facts(issues=issues, facts=facts)
    fired = issues[0].issue_id
    assert facts[0].meaning_issue_ids == [fired], "no shared words: linked by meaning alone"
    assert fired in facts[1].issue_ids and not facts[1].meaning_issue_ids, "shares its words"


def test_auto_prefers_the_model_measured_to_link_facts_as_precisely_as_words(tmp_path, monkeypatch):
    """bge-small ranks law well but links facts less precisely than words; nomic-embed does not.
    With both in the model folder, auto takes nomic-embed though it is the larger."""
    monkeypatch.setattr(embedding_mod, "model_folders", lambda extra, home: [("t", tmp_path)])
    small = tmp_path / "bge-small-en-v1.5-q8_0.gguf"
    large = tmp_path / "nomic-embed-text-v1.5.Q8_0.gguf"
    other = tmp_path / "e5-small-v2.Q8_0.gguf"
    for path, size in ((small, 36), (large, 140), (other, 30)):
        path.write_bytes(b"\0" * (size * 1024 * 1024))
    assert embedding_mod.discover() == [large, other, small]
    assert embedding_mod.from_settings("auto").path == large
