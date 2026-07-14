"""Render qspec.yaml files to deterministic LaTeX."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from answercard.layout import plan_answer_pages, question_needspace
from answercard.schema import AnswerCardSpec, load_spec


PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_DIR: Final = PROJECT_ROOT / "tex"
DEFAULT_TEMPLATE_NAME: Final = "main.tex.j2"
DEFAULT_OUTPUT_PATH: Final = PROJECT_ROOT / "build" / "answercard.tex"
DEFAULT_FRONT_PAGE_ASSET_PATH: Final = PROJECT_ROOT / "assets" / "periodic-table.png"


_LATEX_ESCAPES: Final = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class ScoreTableQuestion:
    id: str
    raw_score: int | float
    assigned_score: int


@dataclass(frozen=True)
class ScoreTableView:
    questions: tuple[ScoreTableQuestion, ...]
    raw_total: int | float
    assigned_total: int
    column_count: int


def render_tex(
    spec_path: str | Path,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    *,
    template_dir: str | Path = DEFAULT_TEMPLATE_DIR,
    template_name: str = DEFAULT_TEMPLATE_NAME,
    page_height_adjustments_mm: list[float] | None = None,
    page_top_spacers_mm: list[float] | None = None,
) -> Path:
    """Render a qspec.yaml file to a LaTeX document and return the output path."""

    spec = load_spec(spec_path)
    destination = Path(output_path)
    asset_path = _front_page_asset_path(destination)
    tex = render_spec(
        spec,
        template_dir=template_dir,
        template_name=template_name,
        page_height_adjustments_mm=page_height_adjustments_mm,
        page_top_spacers_mm=page_top_spacers_mm,
        front_page_asset_path=asset_path,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(tex, encoding="utf-8", newline="\n")
    return destination


def _front_page_asset_path(destination: Path) -> str:
    try:
        return Path(
            os.path.relpath(DEFAULT_FRONT_PAGE_ASSET_PATH, start=destination.parent)
        ).as_posix()
    except ValueError:
        # Windows cannot express a relative path across drive letters. An
        # absolute forward-slash path is valid inside the template's
        # \detokenize wrapper and keeps external pytest temp dirs usable.
        return DEFAULT_FRONT_PAGE_ASSET_PATH.resolve().as_posix()


def render_spec(
    spec: AnswerCardSpec,
    *,
    template_dir: str | Path = DEFAULT_TEMPLATE_DIR,
    template_name: str = DEFAULT_TEMPLATE_NAME,
    page_height_adjustments_mm: list[float] | None = None,
    page_top_spacers_mm: list[float] | None = None,
    front_page_asset_path: str = "../assets/periodic-table.png",
) -> str:
    """Render an already validated spec object to LaTeX."""

    pages = plan_answer_pages(
        spec,
        page_height_adjustments_mm=page_height_adjustments_mm,
        page_top_spacers_mm=page_top_spacers_mm,
    )
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((#",
        comment_end_string="#))",
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
        undefined=StrictUndefined,
    )
    environment.filters["latex_escape"] = latex_escape
    environment.filters["score_number"] = score_number
    environment.filters["question_needspace"] = question_needspace
    environment.filters["question_title_suffix"] = question_title_suffix
    template = environment.get_template(template_name)
    return template.render(
        spec=spec,
        pages=pages,
        score_table=build_score_table(spec),
        front_page_asset_path=front_page_asset_path,
    )


def build_score_table(spec: AnswerCardSpec) -> ScoreTableView:
    """Build the deterministic front-page score-table view from a validated qspec."""

    questions = tuple(
        ScoreTableQuestion(
            id=question.id,
            raw_score=question.score,
            assigned_score=question.percent,
        )
        for question in spec.questions
    )
    return ScoreTableView(
        questions=questions,
        raw_total=spec.paper.total_score,
        assigned_total=sum(question.assigned_score for question in questions),
        column_count=len(questions) + 1,
    )


def latex_escape(value: object) -> str:
    """Escape plain text for LaTeX while preserving Chinese text unchanged."""

    return "".join(_LATEX_ESCAPES.get(character, character) for character in str(value))


def score_number(value: int | float) -> str:
    """Render validated numeric score metadata without unnecessary trailing zeros."""

    return f"{value:g}"


def question_title_suffix(title: object, question_id: object) -> str:
    """Hide extractor placeholder titles that merely repeat the question number."""

    rendered = str(title).strip()
    if rendered == f"第{question_id}题":
        return ""
    return rendered
