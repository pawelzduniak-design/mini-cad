from __future__ import annotations

from tests.conftest import require_ocp
from tests.helpers.topology import assert_valid_shape


def test_step_export_import_round_trip(tmp_path) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.io_step import export_step, import_step

    path = tmp_path / "box.step"
    export_step(make_box(20.0, 20.0, 20.0), path)
    imported = import_step(path)

    assert path.exists()
    assert path.stat().st_size > 0
    assert_valid_shape(imported)
