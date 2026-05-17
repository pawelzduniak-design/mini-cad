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


@pytest.mark.visual
@pytest.mark.parametrize(
    "scenario",
    ("maximized_viewport", "reactivated_viewport", "resize_cycles"),
)
def test_window_resize_cycles_keep_viewport_non_black(
    scenario: str, tmp_path: Path
) -> None:
    """Guards against the known OCC+Qt OpenGL blackout after window state changes.

    Each scenario opens the CAD window, runs a sequence of size/activation
    changes (maximize, restore, resize, reactivate), then captures the
    viewport. A blacked-out viewport surfaces as a very low unique_colors
    count and a high black_ratio in the captured region metrics.
    """
    require_visual_enabled()

    from dev.visual_window_probe import run_probe

    report = run_probe(
        Namespace(
            scenario=scenario,
            out_dir=str(tmp_path / "screenshots"),
            report=str(tmp_path / "report.json"),
            width=960,
            height=640,
            fail_on_problems=False,
        )
    )

    capture = report["captures"][0]
    assert Path(capture["screenshot"]).exists()
    viewport_metrics = capture["regions"]["viewport"]
    assert viewport_metrics["black_ratio"] < 0.05, (
        f"Viewport black_ratio={viewport_metrics['black_ratio']} for "
        f"scenario={scenario}; screenshot={capture['screenshot']}"
    )
    assert viewport_metrics["unique_colors"] > 8, (
        f"Viewport unique_colors={viewport_metrics['unique_colors']} for "
        f"scenario={scenario}; screenshot={capture['screenshot']}"
    )
    assert not capture["detected"]["black_components"], (
        f"Detected large black components for scenario={scenario}: "
        f"{capture['detected']['black_components']}"
    )
