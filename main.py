from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import uuid

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

TASK_TIMEOUT = 60


@register("astrbot_plugin_kards", "雪乃", "让AstrBot能玩Kards卡牌游戏", "0.1.0")
class KardsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = dict(config or {})
        self._pending_actions: list[str] = []
        self._task_queue: list[dict] = []
        self._task_futures: dict[str, asyncio.Future] = {}
        self._access_token = str(self.config.get("access_token", "") or "")

    async def initialize(self):
        register_web_api = getattr(self.context, "register_web_api", None)
        if callable(register_web_api):
            register_web_api(
                "/astrbot_plugin_kards/agent/poll",
                self._api_agent_poll,
                ["POST"],
                "Kards Agent: poll next task",
            )
            register_web_api(
                "/astrbot_plugin_kards/agent/result",
                self._api_agent_result,
                ["POST"],
                "Kards Agent: submit task result",
            )
            logger.info("[Kards] agent API registered, token=%s", bool(self._access_token))
        else:
            logger.warning("[Kards] astrbot does not support register_web_api; agent will not work")

    async def terminate(self):
        for fut in self._task_futures.values():
            if not fut.done():
                fut.cancel()
        self._task_futures.clear()
        self._task_queue.clear()

    def _enqueue_task(self, action: str, args: list[str] = None) -> asyncio.Future:
        task_id = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._task_queue.append({"id": task_id, "action": action, "args": args or []})
        self._task_futures[task_id] = fut
        return fut

    def _complete_task(self, task_id: str, result: dict):
        fut = self._task_futures.pop(task_id, None)
        if fut and not fut.done():
            fut.set_result(result)

    async def _wait_task(self, fut: asyncio.Future, timeout: int = TASK_TIMEOUT) -> dict:
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": "任务超时，确认本地Agent是否在运行喵"}
        except Exception as exc:
            return {"error": str(exc)}

    async def _exec_remote(self, action: str, args: list[str] = None) -> dict:
        fut = self._enqueue_task(action, args)
        return await self._wait_task(fut)

    async def _api_agent_poll(self):
        from quart import jsonify, request
        if self._access_token:
            auth = request.headers.get("Authorization", "")
            if auth.removeprefix("Bearer ") != self._access_token:
                return jsonify({"error": "unauthorized"}), 401
        if not self._task_queue:
            return jsonify({"task": None})
        task = self._task_queue.pop(0)
        return jsonify({"task": task})

    async def _api_agent_result(self):
        from quart import jsonify, request
        if self._access_token:
            auth = request.headers.get("Authorization", "")
            if auth.removeprefix("Bearer ") != self._access_token:
                return jsonify({"error": "unauthorized"}), 401
        data = await request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "invalid payload"})
        task_id = data.get("task_id", "")
        result = data.get("result", {})
        if task_id:
            self._complete_task(task_id, result)
        return jsonify({"status": "ok"})

    @filter.command_group("kards")
    def kards(self):
        pass

    @kards.command("help")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "/kards start - 连接Agent查看局面\n"
            "/kards status - 查看当前战况\n"
            "/kards hand - 查看手牌\n"
            "/kards play <编号> - 出牌\n"
            "/kards attack <编号> [目标] - 攻击\n"
            "/kards endturn - 结束回合\n"
            "/kards suggest - AI给建议\n"
            "/kards apply - 执行AI建议\n"
            "/kards screenshot - 截图"
        )

    @kards.command("start")
    async def start(self, event: AstrMessageEvent):
        result = await self._exec_remote("capture")
        if result.get("error"):
            yield event.plain_result(f"启动失败: {result['error']}")
            return
        yield event.plain_result(f"Kards Bot 已启动!\n\n{result.get('state_text', '')}")

    @kards.command("status")
    async def status(self, event: AstrMessageEvent):
        result = await self._exec_remote("capture")
        if result.get("error"):
            yield event.plain_result(f"获取状态失败: {result['error']}")
            return
        yield event.plain_result(result.get("state_text", "未知"))

    @kards.command("hand")
    async def hand(self, event: AstrMessageEvent):
        result = await self._exec_remote("hand")
        if result.get("error"):
            yield event.plain_result(f"获取手牌失败: {result['error']}")
            return
        cards = result.get("cards", [])
        if not cards:
            yield event.plain_result("手牌为空或无法识别")
            return
        lines = ["手牌:"]
        for c in cards:
            lines.append(f"  [{c['index']}] {c['name']} (费用:{c['cost']}) {c['attack']}/{c['defense']}")
        yield event.plain_result("\n".join(lines))

    @kards.command("play")
    async def play(self, event: AstrMessageEvent, card_index: int):
        result = await self._exec_remote("action", [f"play {card_index}"])
        if result.get("error"):
            yield event.plain_result(f"出牌失败: {result['error']}")
            return
        yield event.plain_result(f"{result.get('result', '')}\n\n{result.get('state_text', '')}")

    @kards.command("attack")
    async def attack(self, event: AstrMessageEvent, unit_index: int, target_index: int = -1):
        action = f"attack {unit_index}"
        if target_index >= 0:
            action += f" {target_index}"
        result = await self._exec_remote("action", [action])
        if result.get("error"):
            yield event.plain_result(f"攻击失败: {result['error']}")
            return
        yield event.plain_result(f"{result.get('result', '')}\n\n{result.get('state_text', '')}")

    @kards.command("endturn")
    async def endturn(self, event: AstrMessageEvent):
        result = await self._exec_remote("action", ["end_turn"])
        if result.get("error"):
            yield event.plain_result(f"结束回合失败: {result['error']}")
            return
        yield event.plain_result(result.get("result", "回合已结束"))

    @kards.command("suggest")
    async def suggest(self, event: AstrMessageEvent):
        result = await self._exec_remote("suggest")
        if result.get("error"):
            yield event.plain_result(f"AI建议失败: {result['error']}")
            return
        actions = result.get("actions", [])
        self._pending_actions = list(actions)
        lines = ["AI 建议的操作:"]
        for i, action in enumerate(actions):
            lines.append(f"  [{i}] {action}")
        lines.append("")
        lines.append("使用 /kards apply 执行所有建议")
        yield event.plain_result("\n".join(lines))

    @kards.command("apply")
    async def apply(self, event: AstrMessageEvent):
        if not self._pending_actions:
            yield event.plain_result("没有待执行的操作，先用 /kards suggest 生成建议")
            return
        results = []
        for action in self._pending_actions:
            result = await self._exec_remote("action", [action])
            results.append(f"> {action}\n  {result.get('result', '?')}")
            await asyncio.sleep(0.5)
        self._pending_actions.clear()
        status = await self._exec_remote("capture")
        yield event.plain_result("执行完成:\n" + "\n".join(results) + "\n\n" + status.get("state_text", ""))

    @kards.command("screenshot")
    async def screenshot(self, event: AstrMessageEvent):
        result = await self._exec_remote("screenshot")
        if result.get("error"):
            yield event.plain_result(f"截图失败: {result['error']}")
            return
        img_b64 = result.get("image", "")
        if not img_b64:
            yield event.plain_result("无法获取截图")
            return
        try:
            img_bytes = base64.b64decode(img_b64)
            tmp = os.path.join(tempfile.gettempdir(), "kards_screenshot.png")
            with open(tmp, "wb") as f:
                f.write(img_bytes)
            try:
                from astrbot.api.message_components import Image
                yield event.chain_result([Image(file=tmp)])
            except Exception:
                yield event.plain_result(f"截图已保存: {tmp}")
        except Exception as exc:
            yield event.plain_result(f"截图处理失败: {exc}")
