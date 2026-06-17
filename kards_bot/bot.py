from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .screen import ScreenCapturer
from .ocr import OcrReader
from .game_state import GameStateParser, GameState
from .ai import DecisionEngine
from .input import InputSimulator

logger = logging.getLogger(__name__)


class KardsBot:
    def __init__(
        self,
        config: Optional[dict] = None,
        llm_caller: Optional[Callable] = None,
    ):
        self.config = config or {}
        self.screen = ScreenCapturer()
        self.ocr = OcrReader()
        self.parser = GameStateParser()
        self.decider = DecisionEngine(llm_caller=llm_caller)
        self.input = InputSimulator()

        self._state: Optional[GameState] = None

    async def capture_and_parse(self) -> Optional[GameState]:
        screenshot = await asyncio.to_thread(self.screen.capture)
        if screenshot is None:
            logger.error("failed to capture screenshot")
            return None
        state = await asyncio.to_thread(self.parser.parse, screenshot, self.ocr)
        self._state = state
        return state

    def capture_and_parse_sync(self) -> Optional[GameState]:
        screenshot = self.screen.capture()
        if screenshot is None:
            logger.error("failed to capture screenshot")
            return None
        state = self.parser.parse(screenshot, self.ocr)
        self._state = state
        return state

    def get_state(self) -> Optional[GameState]:
        return self._state

    async def suggest_actions(self) -> list[str]:
        if self._state is None:
            return ["no state available"]
        return await self.decider.decide(self._state)

    def suggest_actions_sync(self) -> list[str]:
        if self._state is None:
            return ["no state available"]
        try:
            return asyncio.run(self.decider.decide(self._state))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.decider.decide(self._state))
            finally:
                loop.close()

    async def execute_action(self, action: str) -> str:
        parts = action.strip().split()
        if not parts:
            return "empty action"

        cmd = parts[0].lower()

        if cmd == "play":
            return await self._exec_play(parts)
        elif cmd == "attack":
            return await self._exec_attack(parts)
        elif cmd == "end_turn":
            return await self._exec_end_turn()
        elif cmd == "use_hq_power":
            return await self._exec_hq_power()
        else:
            return f"unknown action: {cmd}"

    def execute_action_sync(self, action: str) -> str:
        try:
            return asyncio.run(self.execute_action(action))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.execute_action(action))
            finally:
                loop.close()

    async def _exec_play(self, parts: list[str]) -> str:
        if len(parts) < 2 or not parts[1].isdigit():
            return "usage: play <card_index>"
        card_idx = int(parts[1])
        if self._state is None or card_idx >= len(self._state.my_hand):
            return f"invalid card index {card_idx}"
        card = self._state.my_hand[card_idx]
        center_x = card.x + card.width // 2
        center_y = card.y + card.height // 2
        img_h = self._state.screenshot.shape[0] if self._state.screenshot is not None else 1080
        board_y = int(img_h * 0.5)
        await asyncio.to_thread(self.input.drag, center_x, center_y, center_x, board_y)
        await asyncio.sleep(0.5)
        return f"played card [{card_idx}] {card.name or 'unknown'}"

    async def _exec_attack(self, parts: list[str]) -> str:
        if len(parts) < 2 or not parts[1].isdigit():
            return "usage: attack <unit_index> [target]"
        unit_idx = int(parts[1])
        if self._state is None:
            return "no game state"
        if unit_idx >= len(self._state.my_units):
            return f"invalid unit index {unit_idx}"
        unit = self._state.my_units[unit_idx]
        unit_cx = unit.x + unit.width // 2
        unit_cy = unit.y + unit.height // 2
        await asyncio.to_thread(self.input.click, unit_cx, unit_cy)
        await asyncio.sleep(0.3)

        if len(parts) >= 3 and parts[2].isdigit():
            target_idx = int(parts[2])
            if target_idx < len(self._state.opp_units):
                target = self._state.opp_units[target_idx]
                t_cx = target.x + target.width // 2
                t_cy = target.y + target.height // 2
                await asyncio.to_thread(self.input.click, t_cx, t_cy)
                return f"attacked with unit [{unit_idx}] -> opp_unit [{target_idx}]"

        img_w = self._state.screenshot.shape[1] // 2 if self._state.screenshot is not None else 960
        await asyncio.to_thread(self.input.click, img_w, 50)
        return f"attacked with unit [{unit_idx}] -> opp HQ"

    async def _exec_end_turn(self) -> str:
        if self._state is None or self._state.screenshot is None:
            await asyncio.to_thread(self.input.click, 1820, 1030)
            return "ended turn (default position)"
        h, w = self._state.screenshot.shape[:2]
        await asyncio.to_thread(self.input.click, w - 100, h - 50)
        return "ended turn"

    async def _exec_hq_power(self) -> str:
        if self._state is None or self._state.screenshot is None:
            await asyncio.to_thread(self.input.click, 100, 930)
            return "used HQ power (default position)"
        h = self._state.screenshot.shape[0]
        await asyncio.to_thread(self.input.click, 100, h - 150)
        return "used HQ power"
