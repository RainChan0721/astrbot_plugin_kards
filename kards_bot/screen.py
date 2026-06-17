import os
import re
import json
import subprocess
import logging
import sys
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import mss as mss_lib
except ImportError:
    mss_lib = None

logger = logging.getLogger(__name__)

WINDOW_TITLE_PATTERNS = [
    re.compile(r"kards", re.IGNORECASE),
    re.compile(r"1939", re.IGNORECASE),
]


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _find_window_pygetwindow() -> Optional[dict]:
    try:
        import pygetwindow as gw
        matches = gw.getWindowsWithTitle("KARDS")
        if not matches:
            for pat in WINDOW_TITLE_PATTERNS:
                for w in gw.getAllWindows():
                    if pat.search(w.title):
                        matches.append(w)
                        break
                if matches:
                    break
        if matches:
            w = matches[0]
            return {
                "x": w.left or 0,
                "y": w.top or 0,
                "width": w.width or 0,
                "height": w.height or 0,
            }
    except Exception as exc:
        logger.debug("pygetwindow failed: %s", exc)
    return None


def _find_window_hyprctl() -> Optional[dict]:
    try:
        result = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        clients = json.loads(result.stdout)
        for client in clients:
            title = client.get("title", "")
            for pattern in WINDOW_TITLE_PATTERNS:
                if pattern.search(title):
                    return client
    except Exception as exc:
        logger.debug("hyprctl failed: %s", exc)
    return None


def _find_window_xdotool() -> Optional[dict]:
    try:
        for client in subprocess.run(
            ["xdotool", "search", "--name", ""],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().split("\n"):
            if not client:
                continue
            name = subprocess.run(
                ["xdotool", "getwindowname", client],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip()
            for pattern in WINDOW_TITLE_PATTERNS:
                if pattern.search(name):
                    geo = subprocess.run(
                        ["xdotool", "getwindowgeometry", client],
                        capture_output=True, text=True, timeout=3,
                    )
                    pos = subprocess.run(
                        ["xdotool", "getwindowposition", client],
                        capture_output=True, text=True, timeout=3,
                    )
                    size_m = re.search(r"(\d+)x(\d+)", geo.stdout)
                    pos_m = re.search(r"(\d+),(\d+)", pos.stdout)
                    if size_m and pos_m:
                        return {
                            "x": int(pos_m.group(1)),
                            "y": int(pos_m.group(2)),
                            "width": int(size_m.group(1)),
                            "height": int(size_m.group(2)),
                        }
    except Exception as exc:
        logger.debug("xdotool failed: %s", exc)
    return None


def _np_from_pil(pil_img) -> np.ndarray:
    arr = np.array(pil_img)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if cv2 else arr[:, :, :3]


class ScreenCapturer:
    def __init__(self, window_title: str = "KARDS"):
        self.window_title = window_title
        self._platform = _platform()
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        if self._platform == "windows":
            if mss_lib is not None:
                return "mss"
            return "pyautogui"

        if self._platform == "darwin":
            if mss_lib is not None:
                return "mss"
            return "darwin_fallback"

        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            if subprocess.run(["which", "grim"], capture_output=True).returncode == 0:
                return "grim"
            return "wayland"

        if mss_lib is not None:
            return "mss"
        return "x11_fallback"

    def find_window(self) -> Optional[dict]:
        if self._platform == "windows":
            return _find_window_pygetwindow()
        if self._platform == "darwin":
            return _find_window_pygetwindow()
        window = _find_window_hyprctl()
        if window:
            return window
        return _find_window_xdotool()

    def capture(self) -> Optional[np.ndarray]:
        window = self.find_window()
        if window:
            x = window.get("x", 0) or 0
            y = window.get("y", 0) or 0
            w = window.get("width", 0) or 0
            h = window.get("height", 0) or 0
            if w > 0 and h > 0:
                return self._capture_region(x, y, w, h)
        return self._capture_fullscreen()

    def _capture_region(self, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
        if self._backend == "grim":
            return self._grim_capture(f"{x},{y} {w}x{h}")
        if self._backend == "mss" and mss_lib is not None:
            try:
                with mss_lib.mss() as sct:
                    monitor = {"left": x, "top": y, "width": w, "height": h}
                    img = sct.grab(monitor)
                    return np.array(img)[:, :, :3]
            except Exception as exc:
                logger.error("mss region capture failed: %s", exc)
                return None
        return self._capture_fullscreen()

    def _capture_fullscreen(self) -> Optional[np.ndarray]:
        if self._backend == "grim":
            return self._grim_capture()
        if self._backend == "mss" and mss_lib is not None:
            try:
                with mss_lib.mss() as sct:
                    img = sct.grab(sct.monitors[0])
                    return np.array(img)[:, :, :3]
            except Exception as exc:
                logger.error("mss fullscreen capture failed: %s", exc)
                return None
        if self._backend in ("darwin_fallback", "x11_fallback", "pyautogui", "wayland"):
            return self._pyautogui_screenshot()
        return None

    def _pyautogui_screenshot(self) -> Optional[np.ndarray]:
        try:
            import pyautogui
            img = pyautogui.screenshot()
            return _np_from_pil(img)
        except Exception as exc:
            logger.error("pyautogui screenshot failed: %s", exc)
            return None

    @staticmethod
    def _grim_capture(geometry: str = "") -> Optional[np.ndarray]:
        if cv2 is None:
            logger.error("opencv-python not installed")
            return None
        try:
            cmd = ["grim"]
            if geometry:
                cmd.extend(["-g", geometry])
            cmd.append("-")
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode != 0:
                return None
            img_arr = np.frombuffer(result.stdout, np.uint8)
            return cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        except Exception as exc:
            logger.error("grim capture failed: %s", exc)
            return None
