"""Small runtime platform defaults.

The CAD viewport is backed by OCCT/OpenGL. On Linux, the current OCP bindings
use the X11/GLX ``Xw_Window`` backend, so Qt must create X11 windows. Desktop
Linux sessions can still be Wayland globally; the app opts into Qt's xcb plugin
when an X11 display is available.
"""

from __future__ import annotations

import os
import sys


def configure_platform_environment() -> None:
    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
