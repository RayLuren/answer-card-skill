from pathlib import Path

import pytest

from answercard.layout import question_needspace
from answercard.render_tex import (
    _front_page_asset_path,
    build_score_table,
    question_title_suffix,
    render_spec,
    render_tex,
)
from answercard.schema import load_spec
from answercard.schema import BlockSpec
from answercard.schema import QuestionSpec


def test_render_tex_contains_questions_and_blocks_without_answers(tmp_path: Path) -> None:
    output_path = tmp_path / "answercard.tex"

    render_tex("spec/qspec.sample.yaml", output_path)

    tex = output_path.read_text(encoding="utf-8")
    assert r"\setmainfont{Times New Roman}" in tex
    assert r"\setCJKmainfont[AutoFakeBold=3]{SimSun}" in tex
    assert r"\newcommand{\BodyFont}{\fontsize{10.5pt}{12.5pt}\selectfont\bfseries}" in tex
    assert r"\newcommand{\QuestionTitleFont}{\fontsize{10.5pt}{12.5pt}\selectfont\bfseries}" in tex
    assert r"\newcommand{\AnswerLabelFont}{\fontsize{10pt}{12pt}\selectfont\bfseries}" in tex
    assert r"\setlength{\footskip}{7mm}" in tex
    assert r"\def\@oddfoot{\hfil{\QuestionTitleFont\thepage}\hfil}%" in tex
    assert r"\let\@evenfoot\@oddfoot" in tex
    assert r"\pagestyle{answercard}" in tex
    assert r"\pagestyle{empty}" not in tex
    assert r"\setlength{\QuestionTableGap}{0.5mm}" in tex
    assert r"{\centering\LARGE\bfseries" not in tex
    assert "第39届 Chemy 化学奥林匹克模拟试题1答题纸" not in tex
    assert r"\QuestionTitle{1}{元素化学}{22}" in tex
    assert r"\QuestionTitle{2}{氟代试剂}{7}" in tex
    assert r"{\QuestionTitleFont 第 #1 题 #2（#3 分\if\relax\detokenize{#4}\relax\else，占 #4\%\fi）。}\par" in tex
    assert r"\nopagebreak[4]%" in tex
    assert r"\newcommand{\QuestionTitle}[4]{%" in tex
    assert r"\newcommand{\QuestionTitle}[4]{%" + "\n" + r"  \vspace" not in tex
    assert r"\newcolumntype{L}{>{\arraybackslash}p{\AnswerLabelWidth}}" in tex
    assert r"\usepackage{longtable}" not in tex
    assert r"\newcommand{\NeedAnswerSpace}[1]{%" not in tex
    assert r"\setlength{\LTpre}{0pt}" not in tex
    assert r"\newcommand{\AnswerTableStart}{%" in tex
    assert r"\newcommand{\AnswerLabelCell}[2]{%" in tex
    assert r"\parbox[c][#2][c]{\AnswerLabelWidth}" in tex
    assert r"\vbox to #2{%" not in tex
    assert r"\newcommand{\AnswerBox}[2]{%" not in tex
    assert r"\usepackage{tabularx}" in tex
    assert tex.count(r"\AnswerTableStart") == 3
    assert tex.count(r"\AnswerTableEnd") == 3
    assert tex.count(r"\begin{tabular}{|L|A|}") == 1
    assert tex.count(r"\end{tabular}") == 1
    assert r"\end{tabular}\par" in tex
    assert r"\begin{longtable}{|L|A|}" not in tex
    assert r"\par\newpage" in tex
    assert tex.count(r"\AnswerRow{") == 8
    assert r"\NeedAnswerSpace{" not in tex
    assert tex.count(r"\NeedAnswerSpace{") == 0
    assert r"\AnswerRow{1-1}{22mm}" in tex
    assert r"\AnswerRow{1-2-2}{42mm}" in tex
    assert r"\AnswerRow{1-4}{55mm}" in tex
    assert r"\AnswerRow{2-1}{35mm}" in tex
    assert r"\AnswerRow{2-2}{45mm}" in tex
    assert r"\newcommand{\AnswerImageRow}[3]{%" in tex
    assert r"\newlength{\AnswerImagePageCenterShift}" in tex
    assert r"height=\dimexpr#2-1.2mm\relax" in tex
    assert r"width=\dimexpr\linewidth-2\AnswerImagePageCenterShift-1.2mm\relax" in tex
    assert r"\QuestionTitle{1}{元素化学}{22}{76}" in tex
    assert r"\QuestionTitle{2}{氟代试剂}{7}{24}" in tex
    assert "第 1 题 元素化学（22 分，占 76%）" not in tex
    assert "第 2 题 氟代试剂（7 分，占 24%）" not in tex
    assert r"\setlength{\arrayrulewidth}{ 0.6pt }" in tex
    assert "答案" not in tex
    assert "参考答案" not in tex


def test_render_tex_uses_absolute_asset_path_when_relative_path_is_impossible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_cross_drive_error(path: object, start: object) -> str:
        raise ValueError("path is on a different drive")

    monkeypatch.setattr("answercard.render_tex.os.path.relpath", raise_cross_drive_error)

    asset_path = _front_page_asset_path(tmp_path / "answercard.tex")

    assert asset_path.endswith("/assets/periodic-table.png")
    assert Path(asset_path).is_absolute()


def test_question_needspace_uses_first_block_height_with_bounds() -> None:
    assert (
        question_needspace(
            QuestionSpec(
                id="4",
                title="钼配合物及其转化",
                score=28,
                blocks=[BlockSpec(id="4-1", kind="equation", height="46mm")],
            )
        )
        == "58mm"
    )
    assert (
        question_needspace(
            QuestionSpec(
                id="1",
                title="Small",
                score=1,
                blocks=[BlockSpec(id="1-1", kind="formula", height="10mm")],
            )
        )
        == "35mm"
    )
    assert (
        question_needspace(
            QuestionSpec(
                id="9",
                title="Large",
                score=30,
                blocks=[BlockSpec(id="9-1", kind="mechanism", height="120mm")],
            )
        )
        == "95mm"
    )


def test_question_title_suffix_hides_generic_extractor_title() -> None:
    assert question_title_suffix("第3题", "3") == ""
    assert question_title_suffix("有机结构", "3") == "有机结构"


def test_render_tex_includes_required_percent(tmp_path: Path) -> None:
    spec_path = tmp_path / "qspec.yaml"
    spec_path.write_text(
        """
schema_version: 1
paper:
  title: Compatibility Test
  page_size: A4
  omit_front_page: true
  total_score: 5
  margin:
    top: 12mm
    bottom: 12mm
    left: 10mm
    right: 10mm
style:
  label_width: 13mm
  border_width: 0.6pt
  box_gap: 1.5mm
  title_gap: 2mm
questions:
  - id: "3"
    title: "Old Question"
    score: 5
    percent: 100
    blocks:
      - id: "3"
        kind: "equation"
        height: "20mm"
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "answercard.tex"

    render_tex(spec_path, output_path)

    tex = output_path.read_text(encoding="utf-8")
    assert r"\QuestionTitle{3}{Old Question}{5}{100}" in tex
    assert r"\AnswerRow{3}{20mm}" in tex


def test_render_spec_formats_page_top_spacer_as_a_latex_dimension() -> None:
    spec = load_spec("spec/qspec.sample.yaml")

    tex = render_spec(spec, page_top_spacers_mm=[0.0, 4.76])

    assert r"\vspace*{4.76mm}" in tex
    assert r"\vspace*{4.76}mm}" not in tex


def test_render_tex_includes_front_page_only_when_not_omitted(tmp_path: Path) -> None:
    spec_path = tmp_path / "qspec.yaml"
    spec_path.write_text(
        """
schema_version: 1
paper:
  title: Visible Front Page
  page_size: A4
  omit_front_page: false
  total_score: 5
  margin:
    top: 12mm
    bottom: 12mm
    left: 10mm
    right: 10mm
style:
  label_width: 13mm
  border_width: 0.6pt
  box_gap: 1.5mm
  title_gap: 2mm
questions:
  - id: "1"
    title: "Question"
    score: 5
    percent: 100
    blocks:
      - id: "1-1"
        kind: "short_answer"
        height: "30mm"
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "answercard.tex"

    render_tex(spec_path, output_path)

    tex = output_path.read_text(encoding="utf-8")
    assert "Visible Front Page" in tex
    assert r"\newgeometry{" in tex
    assert r"*{2}{Y|}" in tex
    assert "原始分" in tex
    assert "赋分" in tex
    assert r"\includegraphics[width=148mm,keepaspectratio]" in tex
    assert r"\restoregeometry" in tex
    assert tex.index("Visible Front Page") < tex.index(r"\QuestionTitle{1}{Question}{5}{100}")


def test_score_table_view_is_derived_only_from_validated_qspec() -> None:
    spec = load_spec("spec/qspec.sample.yaml")

    score_table = build_score_table(spec)

    assert score_table.column_count == 3
    assert score_table.raw_total == 29
    assert score_table.assigned_total == 100
    assert [(item.id, item.raw_score, item.assigned_score) for item in score_table.questions] == [
        ("1", 22, 76),
        ("2", 7, 24),
    ]
