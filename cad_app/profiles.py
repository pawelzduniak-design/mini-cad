"""Lightweight local profiles used by direct tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CircleProfile:
    radius: float

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise ValueError("Circle radius must be positive.")
