"""Native window helpers for OCP viewer setup."""

from __future__ import annotations

import ctypes
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
