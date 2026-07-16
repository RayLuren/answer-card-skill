"""Extract structural answer outline metadata from reference-answer PDFs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

from answercard.item_id_hierarchy import leaf_item_ids


QUESTION_HEADING_RE = re.compile(r"^第\s*([0-9０-９一二三四五六七八九十百]+)\s*题\s*([^\n]*)")
SUBITEM_RE = re.compile(r"(?<![\d-])([1-9]\d*(?:-[1-9]\d*)+)(?![\d-])")
TOTAL_SCORE_RE = re.compile(r"共\s*([0-9０-９]+(?:[.．][0-9０-９]+)?)\s*分")
PAREN_SCORE_RE = re.compile(r"[（(]\s*([0-9０-９]+(?:[.．][0-9０-９]+)?)\s*分(?:[^）)]*)?[）)]")

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", "0123456789.")
_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


@dataclass(frozen=True)
class TextPage:
    page: int
    text: str


def extract_outline(pdf_path: str | Path, output_path: str | Path) -> Path:
    """Extract outline metadata from a PDF and write it as pretty UTF-8 JSON."""

    source = Path(pdf_path)
    outline = parse_outline(extract_pdf_text(source), source=str(source))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def extract_pdf_text(pdf_path: str | Path) -> list[TextPage]:
    """Return one text block per PDF page using pypdf."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required to extract PDF text. Install project dependencies first.") from exc

    reader = PdfReader(str(pdf_path))
    pages: list[TextPage] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(TextPage(page=index, text=page.extract_text() or ""))
    return pages


def parse_outline(pages: Iterable[TextPage], *, source: str | None = None) -> dict[str, Any]:
    """Parse already extracted page text into outline metadata."""

    questions: list[dict[str, Any]] = []
    current_question: dict[str, Any] | None = None
    current_items_by_id: dict[str, dict[str, Any]] = {}
    lines = [
        (text_page.page, line)
        for text_page in pages
        for line in (_normalize_space(raw_line) for raw_line in text_page.text.splitlines())
        if line
    ]

    for line_index, (page, line) in enumerate(lines):
        heading = QUESTION_HEADING_RE.search(line)
        if heading:
            question_id = _normalize_question_id(heading.group(1))
            title = _clean_title(heading.group(2), question_id)
            if not _is_scoring_note_title(title):
                current_question = {
                    "id": question_id,
                    "title": title,
                    "score": _extract_score(line, total_only=True),
                    "page": page,
                    "items": [],
                }
                questions.append(current_question)
                current_items_by_id = {}

        if current_question is not None and current_question["score"] is None:
            score = _extract_score(line, total_only=True)
            if score is not None:
                current_question["score"] = score

        if current_question is None:
            continue

        for item_id in _iter_subitem_ids(line, current_question["id"]):
            if item_id not in current_items_by_id:
                item = {
                    "id": item_id,
                    "page": page,
                }
                current_items_by_id[item_id] = item
                current_question["items"].append(item)

    for question in questions:
        items = question["items"]
        leaf_ids = set(leaf_item_ids(item["id"] for item in items))
        question["items"] = [item for item in items if item["id"] in leaf_ids]

    return {
        "source": source,
        "questions": questions,
    }


def _iter_subitem_ids(line: str, question_id: str) -> Iterable[str]:
    for match in SUBITEM_RE.finditer(line):
        if not _is_valid_subitem_match(line, match, question_id):
            continue
        yield match.group(1)


def _is_valid_subitem_match(line: str, match: re.Match[str], question_id: str) -> bool:
    item_id = match.group(1)
    if not item_id.startswith(f"{question_id}-"):
        return False

    before = line[: match.start()]
    after = line[match.end() :]
    if re.search(r"[×xX*]\s*$", before):
        return False
    if re.match(r"[.．]\d", after):
        return False
    return True


def _extract_score(text: str, *, total_only: bool) -> int | float | None:
    patterns = (TOTAL_SCORE_RE, PAREN_SCORE_RE)
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _parse_number(match.group(1))
    return None


def _clean_title(raw_title: str, question_id: str) -> str:
    title = TOTAL_SCORE_RE.sub("", raw_title)
    title = PAREN_SCORE_RE.sub("", title)
    title = title.strip(" ：:，,。")
    return title or f"第{question_id}题"


def _is_scoring_note_title(title: str) -> bool:
    return title.startswith(("评判分", "评分", "得分")) or "具体细则" in title


def _normalize_question_id(value: str) -> str:
    normalized = value.translate(_FULLWIDTH_DIGITS)
    if normalized.isdigit():
        return str(int(normalized))
    return str(_parse_chinese_number(normalized))


def _parse_number(value: str) -> int | float:
    normalized = value.translate(_FULLWIDTH_DIGITS)
    number = float(normalized)
    return int(number) if number.is_integer() else number


def _parse_chinese_number(value: str) -> int:
    if value in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[value]
    if value == "十":
        return 10
    if "十" in value:
        tens, ones = value.split("十", 1)
        ten_value = _CHINESE_DIGITS.get(tens, 1) if tens else 1
        one_value = _CHINESE_DIGITS.get(ones, 0) if ones else 0
        return ten_value * 10 + one_value
    raise ValueError(f"unsupported Chinese question number: {value}")


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
