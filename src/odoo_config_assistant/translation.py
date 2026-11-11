"""French recomposition of the RST pages from the gettext files (F-003, RG-010).

odoo/documentation ships one .po file per domain in ``locale/fr/LC_MESSAGES``. Each entry gives
the English segment (``msgid``), its French translation (``msgstr``) and its references
``../../content/<page>.rst:<line>``. A page is recomposed by replacing, line by line, the RST
block that starts at each referenced line with its translation, but only when the block text is
exactly the ``msgid``: anything else stays in English.

The translation rate of a page is the share of its segments actually replaced. Under the
threshold (ERR-004, Q-003) the page is published with a "traduction partielle" mention; a .po
file that cannot be read leaves the pages of its domain in English (ERR-003).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

LOCALE_DIR = Path("locale") / "fr" / "LC_MESSAGES"
_REF = re.compile(r"(?:\.\./)*(content/\S+?\.rst):(\d+)")
_MARKER = re.compile(r"^(?:(?:[-*+]|#\.|\d+\.|[a-z]\.)\s+)+")
_MENU = re.compile(r":menuselection:`([^`]*)`")
_ADORNMENT = re.compile(r"\s*([=\-~^*+#\"'`:.])\1{2,}\s*")
_TOP_LEVEL = {"administration", "contributing", "developer", "legal"}


class PoError(ValueError):
    """Unreadable gettext file (ERR-003)."""


@dataclass
class PoEntry:
    msgid: str
    msgstr: str
    refs: list[tuple[str, int]]
    fuzzy: bool = False


def _unquote(token: str) -> str:
    token = token.strip()
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise PoError(f"chaîne mal formée : {token[:40]}")
    body = token[1:-1]
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
    out, i = [], 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append(escapes.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def parse_po(text: str) -> list[PoEntry]:
    """Minimal gettext parser: msgid, msgstr, references and fuzzy flag (no plurals needed)."""
    entries: list[PoEntry] = []
    refs: list[tuple[str, int]] = []
    fuzzy = False
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    current: list[str] | None = None

    def flush() -> None:
        nonlocal refs, fuzzy, msgid, msgstr, current
        if msgid is not None and msgstr is not None:
            entries.append(PoEntry("".join(msgid), "".join(msgstr), refs, fuzzy))
        refs, fuzzy, msgid, msgstr, current = [], False, None, None, None

    for line in text.splitlines():
        if not line.strip():
            flush()
        elif line.startswith("#:"):
            if msgstr is not None:
                flush()
            refs += [(m.group(1), int(m.group(2))) for m in _REF.finditer(line)]
        elif line.startswith("#,"):
            fuzzy = fuzzy or "fuzzy" in line
        elif line.startswith("#"):
            continue
        elif line.startswith("msgid "):
            if msgstr is not None:
                flush()
            msgid = [_unquote(line[6:])]
            current = msgid
        elif line.startswith("msgstr "):
            if msgid is None:
                raise PoError("msgstr sans msgid")
            msgstr = [_unquote(line[7:])]
            current = msgstr
        elif line.startswith('"'):
            if current is None:
                raise PoError(f"ligne orpheline : {line[:40]}")
            current.append(_unquote(line))
        elif line.startswith(("msgctxt", "msgid_plural", "msgstr[")):
            continue
        else:
            raise PoError(f"ligne inattendue : {line[:40]}")
    flush()
    return entries


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class PageTranslation:
    text: str
    segments: int
    translated: int

    @property
    def rate(self) -> float:
        return self.translated / self.segments if self.segments else 0.0


@dataclass
class Translations:
    """French segments by page and line, plus the French menu labels."""

    pages: dict[str, dict[int, tuple[str, str]]] = field(default_factory=dict)
    menu_labels: dict[str, str] = field(default_factory=dict)
    failed_domains: dict[str, str] = field(default_factory=dict)

    def domain_failed(self, page: str) -> str | None:
        """Error message if the .po file of the page's domain could not be read (ERR-003)."""
        return self.failed_domains.get(domain_of(page))

    def recompose(self, page: str, rst: str) -> PageTranslation | None:
        """French version of a page, or None when no translation exists for it."""
        segments = self.pages.get(page)
        if not segments:
            return None
        lines = rst.split("\n")
        out = list(lines)
        translated = 0
        for lineno in sorted(segments, reverse=True):
            msgid, msgstr = segments[lineno]
            if not msgstr:
                continue
            span = _block(lines, lineno - 1)
            if span is None:
                continue
            start, end, prefix, text = span
            if _norm(text) != _norm(msgid):
                continue
            new = prefix + _norm(msgstr)
            out[start:end] = [new]
            # A title keeps its adornment as long as the (often longer) French text.
            for neighbour in (start + 1, start - 1):
                if 0 <= neighbour < len(out) and _ADORNMENT.fullmatch(out[neighbour]):
                    out[neighbour] = out[neighbour].strip()[0] * len(new)
            translated += 1
        return PageTranslation("\n".join(out), len(segments), translated)

    def menu_path(self, items: list[str]) -> str | None:
        """French menu path if every item has a known translation."""
        french = [self.menu_labels.get(item) for item in items]
        if any(label is None for label in french):
            return None
        return " > ".join(french)  # type: ignore[arg-type]


def domain_of(page: str) -> str:
    parts = page.split("/")
    if len(parts) > 2 and parts[1] == "applications":
        return parts[2].removesuffix(".rst")
    return parts[1].removesuffix(".rst") if len(parts) > 1 else page


def _block(lines: list[str], start: int) -> tuple[int, int, str, str] | None:
    """RST block starting at ``start`` (0-based): (start, end, prefix, text)."""
    if start < 0 or start >= len(lines) or not lines[start].strip():
        return None
    if _ADORNMENT.fullmatch(lines[start]) and start > 0 and lines[start - 1].strip():
        # Sphinx references a section title by its underline: the title is the line above.
        title = lines[start - 1]
        return start - 1, start, title[: len(title) - len(title.lstrip())], title.strip()
    first = lines[start]
    indent = len(first) - len(first.lstrip())
    marker = _MARKER.match(first[indent:])
    prefix_len = indent + (marker.end() if marker else 0)
    prefix = first[:prefix_len]
    text = [first[prefix_len:]]
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            break
        line_indent = len(line) - len(line.lstrip())
        if line_indent < prefix_len or (_MARKER.match(line.lstrip()) and line_indent <= indent):
            break
        if _ADORNMENT.fullmatch(line):
            break  # title underline
        text.append(line.strip())
        end += 1
    return start, end, prefix, " ".join(text)


def _menu_labels(entries: list[PoEntry]) -> dict[str, str]:
    votes: dict[str, Counter[str]] = {}
    for entry in entries:
        if not entry.msgstr or entry.fuzzy:
            continue
        english, french = _MENU.findall(entry.msgid), _MENU.findall(entry.msgstr)
        if len(english) != len(french):
            continue
        for en_path, fr_path in zip(english, french, strict=True):
            en_items = [i.strip() for i in _norm(en_path).split("-->")]
            fr_items = [i.strip() for i in _norm(fr_path).split("-->")]
            if len(en_items) != len(fr_items):
                continue
            for en, fr in zip(en_items, fr_items, strict=True):
                votes.setdefault(en, Counter())[fr] += 1
    return {en: counter.most_common(1)[0][0] for en, counter in votes.items()}


def load_translations(docs: Path) -> Translations:
    """Read every French .po file of the clone. Unreadable files are recorded (ERR-003)."""
    result = Translations()
    all_entries: list[PoEntry] = []
    directory = docs / LOCALE_DIR
    for path in sorted(directory.glob("*.po")) if directory.is_dir() else []:
        try:
            entries = parse_po(path.read_text(encoding="utf-8"))
        except (PoError, UnicodeDecodeError) as exc:
            result.failed_domains[path.stem] = f"{path.name} : {exc}"
            continue
        all_entries += entries
        for entry in entries:
            if entry.fuzzy or not entry.msgid:
                continue
            for page, line in entry.refs:
                result.pages.setdefault(page, {})[line] = (entry.msgid, entry.msgstr)
    result.menu_labels = _menu_labels(all_entries)
    return result
