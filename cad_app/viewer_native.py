"""Native window helpers for OCP viewer setup.

OCCT exposes different native ``Aspect_Window`` implementations per platform.
Qt gives us a native ``winId()``; this module wraps that handle in the matching
OCCT window class.
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any


def create_native_handle_capsule(win_id: Any) -> Any:
    if type(win_id).__name__ == "PyCapsule":
        return win_id

    ctypes.pythonapi.PyCapsule_New.restype = ctypes.py_object
    ctypes.pythonapi.PyCapsule_New.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
    ]
    return ctypes.pythonapi.PyCapsule_New(ctypes.c_void_p(int(win_id)), None, None)


def create_occt_window(display_connection: Any, win_id: Any) -> tuple[Any, Any | None]:
    """Return ``(occt_window, handle_capsule)`` for the current platform.

    Windows' ``WNT_Window`` expects a PyCapsule around the HWND. Linux/X11's
    ``Xw_Window`` wraps the X drawable directly and also needs OCCT's
    ``Aspect_DisplayConnection``. Wayland is intentionally not treated as a
    native target here because OCCT's Xw backend needs an X11 window; use Qt's
    ``xcb`` platform plugin or run under Xvfb for Linux automation.
    """

    if sys.platform == "win32":
        from OCP.WNT import WNT_Window

        capsule = create_native_handle_capsule(win_id)
        return WNT_Window(capsule), capsule

    if sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "Linux CAD viewport requires an X11 display. Set DISPLAY and run "
                "with Qt's xcb platform plugin, or use xvfb-run in headless CI."
            )
        try:
            from OCP.Xw import Xw_Window
        except ImportError as exc:  # pragma: no cover - depends on Linux wheel
            raise RuntimeError(
                "The installed OCP package does not expose Xw_Window. Install a "
                "Linux cadquery-ocp/OCP build with X11/GLX support."
            ) from exc
        return Xw_Window(display_connection, int(win_id)), None

    raise RuntimeError(f"Unsupported CAD viewport platform: {sys.platform}")
