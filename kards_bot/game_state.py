from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import cv2

logger = logging.getLogger(__name__)


@dataclass
class CardInfo:
    index: int = 0
    name: str = ""
    cost: int = 0
    attack: int = 0
    defense: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass
class GameState:
    my_health: int = 0
    my_kredits: int = 0
    my_hand: list[CardInfo] = field(default_factory=list)
    my_units: list[CardInfo] = field(default_factory=list)
    opp_health: int = 0
    opp_kredits: int = 0
    opp_hand_count: int = 0
    opp_units: list[CardInfo] = field(default_factory=list)
    turn: str = ""  # "my" or "opp"
    screenshot: Optional[np.ndarray] = None

    def to_text(self) -> str:
        lines = []
        lines.append(f"己方: 生命={self.my_health} 费用={self.my_kredits}")
        if self.my_hand:
            lines.append("手牌:")
            for i, card in enumerate(self.my_hand):
                lines.append(f"  [{i}] {card.name} ({card.cost}K) {card.attack}/{card.defense}")
        if self.my_units:
            lines.append("己方战场:")
            for card in self.my_units:
                lines.append(f"  {card.name} ({card.cost}K) {card.attack}/{card.defense}")
        lines.append(f"对手: 生命={self.opp_health} 手牌={self.opp_hand_count}")
        if self.opp_units:
            lines.append("对手战场:")
            for card in self.opp_units:
                lines.append(f"  {card.name} {card.attack}/{card.defense}")
        return "\n".join(lines)


class GameStateParser:
    def __init__(self):
        self._hand_roi: Optional[tuple] = None
        self._kredits_roi: Optional[tuple] = None
        self._health_roi: Optional[tuple] = None

    def calibrate(self, screenshot: np.ndarray):
        h, w = screenshot.shape[:2]
        bottom_h = int(h * 0.25)
        left_w = int(w * 0.1)
        self._hand_roi = (0, h - bottom_h, w, bottom_h)
        self._kredits_roi = (left_w, h - bottom_h - 20, 80, 30)
        self._health_roi = (left_w, h - bottom_h - 50, 60, 25)
        logger.info("calibrated ROIs for %dx%d screenshot", w, h)

    def parse(self, screenshot: np.ndarray, ocr=None) -> GameState:
        state = GameState(screenshot=screenshot)
        h, w = screenshot.shape[:2]

        if self._hand_roi is None:
            self.calibrate(screenshot)

        hand_cards = self._find_hand_cards(screenshot)
        for i, card in enumerate(hand_cards):
            card.index = i
        state.my_hand = hand_cards

        if ocr:
            if self._kredits_roi:
                x, y, kw, kh = self._kredits_roi
                if y >= 0 and x >= 0 and y + kh <= h and x + kw <= w:
                    kredits_region = screenshot[y:y+kh, x:x+kw]
                    kredits = ocr.read_numbers(kredits_region)
                    if kredits is not None:
                        state.my_kredits = kredits

            if self._health_roi:
                x, y, hw, hh = self._health_roi
                if y >= 0 and x >= 0 and y + hh <= h and x + hw <= w:
                    health_region = screenshot[y:y+hh, x:x+hw]
                    health = ocr.read_numbers(health_region)
                    if health is not None:
                        state.my_health = health

        return state

    def _find_hand_cards(self, screenshot: np.ndarray) -> list[CardInfo]:
        h, w = screenshot.shape[:2]
        hand_y_start = int(h * 0.78)
        hand_y_end = int(h * 0.95)
        hand_region = screenshot[hand_y_start:hand_y_end, :]

        gray = cv2.cvtColor(hand_region, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(thresh, kernel, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        cards = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            area = cw * ch
            card_roi_h = hand_y_end - hand_y_start
            if area < 2000 or ch < card_roi_h * 0.3 or cw < 30:
                continue
            cards.append(CardInfo(
                x=x,
                y=hand_y_start + y,
                width=cw,
                height=ch,
            ))
        cards.sort(key=lambda c: c.x)
        return cards
