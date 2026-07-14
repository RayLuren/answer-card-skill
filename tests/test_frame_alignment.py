import json
from pathlib import Path

import pytest

from answercard.frame_alignment import (
    FrameMeasurement,
    alignment_corrections,
    alignment_spreads,
    load_alignment_pass_summaries,
)


def test_load_alignment_pass_summaries_records_standard_and_result(tmp_path: Path) -> None:
    report = tmp_path / "frame_alignment.json"
    report.write_text(
        json.dumps(
            {
                "passes": [
                    {"pass": 0, "top_spread_mm": 4.2, "bottom_spread_mm": 48.0},
                    {"pass": 1, "top_spread_mm": 0.4, "bottom_spread_mm": 1.2},
                    {"pass": 2, "top_spread_mm": 0.3, "bottom_spread_mm": 1.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_alignment_pass_summaries(report, tolerance_mm=1.1) == [
        {
            "pass": 0,
            "top_spread_mm": 4.2,
            "bottom_spread_mm": 48.0,
            "tolerance_mm": 1.1,
            "passed": False,
        },
        {
            "pass": 1,
            "top_spread_mm": 0.4,
            "bottom_spread_mm": 1.2,
            "tolerance_mm": 1.1,
            "passed": False,
        },
        {
            "pass": 2,
            "top_spread_mm": 0.3,
            "bottom_spread_mm": 1.0,
            "tolerance_mm": 1.1,
            "passed": True,
        },
    ]


def test_alignment_corrections_use_a_fixed_target_and_allow_reverse_adjustment() -> None:
    measurements = [
        FrameMeasurement(page=1, top_from_page_top_mm=16.8, bottom_from_page_bottom_mm=17.3),
        FrameMeasurement(page=2, top_from_page_top_mm=20.6, bottom_from_page_bottom_mm=13.1),
    ]

    height_delta, top_delta = alignment_corrections(measurements, target_mm=16.8)

    assert top_delta == pytest.approx([0.0, -3.8])
    assert height_delta == pytest.approx([0.5, 0.1])


def test_alignment_spreads_report_top_and_bottom_ranges() -> None:
    measurements = [
        FrameMeasurement(page=1, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=16.2),
        FrameMeasurement(page=2, top_from_page_top_mm=16.5, bottom_from_page_bottom_mm=16.8),
    ]

    top_spread, bottom_spread = alignment_spreads(measurements)

    assert top_spread == 0.5
    assert round(bottom_spread, 1) == 0.6


def test_alignment_spreads_can_exclude_the_last_page_bottom() -> None:
    measurements = [
        FrameMeasurement(page=1, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=16.2),
        FrameMeasurement(page=2, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=16.5),
        FrameMeasurement(page=3, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=90.0),
    ]

    top_spread, bottom_spread = alignment_spreads(measurements, include_last_bottom=False)

    assert top_spread == 0.0
    assert round(bottom_spread, 1) == 0.3
