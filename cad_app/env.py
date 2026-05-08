"""Runtime dependency checks."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec


@dataclass(frozen=True)
class Dependency:
    module_name: str
    install_name: str


RUNTIME_DEPENDENCIES = (
    Dependency("PySide6", "PySide6"),
    Dependency("OCP", "cadquery-ocp"),
    Dependency("build123d", "build123d"),
)


def missing_dependencies(
    dependencies: tuple[Dependency, ...] = RUNTIME_DEPENDENCIES,
) -> tuple[Dependency, ...]:
    """Return runtime dependencies whose import modules are unavailable."""
    return tuple(dep for dep in dependencies if find_spec(dep.module_name) is None)


def ensure_runtime_dependencies() -> None:
    """Raise a clear error before Qt/OCP initialization if dependencies are missing."""
    missing = missing_dependencies()
    if not missing:
        return

    modules = ", ".join(dep.module_name for dep in missing)
    packages = " ".join(dep.install_name for dep in missing)
    raise RuntimeError(
        "Missing CAD runtime dependencies: "
        f"{modules}. Create an isolated Python 3.11 environment and install: "
        f"python -m pip install {packages}"
    )
