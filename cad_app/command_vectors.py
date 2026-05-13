"""Small vector helpers for topology rebuild code."""

from __future__ import annotations

from cad_app.command_common import UnsupportedTopologyError


def _average_point(
    points: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    count = float(len(points))
    return (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
        sum(point[2] for point in points) / count,
    )


def _newell_normal(
    points: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    normal_x = 0.0
    normal_y = 0.0
    normal_z = 0.0
    for current, following in zip(points, [*points[1:], points[0]]):
        normal_x += (current[1] - following[1]) * (current[2] + following[2])
        normal_y += (current[2] - following[2]) * (current[0] + following[0])
        normal_z += (current[0] - following[0]) * (current[1] + following[1])
    return normal_x, normal_y, normal_z


def _sub(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return left[0] - right[0], left[1] - right[1], left[2] - right[2]


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _norm(vector: tuple[float, float, float]) -> float:
    return _dot(vector, vector) ** 0.5


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _norm(vector)
    if length == 0:
        raise UnsupportedTopologyError("Cannot normalize a zero vector.")
    return vector[0] / length, vector[1] / length, vector[2] / length


def _scale(
    vector: tuple[float, float, float],
    factor: float,
) -> tuple[float, float, float]:
    return vector[0] * factor, vector[1] * factor, vector[2] * factor
