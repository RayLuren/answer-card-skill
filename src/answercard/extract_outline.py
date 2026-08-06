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

_QUESTION_BODY_PREFIXES = (
    "写出",
    "计算",
    "说明",
    "回答",
    "完成",
    "画出",
    "指出",
    "简述",
    "判断",
    "选择",
    "解释",
    "推导",
    "求出",
    "求",
    "请",
    "已知",
    "现有",
    "下列",
    "将",
    "当",
    "若",
    "有一类",
    "有一种",
    "最近",
    "设",
    "给出",
    "分别",
    "试",
    "根据",
)

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
    from_ocr: bool = False


def extract_outline(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    ocr_fallback: bool = True,
    ocr_dpi: int = 220,
) -> Path:
    """Extract outline metadata from a PDF and write it as pretty UTF-8 JSON."""

    source = Path(pdf_path)
    pages = extract_pdf_text(source, ocr_fallback=ocr_fallback, ocr_dpi=ocr_dpi)
    outline = parse_outline(pages, source=str(source))
    ocr_pages = {page.page for page in pages if page.from_ocr}
    if ocr_pages:
        outline = _normalize_ocr_outline(outline, ocr_pages=ocr_pages)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(outline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def extract_pdf_text(
    pdf_path: str | Path,
    *,
    ocr_fallback: bool = True,
    ocr_dpi: int = 220,
) -> list[TextPage]:
    """Return page text, using transient OCR only for pages with no text layer."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required to extract PDF text. Install project dependencies first.") from exc

    reader = PdfReader(str(pdf_path))
    pages: list[TextPage] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(TextPage(page=index, text=page.extract_text() or ""))
    blank_page_numbers = [page.page for page in pages if not page.text.strip()]
    if ocr_fallback and blank_page_numbers:
        from answercard.ocr_text import extract_ocr_page_texts

        ocr_texts = extract_ocr_page_texts(pdf_path, blank_page_numbers, dpi=ocr_dpi)
        pages = [
            TextPage(
                page=page.page,
                text=ocr_texts.get(page.page, ""),
                from_ocr=page.page in ocr_texts,
            )
            if page.page in blank_page_numbers
            else page
            for page in pages
        ]
    return pages


def _numeric_id_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("-"))


def _is_plausible_ocr_item_id(value: str) -> bool:
    parts = value.split("-")
    return len(parts) >= 2 and all(part.isdigit() and 1 <= int(part) <= 99 for part in parts)


def _normalize_ocr_outline(
    outline: dict[str, Any],
    *,
    ocr_pages: set[int],
) -> dict[str, Any]:
    """Merge safe OCR duplicates and restore numeric hierarchy order."""

    merged: dict[str, dict[str, Any]] = {}
    for raw_question in outline["questions"]:
        question_id = raw_question["id"]
        existing = merged.get(question_id)
        if existing is None:
            merged[question_id] = {
                **raw_question,
                "items": list(raw_question["items"]),
            }
            continue

        existing_score = existing.get("score")
        duplicate_score = raw_question.get("score")
        if existing_score is not None and duplicate_score is not None and existing_score != duplicate_score:
            raise ValueError("OCR duplicate question score conflict")
        if existing_score is None:
            existing["score"] = duplicate_score
        existing["items"].extend(raw_question["items"])

    questions: list[dict[str, Any]] = []
    for question_id in sorted(merged, key=_numeric_id_key):
        question = merged[question_id]
        items_by_id = {
            item["id"]: item
            for item in question["items"]
            if item["page"] not in ocr_pages or _is_plausible_ocr_item_id(item["id"])
        }
        leaf_ids = set(leaf_item_ids(items_by_id))
        if any(item["page"] in ocr_pages for item in items_by_id.values()):
            ordered_ids = sorted(leaf_ids, key=_numeric_id_key)
        else:
            ordered_ids = [item["id"] for item in question["items"] if item["id"] in leaf_ids]
        question["items"] = [items_by_id[item_id] for item_id in ordered_ids]
        questions.append(question)

    return {"source": outline.get("source"), "questions": questions}


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
            raw_title = heading.group(2).strip()
            title = _clean_title(raw_title, question_id)
            if not _is_scoring_note_title(raw_title) and not _is_scoring_note_title(title):
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
    if before.strip():
        return False
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
    """Return only an explicit nearby major-question summary.

    Printed score metadata may appear before or after the summary.  Text left
    on the heading line after removing that metadata is not automatically a
    title: answer keys often begin the question body on the same line.  Keep a
    concise title-like phrase verbatim, otherwise use the generic sentinel that
    the renderer suppresses.
    """

    raw = raw_title.strip()
    score_matches = [
        match
        for pattern in (TOTAL_SCORE_RE, PAREN_SCORE_RE)
        for match in pattern.finditer(raw)
    ]
    if score_matches:
        score_match = min(score_matches, key=lambda match: match.start())
        candidates = (
            raw[: score_match.start()],
            raw[score_match.end() :],
        )
    else:
        candidates = (raw,)

    for candidate in candidates:
        title = candidate.strip(" ：:，,。")
        if _looks_like_question_summary(title):
            return title
    return f"第{question_id}题"


def _looks_like_question_summary(value: str) -> bool:
    if not value or len(value.replace(" ", "")) > 36:
        return False
    if re.search(r"[。！？；，,]", value):
        return False
    if value.startswith(_QUESTION_BODY_PREFIXES):
        return False
    if re.search(r"(?:\s|^)(?:是|为)(?:一|由|用|指)", value):
        return False
    return True


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
