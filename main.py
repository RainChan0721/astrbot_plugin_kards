from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import uuid

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

COMMAND_PREFIX = "/kards"
COMMANDS = {
    "start": "启动Kards Bot并分析当前局面",
    "status": "查看当前游戏状态",
    "screenshot": "截取当前游戏画面",
    "hand": "查看手牌详情",
    "play": "出牌: /kards play <编号>",
    "attack": "攻击: /kards attack <单位编号> [目标编号]",
    "endturn": "结束回合",
    "suggest": "让AI分析局面并给出建议",
    "apply": "执行AI建议的所有操作",
    "help": "显示帮助信息",
}

TASK_TIMEOUT = 60


@register("astrbot_plugin_kards", "雪乃", "让AstrBot能玩Kards卡牌游戏（远程Agent模式）", "0.1.0")
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

    async def _reply(self, event: AstrMessageEvent, message: str):
        try:
            await event.send(message)
        except Exception:
            try:
                await self.context.send_message(event, message)
            except Exception as exc:
                logger.error("[Kards] failed to reply: %s", exc)

    def _enqueue_task(self, action: str, args: list[str] = None) -> asyncio.Future:
        task_id = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._task_queue.append({
            "id": task_id,
            "action": action,
            "args": args or [],
        })
        self._task_futures[task_id] = fut
        logger.info("[Kards] task enqueued: %s %s %s", task_id, action, args)
        return fut

    def _complete_task(self, task_id: str, result: dict):
        fut = self._task_futures.pop(task_id, None)
        if fut and not fut.done():
            fut.set_result(result)
            logger.info("[Kards] task completed: %s", task_id)

    async def _wait_task(self, fut: asyncio.Future, timeout: int = TASK_TIMEOUT) -> dict:
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return {"error": "任务超时，确认本地Agent是否在运行喵"}
        except Exception as exc:
            return {"error": str(exc)}

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

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = str(getattr(event, "message_str", "") or "").strip()
        if not text.startswith(COMMAND_PREFIX):
            return

        parts = text[len(COMMAND_PREFIX):].strip().split()
        if not parts:
            await self._show_help(event)
            return

        cmd = parts[0].lower()
        args = parts[1:]

        handler = {
            "start": self._cmd_start,
            "status": self._cmd_status,
            "screenshot": self._cmd_screenshot,
            "hand": self._cmd_hand,
            "play": self._cmd_play,
            "attack": self._cmd_attack,
            "endturn": self._cmd_endturn,
            "suggest": self._cmd_suggest,
            "apply": self._cmd_apply,
            "help": self._show_help,
        }.get(cmd)

        if handler is None:
            await self._reply(event, f"未知指令: {cmd}\n发送 /kards help 查看帮助")
            return

        try:
            await handler(event, args)
        except Exception as exc:
            logger.exception("[Kards] command error: %s", exc)
            await self._reply(event, f"指令执行出错: {exc}")

    async def _show_help(self, event: AstrMessageEvent, _args=None):
        lines = ["Kards Bot 指令列表:"]
        for cmd, desc in COMMANDS.items():
            lines.append(f"  /kards {cmd} - {desc}")
        await self._reply(event, "\n".join(lines))

    async def _exec_remote(self, action: str, args: list[str] = None) -> dict:
        fut = self._enqueue_task(action, args)
        return await self._wait_task(fut)

    async def _cmd_start(self, event: AstrMessageEvent, _args: list[str]):
        result = await self._exec_remote("capture")
        if result.get("error"):
            await self._reply(event, f"启动失败: {result['error']}")
            return
        state_text = result.get("state_text", "未知")
        await self._reply(event, f"Kards Bot 已启动!\n\n{state_text}")

    async def _cmd_status(self, event: AstrMessageEvent, _args: list[str]):
        result = await self._exec_remote("capture")
        if result.get("error"):
            await self._reply(event, f"获取状态失败: {result['error']}")
            return
        await self._reply(event, result.get("state_text", "未知"))

    async def _cmd_screenshot(self, event: AstrMessageEvent, _args: list[str]):
        result = await self._exec_remote("screenshot")
        if result.get("error"):
            await self._reply(event, f"截图失败: {result['error']}")
            return
        img_b64 = result.get("image", "")
        if not img_b64:
            await self._reply(event, "无法获取截图")
            return
        try:
            img_bytes = base64.b64decode(img_b64)
            tmp = os.path.join(tempfile.gettempdir(), "kards_screenshot.png")
            with open(tmp, "wb") as f:
                f.write(img_bytes)
            try:
                from astrbot.api.message_components import Image
                await event.send(Image(file=tmp))
            except Exception:
                await self._reply(event, f"截图已保存: {tmp}")
        except Exception as exc:
            await self._reply(event, f"截图处理失败: {exc}")

    async def _cmd_hand(self, event: AstrMessageEvent, _args: list[str]):
        result = await self._exec_remote("hand")
        if result.get("error"):
            await self._reply(event, f"获取手牌失败: {result['error']}")
            return
        cards = result.get("cards", [])
        if not cards:
            await self._reply(event, "手牌为空或无法识别")
            return
        lines = ["手牌:"]
        for c in cards:
            lines.append(f"  [{c['index']}] {c['name']} (费用:{c['cost']}) {c['attack']}/{c['defense']}")
        await self._reply(event, "\n".join(lines))

    async def _cmd_play(self, event: AstrMessageEvent, args: list[str]):
        if not args or not args[0].isdigit():
            await self._reply(event, "用法: /kards play <手牌编号>")
            return
        result = await self._exec_remote("action", [f"play {args[0]}"])
        if result.get("error"):
            await self._reply(event, f"出牌失败: {result['error']}")
            return
        await self._reply(event, f"{result.get('result', '')}\n\n{result.get('state_text', '')}")

    async def _cmd_attack(self, event: AstrMessageEvent, args: list[str]):
        if not args or not args[0].isdigit():
            await self._reply(event, "用法: /kards attack <单位编号> [目标编号]")
            return
        action = "attack " + " ".join(args)
        result = await self._exec_remote("action", [action])
        if result.get("error"):
            await self._reply(event, f"攻击失败: {result['error']}")
            return
        await self._reply(event, f"{result.get('result', '')}\n\n{result.get('state_text', '')}")

    async def _cmd_endturn(self, event: AstrMessageEvent, _args: list[str]):
        result = await self._exec_remote("action", ["end_turn"])
        if result.get("error"):
            await self._reply(event, f"结束回合失败: {result['error']}")
            return
        await self._reply(event, result.get("result", "回合已结束"))

    async def _cmd_suggest(self, event: AstrMessageEvent, _args: list[str]):
        result = await self._exec_remote("suggest")
        if result.get("error"):
            await self._reply(event, f"AI建议失败: {result['error']}")
            return
        actions = result.get("actions", [])
        self._pending_actions = list(actions)
        lines = ["AI 建议的操作:"]
        for i, action in enumerate(actions):
            lines.append(f"  [{i}] {action}")
        lines.append("")
        lines.append("使用 /kards apply 执行所有建议，或 /kards play/attack 手动操作")
        await self._reply(event, "\n".join(lines))

    async def _cmd_apply(self, event: AstrMessageEvent, _args: list[str]):
        if not self._pending_actions:
            await self._reply(event, "没有待执行的操作，先用 /kards suggest 生成建议")
            return
        results = []
        for action in self._pending_actions:
            result = await self._exec_remote("action", [action])
            results.append(f"> {action}\n  {result.get('result', '?')}")
            await asyncio.sleep(0.5)
        self._pending_actions.clear()
        status = await self._exec_remote("capture")
        state_text = status.get("state_text", "")
        await self._reply(event, "执行完成:\n" + "\n".join(results) + "\n\n" + state_text)
