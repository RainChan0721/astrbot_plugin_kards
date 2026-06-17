from __future__ import annotations

import logging

from .game_state import GameState

logger = logging.getLogger(__name__)


class DecisionEngine:
    def __init__(self, llm_caller=None):
        self.llm_caller = llm_caller

    async def decide(self, state: GameState) -> list[str]:
        if self.llm_caller:
            return await self._decide_with_llm(state)
        return self._decide_with_rules(state)

    async def _decide_with_llm(self, state: GameState) -> list[str]:
        prompt = f"""你是一个KARDS卡牌游戏AI。分析当前局面并决定行动。

当前局面:
{state.to_text()}

可能的行动（一次一个，按顺序执行）:
1. play <手牌编号> - 出牌
2. attack <己方单位编号> <目标:opp_hq/对手单位编号> - 攻击
3. end_turn - 结束回合
4. use_hq_power - 使用HQ技能

只输出行动列表,每行一个,不要解释。
示例:
play 0
end_turn
"""
        response = await self.llm_caller(prompt)
        return [a.strip() for a in response.split("\n") if a.strip()]

    def _decide_with_rules(self, state: GameState) -> list[str]:
        actions = []
        playable = [c for c in state.my_hand if c.cost <= state.my_kredits]
        playable.sort(key=lambda c: c.cost, reverse=True)
        for card in playable[:2]:
            actions.append(f"play {card.index}")
        if state.my_units:
            opp_sorted = sorted(state.opp_units, key=lambda u: u.attack or 0, reverse=True)
            for unit in state.my_units:
                if opp_sorted:
                    actions.append(f"attack {unit.index} {opp_sorted[0].index}")
                else:
                    actions.append(f"attack {unit.index} opp_hq")
        actions.append("end_turn")
        return actions
