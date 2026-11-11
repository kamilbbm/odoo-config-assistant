"""French recomposition from the gettext files (F-003, RG-010, ERR-003, ERR-004)."""

import json
from pathlib import Path

import pytest

from odoo_config_assistant.journeys import load_catalog
from odoo_config_assistant.knowledge import (
    DEFAULT_INDEX_PATH,
    Citation,
    build_index,
    split_sections,
)
from odoo_config_assistant.translation import (
    PoError,
    Translations,
    domain_of,
    load_translations,
    parse_po,
)

PAGE = "content/applications/finance/sample.rst"
RST = """\
.. _sample/top:

======
Sample
======

Odoo computes the taxes
of every invoice line.

.. _sample/menu:

Menus
=====

- Go to :menuselection:`Accounting --> Configuration --> Taxes` to see
  every tax of the company.
- Untranslated item of the list.

.. note::
   A note that nobody translated yet but which is long enough.
"""

PO = r'''# French translation
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"

#: ../../content/applications/finance/sample.rst:5
msgid "Sample"
msgstr "Exemple"

#: ../../content/applications/finance/sample.rst:7
msgid "Odoo computes the taxes of every invoice line."
msgstr "Odoo calcule les taxes de chaque ligne de facture."

#: ../../content/applications/finance/sample.rst:13
msgid "Menus"
msgstr "Menus de configuration"

#: ../../content/applications/finance/sample.rst:15
msgid ""
"Go to :menuselection:`Accounting --> Configuration --> Taxes` to see every "
"tax of the company."
msgstr ""
"Allez dans :menuselection:`Comptabilité --> Configuration --> Taxes` pour "
"voir toutes les taxes de la société."

#: ../../content/applications/finance/sample.rst:17
msgid "Untranslated item of the list."
msgstr ""

#: ../../content/applications/finance/sample.rst:20
#, fuzzy
msgid "A note that nobody translated yet but which is long enough."
msgstr "Une note approximative."
'''


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "docs"
    (root / "content/applications/finance").mkdir(parents=True)
    (root / PAGE).write_text(RST, encoding="utf-8")
    locale = root / "locale/fr/LC_MESSAGES"
    locale.mkdir(parents=True)
    (locale / "finance.po").write_text(PO, encoding="utf-8")
    return root


def test_parse_po_reads_multiline_strings_references_and_fuzzy_flag():
    entries = parse_po(PO)
    menu = next(e for e in entries if e.msgid.startswith("Go to"))
    assert menu.msgid.endswith("every tax of the company.")
    assert menu.refs == [(PAGE, 15)]
    assert next(e for e in entries if e.msgid.startswith("A note")).fuzzy


def test_parse_po_rejects_a_broken_file():
    with pytest.raises(PoError):
        parse_po('msgid "ok"\nmsgstr "ok"\nbroken line\n')


def test_recompose_replaces_matching_blocks_and_keeps_the_rest_in_english(docs):
    translations = load_translations(docs)
    result = translations.recompose(PAGE, RST)
    assert "Odoo calcule les taxes de chaque ligne de facture." in result.text
    assert "- Allez dans :menuselection:`Comptabilité --> Configuration --> Taxes`" in result.text
    assert "Untranslated item of the list." in result.text  # msgstr vide : anglais conservé
    assert "A note that nobody translated" in result.text  # entrée fuzzy ignorée
    assert (result.segments, result.translated) == (5, 4)
    assert result.rate == pytest.approx(0.8)


def test_translated_titles_keep_valid_adornments(docs):
    result = load_translations(docs).recompose(PAGE, RST)
    titles = [title for title, _, _ in split_sections(result.text)]
    assert titles == [title and title for title in ["", "Exemple", "Menus de configuration"]]
    assert "======================" in result.text  # soulignement allongé au titre français


def test_menu_labels_come_from_the_menuselection_pairs(docs):
    translations = load_translations(docs)
    assert translations.menu_labels["Accounting"] == "Comptabilité"
    assert translations.menu_path(["Accounting", "Configuration", "Taxes"]) == (
        "Comptabilité > Configuration > Taxes"
    )
    assert translations.menu_path(["Accounting", "Unknown"]) is None


def test_err003_unreadable_po_file_leaves_its_domain_in_english(docs):
    (docs / "locale/fr/LC_MESSAGES/finance.po").write_text("garbage\n", encoding="utf-8")
    translations = load_translations(docs)
    assert "finance" in translations.failed_domains
    assert translations.domain_failed(PAGE)
    index = build_index(docs, "c" * 40, ["content/applications/finance"], translations=translations)
    assert all(c.text_fr is None for c in index.chunks)
    assert all("non traduite" in c.translation_note for c in index.chunks)


def test_index_chunks_carry_the_french_text_and_the_rg010_mention(docs):
    translations = load_translations(docs)
    index = build_index(
        docs, "c" * 40, ["content/applications/finance"], translations=translations, threshold=0.9
    )
    chunk = next(c for c in index.chunks if c.anchor == "sample/top")
    assert chunk.page_title_fr == "Exemple" and "Odoo calcule" in chunk.text_fr
    assert "Odoo computes" in chunk.text  # le texte anglais reste indexé
    assert chunk.translation_rate == pytest.approx(0.8)
    assert "Traduction partielle (80 %" in chunk.translation_note.replace("80%", "80 %")
    citation = Citation.from_chunk(chunk, 1)
    assert citation.title == "Exemple" and "Odoo calcule" in citation.excerpt
    assert citation.translation_note == chunk.translation_note
    assert index.menu_labels["Accounting"] == "Comptabilité"
    assert index.translation_rates[PAGE] == pytest.approx(0.8)


def test_page_without_translation_is_shown_in_english_with_a_mention(docs):
    other = docs / "content/applications/finance/other.rst"
    other.write_text("Other\n=====\n\nA page that the translators never saw at all.\n")
    index = build_index(
        docs, "c" * 40, ["content/applications/finance"], translations=load_translations(docs)
    )
    chunk = next(c for c in index.chunks if c.path.endswith("other.rst"))
    assert chunk.text_fr is None and chunk.display_text.startswith("A page")
    assert chunk.translation_note.startswith("Page non traduite")


def test_domain_of_page():
    assert domain_of("content/applications/finance/accounting/taxes.rst") == "finance"
    assert domain_of("content/administration/upgrade.rst") == "administration"


def test_translations_without_page_return_none():
    assert Translations().recompose(PAGE, RST) is None


@pytest.mark.skipif(not DEFAULT_INDEX_PATH.exists(), reason="index absent")
def test_real_index_gives_a_french_menu_path_for_every_step():
    data = json.loads(Path(DEFAULT_INDEX_PATH).read_text(encoding="utf-8"))
    labels = data.get("menu_labels") or {}
    if not labels:
        pytest.skip("index construit sans les traductions")
    catalog = load_catalog()
    missing = [
        (s.id, item)
        for j in catalog.journeys
        for s in j.steps
        for item in s.menu_items
        if item not in labels
    ]
    assert not missing
    assert labels["Accounting"] == "Comptabilité"


def test_f003_indexed_units_are_labelled():
    from odoo_config_assistant.knowledge import chunk_tags

    raw = (
        "Install `l10n_fr_account` then go to :menuselection:`Accounting -->\n"
        "Configuration --> Settings`."
    )
    tags = chunk_tags("content/applications/finance/fiscal_localizations/france.rst", raw)
    assert tags == {
        "application": "finance/fiscal_localizations",
        "country": "FR",
        "modules": ["l10n_fr_account"],
        "menus": ["Accounting > Configuration > Settings"],
    }
    other = chunk_tags("content/applications/inventory_and_mrp/inventory.rst", "No module.")
    assert other["application"] == "inventory_and_mrp/inventory" and other["country"] is None


def test_declared_source_defaults_to_the_official_repository():
    from odoo_config_assistant.db import Organisation

    assert Organisation(name="X").doc_repo == "https://github.com/odoo/documentation"
