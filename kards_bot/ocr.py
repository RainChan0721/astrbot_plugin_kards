import logging
from typing import Optional

import numpy as np
import cv2

logger = logging.getLogger(__name__)

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


class OcrReader:
    def __init__(self, lang: str = "eng"):
        self.lang = lang
        if not HAS_TESSERACT:
            logger.warning("pytesseract not installed, OCR disabled")

    def preprocess(self, region: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        denoised = cv2.fastNlMeansDenoising(thresh, h=30)
        return denoised

    def read_text(self, region: np.ndarray) -> str:
        if not HAS_TESSERACT:
            return ""
        try:
            processed = self.preprocess(region)
            custom_config = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
            text = pytesseract.image_to_string(processed, config=custom_config, lang=self.lang)
            return text.strip()
        except Exception as exc:
            logger.debug("OCR read_text failed: %s", exc)
            return ""

    def read_card_name(self, region: np.ndarray) -> str:
        if not HAS_TESSERACT:
            return ""
        try:
            processed = self.preprocess(region)
            custom_config = r"--oem 3 --psm 7"
            text = pytesseract.image_to_string(processed, config=custom_config, lang=self.lang)
            return text.strip()
        except Exception as exc:
            logger.debug("OCR read_card_name failed: %s", exc)
            return ""

    def read_numbers(self, region: np.ndarray) -> Optional[int]:
        text = self.read_text(region)
        if not text:
            return None
        digits = "".join(c for c in text if c.isdigit())
        return int(digits) if digits else None
