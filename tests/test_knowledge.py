from pathlib import Path
from types import SimpleNamespace

import pytest

from odoo_config_assistant.assistant import NOT_COVERED_MARKER, answer, load_env_file, make_client
from odoo_config_assistant.knowledge import (
    DEFAULT_INDEX_PATH,
    BM25Retriever,
    Chunk,
    Citation,
    KnowledgeIndex,
    build_index,
    clean_rst,
    is_covered,
    split_sections,
)
from odoo_config_assistant.models import LICENSE_NOTICE, Step

COMMIT = "ca129a822019682bd32552e4cbabba2520d1308e"

SAMPLE_RST = """:show-content:

=====
Taxes
=====

Taxes are configured per company. Go to :menuselection:`Accounting --> Configuration --> Taxes`.

.. image:: taxes/list.png
   :alt: tax list

.. _taxes/default:

Default taxes
-------------

The default :guilabel:`Sales Tax` and :guilabel:`Purchase Tax` are automatically set on products
when creating new products.

.. note::
   Default taxes can be changed in the settings of the accounting application.
"""


def make_chunk(text: str, version: str = "18.0", path: str = "content/applications/a.rst"):
    return Chunk(
        id=f"{path}#{version}",
        version=version,
        commit=COMMIT,
        path=path,
        page_title="Page",
        section_title="Section",
        text=text,
    )


class FakeClient:
    """Stands in for anthropic.Anthropic: records the call, returns a canned response."""

    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.calls = []
        response = SimpleNamespace(
            stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
        )

        def create(**kwargs):
            self.calls.append(kwargs)
            return response

        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.fixture
def retriever():
    return BM25Retriever(
        [
            make_chunk(
                "Default sales tax and purchase tax are set on new products. Tax included prices."
            ),
            make_chunk("Warehouses and storage locations organise inventory in the warehouse."),
            make_chunk("Bills of materials list components and operations for manufacturing."),
        ],
        min_score=0.5,
    )


# Sectioning -------------------------------------------------------------------------------


def test_split_sections_attaches_labels_and_skips_images():
    sections = split_sections(SAMPLE_RST)
    titles = [(title, label) for title, label, _ in sections if title]
    assert titles == [("Taxes", None), ("Default taxes", "taxes/default")]
    body = dict((t, b) for t, _, b in sections)["Taxes"]
    assert "image" not in body and "tax list" not in body


def test_clean_rst_resolves_roles():
    text = clean_rst(":menuselection:`A --> B` and :guilabel:`Save` see :doc:`page <../x/y>`")
    assert text == "A > B and Save see page"


def test_build_index_from_rst_tree(tmp_path: Path):
    page = tmp_path / "content/applications/finance/accounting/taxes.rst"
    page.parent.mkdir(parents=True)
    page.write_text(SAMPLE_RST, encoding="utf-8")
    index = build_index(tmp_path, COMMIT, ["content/applications/finance"])
    assert index.commit == COMMIT
    default = next(c for c in index.chunks if c.section_title == "Default taxes")
    assert default.url.endswith("finance/accounting/taxes.html#taxes-default")
    assert default.domain == "finance"
    index.save(tmp_path / "idx.json")
    assert KnowledgeIndex.load(tmp_path / "idx.json").chunks == index.chunks


# RG-006 -----------------------------------------------------------------------------------


def test_rg006_uncovered_question_is_stated_without_citation(retriever):
    result = answer("Quelle est la recette de la tourtière ?", retriever)
    assert not result.covered and result.citations == []
    assert "pas couverte par la documentation" in result.text


def test_rg006_covered_question_cites_at_least_one_source(retriever):
    result = answer("Quelles sont les taxes par défaut des articles ?", retriever)
    assert result.covered and result.mode == "extracts"
    assert len(result.citations) >= 1
    assert result.citations[0].number == 1


def test_rg006_model_answer_without_citation_is_discarded(retriever):
    client = FakeClient("Les taxes par défaut se règlent dans les paramètres.")
    result = answer("Quelles sont les taxes par défaut des articles ?", retriever, client=client)
    assert not result.covered and result.citations == []


def test_rg006_model_not_covered_marker_is_honoured(retriever):
    client = FakeClient(NOT_COVERED_MARKER)
    result = answer("Quelles sont les taxes par défaut des articles ?", retriever, client=client)
    assert not result.covered


def test_rg006_model_refusal_gives_not_covered(retriever):
    client = FakeClient("", stop_reason="refusal")
    result = answer("Quelles sont les taxes par défaut des articles ?", retriever, client=client)
    assert not result.covered


def test_rg006_model_answer_keeps_only_cited_excerpts(retriever):
    client = FakeClient("La taxe de vente par défaut est posée sur les nouveaux articles [1].")
    result = answer("Quelles sont les taxes par défaut des articles ?", retriever, client=client)
    assert result.covered and result.mode == "llm"
    assert [c.number for c in result.citations] == [1]
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert "<extrait numero=1" in call["messages"][0]["content"]


def test_rg006_model_is_not_called_when_nothing_is_found(retriever):
    client = FakeClient("Réponse inventée [1].")
    result = answer("Qui a gagné la coupe Stanley en 1993 ?", retriever, client=client)
    assert not result.covered and client.calls == []


def test_is_covered_requires_score_and_terms(retriever):
    assert not is_covered([], "taxes")
    hits = retriever.search("taxes par défaut des articles")
    assert is_covered(hits, "taxes par défaut des articles", min_score=0.5)
    assert not is_covered(hits, "taxes par défaut des articles", min_score=1000)


def test_make_client_without_key_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert make_client() is None


def test_env_file_is_read_without_overriding_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_MODEL", "from-env")
    env = tmp_path / ".env"
    env.write_text("# commentaire\nANTHROPIC_API_KEY=sk-test\nCLAUDE_MODEL=from-file\nEMPTY=\n")
    load_env_file(env)
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test"
    assert os.environ["CLAUDE_MODEL"] == "from-env"
    assert "EMPTY" not in os.environ


# RG-007 -----------------------------------------------------------------------------------


def test_rg007_search_only_returns_project_version():
    retriever = BM25Retriever(
        [
            make_chunk("Fiscal positions map taxes for Quebec customers.", version="17.0"),
            make_chunk("Fiscal positions map taxes for Quebec customers.", version="18.0"),
            make_chunk("Unrelated text about warehouses.", version="18.0"),
        ],
        min_score=0.1,
    )
    hits = retriever.search("positions fiscales Québec", version="18.0")
    assert [h.chunk.version for h in hits] == ["18.0"]
    assert retriever.search("positions fiscales Québec", version="16.0") == []
    result = answer("positions fiscales Québec", retriever, version="18.0")
    assert {c.version for c in result.citations} == {"18.0"}


def test_rg007_other_erp_is_excluded():
    chunk = make_chunk("Fiscal positions map taxes for Quebec customers.")
    other = chunk.model_copy(update={"erp": "sap", "id": "sap"})
    hits = BM25Retriever([chunk, other]).search("positions fiscales Québec", erp="odoo")
    assert [h.chunk.erp for h in hits] == ["odoo"]


def test_step_context_boosts_its_sources():
    a = make_chunk("Taxes and fiscal positions.", path="content/applications/a.rst")
    b = make_chunk("Taxes and fiscal positions.", path="content/applications/b.rst")
    step = Step.model_validate(
        {
            "id": "s",
            "title": "t",
            "objective": "o",
            "menu_path": "A > B",
            "recommendations": [{"value": "v"}],
            "sources": [{"path": "content/applications/b.rst", "title": "B", "url": "u"}],
        }
    )
    c = make_chunk("Warehouses.", path="content/applications/c.rst")
    retriever = BM25Retriever([a, b, c], min_score=0.1)
    result = answer("taxes positions fiscales", retriever, step=step)
    assert result.citations[0].path == "content/applications/b.rst"
    assert result.step_id == "s"


# RG-008 / RG-014 ------------------------------------------------------------------------------


def test_rg008_answer_and_citations_keep_doc_commit(retriever):
    result = answer("Quelles sont les taxes par défaut des articles ?", retriever)
    assert result.doc_commit == COMMIT
    assert {c.commit for c in result.citations} == {COMMIT}


def test_rg008_not_covered_answer_keeps_doc_commit(retriever):
    result = answer("tourtière", retriever, doc_commit=COMMIT)
    assert result.doc_commit == COMMIT


def test_rg014_citation_shows_source_link_and_license():
    citation = Citation.from_chunk(make_chunk("Text " * 10), number=2)
    assert citation.url.startswith("https://www.odoo.com/documentation/18.0/fr/")
    assert citation.license == LICENSE_NOTICE and "CC BY-SA 4.0" in citation.license
    rendered = citation.markdown()
    assert citation.url in rendered and "CC BY-SA 4.0" in rendered and rendered.startswith("[2]")


# Real documentation (skipped when the index has not been built) ---------------------------

real_index = pytest.mark.skipif(
    not DEFAULT_INDEX_PATH.exists(), reason="index absent : lancer scripts/build_index.py"
)


@real_index
def test_real_index_answers_quebec_fiscal_positions():
    retriever = BM25Retriever(KnowledgeIndex.load().chunks)
    result = answer(
        "Comment configurer les positions fiscales au Québec ?", retriever, country="CA"
    )
    assert result.covered
    assert result.citations[0].path.endswith("fiscal_localizations/canada.rst")


@real_index
def test_real_index_does_not_cover_quebec_payroll_or_qst_rate():
    retriever = BM25Retriever(KnowledgeIndex.load().chunks)
    for question in ("Comment configurer la paie au Québec ?", "Quel est le taux de la TVQ ?"):
        assert not answer(question, retriever, country="CA").covered
