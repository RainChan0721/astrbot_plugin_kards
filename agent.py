"""
Kards Bot Local Agent - 在本地电脑上运行，负责实际控制Kards游戏。
通过轮询远程astrbot服务器的API获取任务并执行。
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import signal
import time

import cv2
import httpx

from kards_bot import KardsBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("kards_agent")

POLL_INTERVAL = 2.0
POLL_PATH = "/astrbot_plugin_kards/agent/poll"
RESULT_PATH = "/astrbot_plugin_kards/agent/result"


class KardsAgent:
    def __init__(self, server_url: str, poll_interval: float = POLL_INTERVAL, access_token: str = ""):
        self.server_url = server_url.rstrip("/")
        self.poll_interval = poll_interval
        self.bot = KardsBot()
        headers = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self._http = httpx.Client(timeout=30.0, headers=headers)
        self._running = False

    def poll_task(self) -> dict | None:
        try:
            resp = self._http.post(f"{self.server_url}{POLL_PATH}")
            if resp.status_code == 401:
                logger.error("server rejected token, check access_token config")
                self._running = False
                return None
            resp.raise_for_status()
            data = resp.json()
            return data.get("task")
        except httpx.HTTPError as exc:
            logger.debug("poll failed: %s", exc)
            return None

    def submit_result(self, task_id: str, result: dict):
        try:
            resp = self._http.post(
                f"{self.server_url}{RESULT_PATH}",
                json={"task_id": task_id, "result": result},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("submit result failed: %s", exc)

    def execute_task(self, task: dict) -> dict:
        action = task.get("action", "")
        args = task.get("args", [])
        logger.info("executing task: %s %s", action, args)

        if action == "capture":
            return self._do_capture()
        elif action == "screenshot":
            return self._do_screenshot()
        elif action == "hand":
            return self._do_hand()
        elif action == "suggest":
            return self._do_suggest()
        elif action == "action":
            return self._do_action(args)
        else:
            return {"error": f"unknown action: {action}"}

    def _do_capture(self) -> dict:
        state = self.bot.capture_and_parse_sync()
        if state is None:
            return {"error": "无法捕获游戏画面"}
        return {"state_text": state.to_text()}

    def _do_screenshot(self) -> dict:
        state = self.bot.capture_and_parse_sync()
        if state is None or state.screenshot is None:
            return {"error": "无法截取游戏画面"}
        _, buf = cv2.imencode(".png", state.screenshot)
        b64 = base64.b64encode(buf.tobytes()).decode()
        return {"image": b64}

    def _do_hand(self) -> dict:
        state = self.bot.capture_and_parse_sync()
        if state is None:
            return {"error": "无法捕获游戏画面"}
        cards = []
        for i, card in enumerate(state.my_hand):
            cards.append({
                "index": i,
                "name": card.name or f"卡牌{i}",
                "cost": card.cost,
                "attack": card.attack,
                "defense": card.defense,
            })
        return {"cards": cards}

    def _do_suggest(self) -> dict:
        if self.bot.get_state() is None:
            self.bot.capture_and_parse_sync()
        actions = self.bot.suggest_actions_sync()
        return {"actions": actions}

    def _do_action(self, args: list[str]) -> dict:
        if not args:
            return {"error": "missing action"}
        if self.bot.get_state() is None:
            self.bot.capture_and_parse_sync()
        action_str = args[0] if args else ""
        result = self.bot.execute_action_sync(action_str)
        time.sleep(0.5)
        state = self.bot.capture_and_parse_sync()
        state_text = state.to_text() if state else ""
        return {"result": result, "state_text": state_text}

    def run(self):
        self._running = True
        try:
            resp = self._http.post(f"{self.server_url}{POLL_PATH}", json={}, timeout=10)
            logger.info("connected to server, poll response: %s %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("server health check failed: %s", exc)
        logger.info("Kards Agent started, polling %s every %.1fs", self.server_url + POLL_PATH, self.poll_interval)

        last_error_log = 0.0
        last_heartbeat = time.monotonic()
        heartbeat_interval = 30.0
        while self._running:
            try:
                task = self.poll_task()
                if task:
                    task_id = task.get("id", "")
                    logger.info("got task: %s %s", task_id, task.get("action"))
                    result = self.execute_task(task)
                    self.submit_result(task_id, result)
                    logger.info("task done: %s", task_id)
                else:
                    now = time.monotonic()
                    if now - last_heartbeat >= heartbeat_interval:
                        logger.info("heartbeat: polling... (no tasks)")
                        last_heartbeat = now
                    if self._running:
                        time.sleep(self.poll_interval)
            except Exception as exc:
                now = time.time()
                if now - last_error_log > 30:
                    logger.error("agent error: %s", exc)
                    last_error_log = now
                if self._running:
                    time.sleep(self.poll_interval)

        logger.info("Kards Agent stopped")

    def stop(self):
        self._running = False


def main():
    parser = argparse.ArgumentParser(description="Kards Bot Local Agent")
    parser.add_argument("--server", "-s", default=os.environ.get("KARDS_SERVER_URL", "http://localhost:6188"),
                        help="远程astrbot服务器地址")
    parser.add_argument("--interval", "-i", type=float, default=POLL_INTERVAL,
                        help="轮询间隔秒数")
    parser.add_argument("--token", "-t", default=os.environ.get("KARDS_ACCESS_TOKEN", ""),
                        help="访问令牌（与astrbot插件配置的access_token一致）")
    args = parser.parse_args()

    agent = KardsAgent(server_url=args.server, poll_interval=args.interval, access_token=args.token)

    def _signal_handler(signum, frame):
        logger.info("received signal %s, stopping...", signum)
        agent.stop()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    agent.run()


if __name__ == "__main__":
    main()
