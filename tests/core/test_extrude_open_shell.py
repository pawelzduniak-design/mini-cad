from __future__ import annotations

import pytest

from tests.conftest import require_ocp


def _cylinder(radius: float = 20.0, height: float = 40.0):
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
    )
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt, gp_Vec

    axis = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
    edge = BRepBuilderAPI_MakeEdge(gp_Circ(axis, radius)).Edge()
    wire = BRepBuilderAPI_MakeWire(edge).Wire()
    face = BRepBuilderAPI_MakeFace(wire).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape()


def _cap_face_index(shape, sign: float) -> int:
    """Return the index of the planar cap whose normal points along ``sign*Z``."""
    from cad_app.command_geometry import _face_by_index
    from cad_app.command_topology import _planar_face_normal
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    for index in range(1, face_map.Extent() + 1):
        try:
            normal = _planar_face_normal(_face_by_index(shape, index))
        except Exception:
            continue
        if round(normal.Z(), 2) == sign:
            return index
    raise AssertionError("cap face not found")


def _side_face_index(shape) -> int:
    """Return the index of the (non-planar) cylindrical side face."""
    from cad_app.command_geometry import _face_by_index
    from cad_app.command_topology import _planar_face_normal
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    for index in range(1, face_map.Extent() + 1):
        try:
            _planar_face_normal(_face_by_index(shape, index))
        except Exception:
            return index  # non-planar -> the lateral wall
    raise AssertionError("side face not found")


def test_rotation_alone_keeps_extrude_working() -> None:
    require_ocp()
    from cad_app.command_geometry import _shape_has_solid
    from cad_app.commands import extrude_face, rotate_shape

    cylinder = _cylinder()
    rotated = rotate_shape(cylinder, (0, 0, 0), (0, 1, 0), -5.0)
    result = extrude_face(rotated, _cap_face_index(rotated, 1.0), 10.0)
    assert _shape_has_solid(result)


def test_extrude_reseals_open_shell_with_flat_opening() -> None:
    require_ocp()
    from cad_app.command_geometry import _shape_has_solid
    from cad_app.commands import extrude_face, remove_face

    cylinder = _cylinder()
    # Remove the top cap -> open "cup"; its single planar free boundary
    # can be sealed, so extruding the bottom cap should succeed.
    cup = remove_face(cylinder, _cap_face_index(cylinder, 1.0))
    assert not _shape_has_solid(cup)
    result = extrude_face(cup, _cap_face_index(cup, -1.0), 10.0)
    assert _shape_has_solid(result)


def test_extrude_open_shell_with_curved_opening_raises_clear_error() -> None:
    require_ocp()
    from cad_app.commands import UnsupportedTopologyError, extrude_face, remove_face

    cylinder = _cylinder()
    # Remove the lateral wall -> two detached disks, no flat cap can
    # close the curved opening, so extrude must refuse with a clear error.
    open_shell = remove_face(cylinder, _side_face_index(cylinder))
    with pytest.raises(UnsupportedTopologyError, match="seal"):
        extrude_face(open_shell, _cap_face_index(open_shell, 1.0), 10.0)
