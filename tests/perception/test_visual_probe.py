from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from tests.conftest import require_visual_enabled


@pytest.mark.visual
def test_startup_visual_probe_has_no_obvious_viewport_failures(tmp_path: Path) -> None:
    require_visual_enabled()

    from dev.visual_window_probe import run_probe

    report = run_probe(
        Namespace(
            scenario="startup",
            out_dir=str(tmp_path / "screenshots"),
            report=str(tmp_path / "report.json"),
            width=960,
            height=640,
            fail_on_problems=False,
        )
    )

    assert report["problems"] == []
    capture = report["captures"][0]
    assert Path(capture["screenshot"]).exists()
    assert capture["regions"]["viewport"]["unique_colors"] > 8
    assert capture["regions"]["viewport"]["black_ratio"] < 0.05
