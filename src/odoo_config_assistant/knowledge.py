"""Documentary knowledge base: RST sectioning, BM25 search and citations.

- RG-006: ``is_covered`` decides whether hits are relevant enough to answer at all.
- RG-007: every search is filtered on the ERP and version of the project.
- RG-008: chunks, hits and citations carry the documentation commit id.
- RG-014: a citation always exposes the public page URL and the CC BY-SA 4.0 notice.

The ``Retriever`` protocol keeps the door open for a semantic retriever later: anything that
implements ``search(query, erp=..., version=..., k=...)`` can replace ``BM25Retriever``.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from odoo_config_assistant import DOC_VERSION, ERP
from odoo_config_assistant.models import LICENSE_NOTICE, LICENSE_URL, public_url

DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[2] / "index" / "odoo-18.0.json"
INDEX_FORMAT = 1


# --------------------------------------------------------------------------- RST sectioning

_ADORNMENT = re.compile(r"^([=\-~^*+#\"'`:.])\1{2,}\s*$")
_LABEL = re.compile(r"^\.\.\s+_([^:]+):\s*$")
_DIRECTIVE = re.compile(r"^\.\.\s+([\w:-]+)::(.*)$")
_SKIPPED_DIRECTIVES = {"image", "figure", "toctree", "raw", "only", "cards", "card"}


class Chunk(BaseModel):
    """Indexed unit: one section of one RST page."""

    id: str
    erp: str = ERP
    version: str = DOC_VERSION
    commit: str
    path: str
    anchor: str | None = None
    page_title: str
    section_title: str
    text: str

    @property
    def url(self) -> str:
        return public_url(self.path, self.anchor, self.version)

    @property
    def domain(self) -> str:
        parts = self.path.split("/")
        return parts[2] if len(parts) > 3 and parts[1] == "applications" else parts[1]


def clean_rst(text: str) -> str:
    """Turn RST inline markup into readable text."""
    text = re.sub(r":menuselection:`([^`]*)`", lambda m: m.group(1).replace("-->", ">"), text)
    text = re.sub(r":(?:doc|ref):`([^`<]*?)\s*<[^>]*>`", r"\1", text)
    text = re.sub(r":(?:doc|ref):`([^`]*)`", lambda m: m.group(1).split("/")[-1], text)
    text = re.sub(r":icon:`[^`]*`", "", text)
    text = re.sub(r":abbr:`([^`(]*?)\s*\(([^)]*)\)`", r"\1 (\2)", text)
    text = re.sub(r":[a-z]+:`([^`]*)`", r"\1", text)
    text = re.sub(r"`([^`<]+?)\s*<[^>]+>`_+", r"\1", text)
    text = re.sub(r"``([^`]*)``", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\|([A-Za-z]+)\|", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sections(rst: str) -> list[tuple[str, str | None, str]]:
    """Split an RST document into (title, label, raw body) by section titles."""
    lines = rst.splitlines()
    sections: list[tuple[str, str | None, list[str]]] = [("", None, [])]
    pending_label: str | None = None
    skip_indent: int | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if skip_indent is not None:
            if stripped and (len(line) - len(line.lstrip())) <= skip_indent:
                skip_indent = None
            else:
                i += 1
                continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        # Overlined title: ===== / Title / =====
        if _ADORNMENT.match(line) and i + 2 < len(lines) and _ADORNMENT.match(lines[i + 2]):
            title = lines[i + 1].strip()
            if title and not _ADORNMENT.match(lines[i + 1]):
                sections.append((title, pending_label, []))
                pending_label = None
                i += 3
                continue
        # Underlined title: Title / =====
        if (
            stripped
            and not stripped.startswith("..")
            and _ADORNMENT.match(nxt)
            and len(nxt.strip()) >= len(stripped)
        ):
            sections.append((stripped, pending_label, []))
            pending_label = None
            i += 2
            continue
        label = _LABEL.match(stripped)
        if label:
            pending_label = label.group(1).strip()
            i += 1
            continue
        directive = _DIRECTIVE.match(stripped)
        if directive and directive.group(1) in _SKIPPED_DIRECTIVES:
            skip_indent = len(line) - len(line.lstrip())
            i += 1
            continue
        if stripped.startswith(":") and stripped.endswith(":") and " " not in stripped:
            i += 1  # file-level field such as :show-content:
            continue
        if directive:
            # keep admonition content (note, tip, important...), drop the marker itself
            rest = directive.group(2).strip()
            if rest:
                sections[-1][2].append(rest)
            i += 1
            continue
        if stripped.startswith(".. |") or stripped.startswith(".. _"):
            i += 1
            continue
        sections[-1][2].append(line)
        i += 1
    return [(title, label, "\n".join(body)) for title, label, body in sections]


def chunk_file(
    docs_root: Path, path: Path, commit: str, erp: str = ERP, version: str = DOC_VERSION
) -> list[Chunk]:
    rel = path.relative_to(docs_root).as_posix()
    sections = split_sections(path.read_text(encoding="utf-8"))
    page_title = next((t for t, _, _ in sections if t), path.stem)
    chunks = []
    for n, (title, label, body) in enumerate(sections):
        text = clean_rst(body)
        if len(text) < 40:
            continue
        chunks.append(
            Chunk(
                id=f"{rel}#{n}",
                erp=erp,
                version=version,
                commit=commit,
                path=rel,
                anchor=label,
                page_title=page_title,
                section_title=title or page_title,
                text=text,
            )
        )
    return chunks


# --------------------------------------------------------------------------- index file


class KnowledgeIndex(BaseModel):
    format: int = INDEX_FORMAT
    erp: str = ERP
    version: str = DOC_VERSION
    commit: str
    built_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    chunks: list[Chunk]
    # Empreinte SHA-256 de chaque page RST de la version (détection des changements, F-002).
    page_hashes: dict[str, str] = Field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = DEFAULT_INDEX_PATH) -> KnowledgeIndex:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


def build_index(
    docs_root: Path,
    commit: str,
    include: Iterable[str],
    erp: str = ERP,
    version: str = DOC_VERSION,
    previous: KnowledgeIndex | None = None,
    errors: list[tuple[str, str]] | None = None,
) -> KnowledgeIndex:
    """Index every RST file under the ``include`` prefixes (directories or files).

    A page that cannot be read or parsed is left out (ERR-005); its sections from ``previous``
    (the active version), if any, are kept. Each failure is appended to ``errors``.
    """
    files: set[Path] = set()
    for prefix in include:
        target = docs_root / prefix
        if target.is_file():
            files.add(target)
        elif target.is_dir():
            files.update(target.rglob("*.rst"))
    kept: dict[str, list[Chunk]] = {}
    for chunk in previous.chunks if previous else []:
        kept.setdefault(chunk.path, []).append(chunk)
    chunks = []
    for path in sorted(files):
        try:
            chunks.extend(chunk_file(docs_root, path, commit, erp, version))
        except (UnicodeDecodeError, ValueError, IndexError) as exc:
            rel = path.relative_to(docs_root).as_posix()
            if errors is not None:
                errors.append((rel, f"{type(exc).__name__} : {exc}"))
            chunks.extend(kept.get(rel, []))
    return KnowledgeIndex(erp=erp, version=version, commit=commit, chunks=chunks)


# --------------------------------------------------------------------------- tokenization

_STOPWORDS_TEXT = """
a an and are as at be by can de des du en est et for from how i if in is it la le les of
on or ou par pour que quel quelle quelles quels qui sur the this to un une what when which
with dans comment faut il elle on doit dois peut est-ce ce cette ces mon ma mes nos notre
votre vos son sa ses leur leurs au aux y a-t-il je nous vous ils elles se sont avec sans
plus moins tout tous toute toutes faire configure configurer odoo
"""
_STOPWORDS = frozenset(_STOPWORDS_TEXT.split())

# Minimal French -> English glossary: the indexed pages are in English (V0, no .po
# recomposition), questions are asked in French. Terms only, no documentation content.
GLOSSARY: dict[str, str] = {
    "taxe": "tax",
    "taxes": "tax taxes",
    "tps": "gst",
    "tvq": "qst quebec",
    "tvh": "hst",
    "tva": "vat",
    "france": "france french",
    "français": "french",
    "française": "french",
    "intracommunautaire": "intra community eu",
    "facturation": "invoicing",
    "électronique": "electronic e-invoicing",
    "plateforme": "platform",
    "agréée": "approved",
    "fec": "fec",
    "générer": "generate generation",
    "fichier": "file",
    "exporter": "export",
    "importer": "import",
    "liasse": "liasse fiscale",
    "sepa": "sepa",
    "prélèvement": "direct debit sdd",
    "virement": "credit transfer sct",
    "mandat": "mandate",
    "mandats": "mandates",
    "chorus": "chorus pro",
    "siret": "siret",
    "siren": "siren",
    "québec": "quebec",
    "quebec": "quebec",
    "position": "position",
    "positions": "positions",
    "fiscale": "fiscal",
    "fiscales": "fiscal",
    "fiscal": "fiscal",
    "exercice": "fiscal year",
    "année": "year",
    "plan": "chart",
    "comptable": "accounts accounting",
    "comptes": "accounts",
    "compte": "account",
    "journal": "journal",
    "journaux": "journals",
    "devise": "currency",
    "devises": "currencies",
    "conditions": "terms",
    "paiement": "payment",
    "chèque": "check checks",
    "chèques": "checks",
    "banque": "bank",
    "bancaire": "bank",
    "verrouillage": "lock",
    "soldes": "balances",
    "solde": "balance",
    "ouverture": "opening",
    "déclaration": "return",
    "périodicité": "periodicity",
    "localisation": "localization",
    "rapport": "report",
    "rapports": "reports",
    "entrepôt": "warehouse",
    "entrepôts": "warehouses",
    "emplacement": "location",
    "emplacements": "locations",
    "unité": "unit",
    "unités": "units",
    "mesure": "measure uom",
    "catégorie": "category",
    "catégories": "categories",
    "article": "product",
    "articles": "products",
    "route": "route",
    "routes": "routes",
    "nomenclature": "bill materials bom",
    "nomenclatures": "bills materials bom",
    "poste": "work center",
    "postes": "work centers",
    "travail": "work",
    "ordre": "order",
    "ordres": "orders",
    "fabrication": "manufacturing manufacture",
    "fabriquer": "manufacture",
    "réception": "receipt receipts",
    "réceptions": "receipts",
    "livraison": "delivery",
    "livraisons": "deliveries delivery",
    "étapes": "steps",
    "étape": "step",
    "lot": "lot lots",
    "lots": "lots",
    "série": "serial",
    "réapprovisionnement": "replenishment reordering",
    "fournisseur": "vendor",
    "fournisseurs": "vendors",
    "client": "customer",
    "clients": "customers",
    "délai": "lead time",
    "achat": "purchase buy",
    "achats": "purchase purchases",
    "vente": "sales sale",
    "ventes": "sales",
    "stock": "stock inventory",
    "inventaire": "inventory physical",
    "quantités": "quantities quantity",
    "valorisation": "valuation",
    "coût": "cost costing",
    "méthode": "method",
    "commande": "order",
    "société": "company",
    "entreprise": "company",
    "escompte": "discount",
    "stockage": "storage",
    "imprimer": "print printing",
    "impression": "print printing",
    "deux": "two",
    "trois": "three",
    "dénombrement": "count counting",
    "matières": "materials",
    "premières": "raw",
    "composant": "component",
    "composants": "components",
    "activer": "enable activate",
    "paramètres": "settings",
}

# Country code -> page name under content/applications/finance/fiscal_localizations/
LOCALIZATION_PAGES = {"CA": "canada", "FR": "france", "BE": "belgium", "US": "united_states"}
_LOCALIZATION_DIR = "content/applications/finance/fiscal_localizations/"


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    ).lower()


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[\w]+", text.lower())
    tokens: list[str] = []
    for word in words:
        if word in _STOPWORDS or len(word) < 2:
            continue
        tokens.append(_fold(word))
    return tokens


def expand_query(query: str) -> list[str]:
    """Tokens of the query plus the English equivalents of known French terms."""
    tokens = tokenize(query)
    expanded = list(tokens)
    for word in re.findall(r"[\w]+", query.lower()):
        if word in GLOSSARY:
            expanded.extend(tokenize(GLOSSARY[word]))
    return expanded


# --------------------------------------------------------------------------- retrieval


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    matched_terms: frozenset[str]


class Retriever(Protocol):
    def search(self, query: str, *, erp: str, version: str, k: int = 5) -> list[Hit]: ...


class BM25Retriever:
    """Okapi BM25 over section chunks (k1=1.5, b=0.75).

    ``min_score`` is the RG-006 relevance threshold. BM25 scores grow with corpus size, so the
    default is calibrated on the full Odoo 18 index (about 2,700 sections).
    """

    def __init__(
        self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75, min_score: float = 6.0
    ):
        self.chunks = chunks
        self.min_score = min_score
        self.k1 = k1
        self.b = b
        self._docs = [
            Counter(tokenize(f"{c.page_title} {c.section_title} {c.section_title} {c.text}"))
            for c in chunks
        ]
        self._lengths = [sum(d.values()) for d in self._docs]
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        df: Counter[str] = Counter()
        for doc in self._docs:
            df.update(doc.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(
        self,
        query: str,
        *,
        erp: str = ERP,
        version: str = DOC_VERSION,
        k: int = 5,
        boost_paths: Iterable[str] = (),
        country: str | None = None,
    ) -> list[Hit]:
        """Rank chunks of ``erp``/``version`` only (RG-007).

        ``boost_paths`` favours the pages cited by the open step; ``country`` demotes the fiscal
        localization pages of other countries.
        """
        terms = set(expand_query(query))
        boosted = set(boost_paths)
        own_page = LOCALIZATION_PAGES.get((country or "").upper())
        hits = []
        for chunk, doc, length in zip(self.chunks, self._docs, self._lengths, strict=True):
            if chunk.erp != erp or chunk.version != version:  # RG-007
                continue
            matched = terms & doc.keys()
            if not matched:
                continue
            score = 0.0
            for term in matched:
                tf = doc[term]
                norm = (
                    tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self._avg))
                )
                score += self._idf[term] * norm
            if chunk.path in boosted:
                score *= 1.25
            if country and chunk.path.startswith(_LOCALIZATION_DIR):
                page = chunk.path.removeprefix(_LOCALIZATION_DIR).split("/")[0].removesuffix(".rst")
                if page != own_page:
                    score *= 0.5
            hits.append(Hit(chunk, score, frozenset(matched)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]


def is_covered(hits: list[Hit], query: str, min_score: float = 6.0, min_terms: int = 2) -> bool:
    """RG-006 guard: the best hit must be strong and match enough distinct query terms.

    A query with a single meaningful term only needs that term to match.
    """
    if not hits:
        return False
    needed = min(min_terms, len(set(tokenize(query))) or 1)
    best = hits[0]
    return best.score >= min_score and len(best.matched_terms) >= needed


# --------------------------------------------------------------------------- citations


class Citation(BaseModel):
    """Source shown under an answer or a step (RG-008, RG-014)."""

    title: str
    path: str
    url: str
    commit: str
    version: str
    excerpt: str = ""
    number: int | None = None
    license: str = LICENSE_NOTICE
    license_url: str = LICENSE_URL

    @classmethod
    def from_chunk(
        cls, chunk: Chunk, number: int | None = None, excerpt_chars: int = 600
    ) -> Citation:
        title = chunk.page_title
        if chunk.section_title and chunk.section_title != chunk.page_title:
            title = f"{chunk.page_title} : {chunk.section_title}"
        excerpt = (
            chunk.text if len(chunk.text) <= excerpt_chars else chunk.text[:excerpt_chars] + "…"
        )
        return cls(
            title=title,
            path=chunk.path,
            url=chunk.url,
            commit=chunk.commit,
            version=chunk.version,
            excerpt=excerpt,
            number=number,
        )

    def markdown(self) -> str:
        prefix = f"[{self.number}] " if self.number is not None else ""
        return (
            f"{prefix}[{self.title}]({self.url}) · Odoo {self.version}, "
            f"commit `{self.commit[:7]}` · [{self.license}]({self.license_url})"
        )


# --------------------------------------------------------------------------- doc version

_ROOT = Path(__file__).resolve().parents[2]


def current_doc_commit(index_path: Path = DEFAULT_INDEX_PATH) -> str | None:
    """Commit of the documentation in use: index, then local clone, then verified commit."""
    candidates = [
        index_path,
        _ROOT / "vendor" / "odoo-docs.version.json",
        _ROOT / "data" / "doc_version.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")).get("commit")
            except ValueError:
                continue
    return None
