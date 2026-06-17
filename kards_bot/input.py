import os
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


class InputSimulator:
    def __init__(self):
        self._platform = _platform()
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        if self._platform == "windows":
            return "pyautogui"
        if self._platform == "darwin":
            return "pyautogui"
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            if subprocess.run(["which", "ydotool"], capture_output=True).returncode == 0:
                return "ydotool"
            return "wayland"
        return "pyautogui"

    def click(self, x: int, y: int):
        if self._backend == "ydotool":
            self._ydotool_click(x, y)
        elif self._backend == "pyautogui":
            self._pyautogui_click(x, y)
        else:
            logger.warning("no input backend available, cannot click at (%d, %d)", x, y)

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        if self._backend == "ydotool":
            self._ydotool_drag(x1, y1, x2, y2)
        elif self._backend == "pyautogui":
            self._pyautogui_drag(x1, y1, x2, y2)
        else:
            logger.warning("no input backend available, cannot drag")

    @staticmethod
    def _ydotool_click(x: int, y: int):
        try:
            subprocess.run(["ydotool", "mousemove", str(x), str(y)], check=True, timeout=5)
            subprocess.run(["ydotool", "click", "0x1"], check=True, timeout=5)
        except Exception as exc:
            logger.error("ydotool click failed: %s", exc)

    @staticmethod
    def _ydotool_drag(x1: int, y1: int, x2: int, y2: int):
        try:
            subprocess.run(["ydotool", "mousemove", str(x1), str(y1)], check=True, timeout=5)
            subprocess.run(["ydotool", "mousedown", "0x1"], check=True, timeout=5)
            subprocess.run(["ydotool", "mousemove", str(x2), str(y2)], check=True, timeout=5)
            subprocess.run(["ydotool", "mouseup", "0x1"], check=True, timeout=5)
        except Exception as exc:
            logger.error("ydotool drag failed: %s", exc)

    @staticmethod
    def _pyautogui_click(x: int, y: int):
        try:
            import pyautogui
            pyautogui.click(x, y)
        except Exception as exc:
            logger.error("pyautogui click failed: %s", exc)

    @staticmethod
    def _pyautogui_drag(x1: int, y1: int, x2: int, y2: int):
        try:
            import pyautogui
            pyautogui.moveTo(x1, y1)
            pyautogui.drag(x2 - x1, y2 - y1, duration=0.3)
        except Exception as exc:
            logger.error("pyautogui drag failed: %s", exc)
