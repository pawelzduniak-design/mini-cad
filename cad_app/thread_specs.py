"""Thread presets and validation helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

THREAD_MODES = ("modeled", "cosmetic")
THREAD_TYPES = ("auto", "external", "internal")


@dataclass(frozen=True)
class ThreadPreset:
    """Manufacturing-oriented thread dimensions in millimeters."""

    standard: str
    size: str
    major_diameter: float
    pitch: float
    minor_diameter: float

    @property
    def name(self) -> str:
        return f"{self.standard} {self.size}"

    @property
    def modeled_depth(self) -> float:
        return max((self.major_diameter - self.minor_diameter) / 2.0, 0.001)


def _iso_thread(size: str, major_diameter: float, pitch: float) -> ThreadPreset:
    return ThreadPreset(
        standard="ISO",
        size=size,
        major_diameter=major_diameter,
        pitch=pitch,
        minor_diameter=major_diameter - _thread_diameter_delta(pitch),
    )


def _unc_thread(size: str, major_inch: float, threads_per_inch: int) -> ThreadPreset:
    major_diameter = major_inch * 25.4
    pitch = 25.4 / threads_per_inch
    return ThreadPreset(
        standard="UNC",
        size=size,
        major_diameter=major_diameter,
        pitch=pitch,
        minor_diameter=major_diameter - _thread_diameter_delta(pitch),
    )


def _thread_diameter_delta(pitch: float) -> float:
    """Return a practical major/minor diameter delta for a 60 degree thread."""
    return 2.0 * thread_depth_from_pitch(pitch)


def thread_depth_from_pitch(pitch: float) -> float:
    """Return radial modeled depth for a standard 60 degree thread."""
    if pitch <= 0:
        raise ValueError("Thread pitch must be positive.")
    return math.sqrt(3.0) * pitch * 0.375


THREAD_PRESETS: tuple[ThreadPreset, ...] = (
    _iso_thread("M3x0.5", 3.0, 0.5),
    _iso_thread("M4x0.7", 4.0, 0.7),
    _iso_thread("M5x0.8", 5.0, 0.8),
    _iso_thread("M6x1.0", 6.0, 1.0),
    _iso_thread("M8x1.25", 8.0, 1.25),
    _iso_thread("M10x1.5", 10.0, 1.5),
    _iso_thread("M12x1.75", 12.0, 1.75),
    _iso_thread("M16x2.0", 16.0, 2.0),
    _unc_thread("#4-40", 0.112, 40),
    _unc_thread("#6-32", 0.138, 32),
    _unc_thread("#8-32", 0.164, 32),
    _unc_thread("#10-24", 0.190, 24),
    _unc_thread("1/4-20", 0.250, 20),
    _unc_thread("5/16-18", 0.3125, 18),
    _unc_thread("3/8-16", 0.375, 16),
    _unc_thread("1/2-13", 0.500, 13),
)


def thread_preset_names() -> tuple[str, ...]:
    return ("Custom",) + tuple(preset.name for preset in THREAD_PRESETS)


def thread_preset_by_name(name: str) -> ThreadPreset | None:
    if name == "Custom":
        return None
    for preset in THREAD_PRESETS:
        if preset.name == name:
            return preset
    raise ValueError(f"Unknown thread preset: {name}")


def matching_thread_preset_for_edge_diameter(
    edge_diameter: float,
    *,
    thread_type: str = "auto",
) -> ThreadPreset | None:
    """Return a preset only when it is compatible with the selected edge."""
    if edge_diameter <= 0:
        raise ValueError("Thread edge diameter must be positive.")
    if thread_type not in THREAD_TYPES:
        raise ValueError(f"Unsupported thread type: {thread_type}")

    matches: list[tuple[float, ThreadPreset]] = []
    for preset in THREAD_PRESETS:
        candidates = _preset_candidate_diameters(preset, thread_type)
        tolerance = _thread_profile_tolerance(preset.pitch, candidates)
        distance = min(abs(edge_diameter - candidate) for candidate in candidates)
        if distance <= tolerance:
            matches.append((distance, preset))
    if not matches:
        return None
    return min(matches, key=lambda match: match[0])[1]


def thread_parameters_from_preset(preset: ThreadPreset) -> dict[str, float | str]:
    return {
        "standard": preset.standard,
        "size": preset.size,
        "major_diameter": preset.major_diameter,
        "minor_diameter": preset.minor_diameter,
        "pitch": preset.pitch,
        "depth": preset.modeled_depth,
    }


def normalized_thread_parameters(
    *,
    pitch: float,
    length: float,
    depth: float,
    mode: str = "modeled",
    thread_type: str = "auto",
    standard: str = "custom",
    size: str = "custom",
    major_diameter: float | None = None,
    minor_diameter: float | None = None,
) -> dict[str, float | str | None]:
    if mode not in THREAD_MODES:
        raise ValueError(f"Unsupported thread mode: {mode}")
    if thread_type not in THREAD_TYPES:
        raise ValueError(f"Unsupported thread type: {thread_type}")
    if pitch <= 0:
        raise ValueError("Thread pitch must be positive.")
    if length <= 0:
        raise ValueError("Thread length must be positive.")
    if depth <= 0:
        raise ValueError("Thread depth must be positive.")
    if major_diameter is not None and major_diameter <= 0:
        raise ValueError("Thread major diameter must be positive.")
    if minor_diameter is not None and minor_diameter <= 0:
        raise ValueError("Thread minor diameter must be positive.")
    if (
        major_diameter is not None
        and minor_diameter is not None
        and minor_diameter >= major_diameter
    ):
        raise ValueError("Thread minor diameter must be smaller than major diameter.")
    return {
        "pitch": float(pitch),
        "length": float(length),
        "depth": float(depth),
        "mode": mode,
        "thread_type": thread_type,
        "standard": standard,
        "size": size,
        "major_diameter": major_diameter,
        "minor_diameter": minor_diameter,
    }


def validate_thread_edge_profile(
    params: dict[str, float | str | None],
    edge_diameter: float,
) -> None:
    """Validate that a selected circular edge is compatible with the thread."""
    major_diameter = params.get("major_diameter")
    minor_diameter = params.get("minor_diameter")
    if major_diameter is None and minor_diameter is None:
        return
    pitch = float(params["pitch"])
    thread_type = str(params.get("thread_type", "auto"))
    candidates: list[float] = []
    if thread_type in {"auto", "external"} and major_diameter is not None:
        candidates.append(float(major_diameter))
    if thread_type in {"auto", "internal"}:
        if minor_diameter is not None:
            candidates.append(float(minor_diameter))
        elif major_diameter is not None:
            candidates.append(float(major_diameter))
    if not candidates:
        return
    tolerance = _thread_profile_tolerance(pitch, candidates)
    if all(abs(edge_diameter - candidate) > tolerance for candidate in candidates):
        expected = " or ".join(f"{candidate:.2f} mm" for candidate in candidates)
        raise ValueError(
            "Selected circular edge diameter "
            f"{edge_diameter:.2f} mm does not match thread profile {expected}."
        )


def _preset_candidate_diameters(
    preset: ThreadPreset,
    thread_type: str,
) -> tuple[float, ...]:
    candidates: list[float] = []
    if thread_type in {"auto", "external"}:
        candidates.append(preset.major_diameter)
    if thread_type in {"auto", "internal"}:
        candidates.append(preset.minor_diameter)
    return tuple(candidates)


def _thread_profile_tolerance(
    pitch: float,
    candidates: list[float] | tuple[float, ...],
) -> float:
    nominal = max(candidates)
    return max(pitch, nominal * 0.15)
