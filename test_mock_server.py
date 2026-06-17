"""
Kards Agent 本地模拟测试
模拟远程astrbot服务器的API，让你可以在不开astrbot的情况下测试agent的完整工作流。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mock_server")

POLL_PATH = "/astrbot_plugin_kards/agent/poll"
RESULT_PATH = "/astrbot_plugin_kards/agent/result"
TOKEN = "test123"


class MockTask:
    def __init__(self, action: str, args: list[str] = None):
        self.id = uuid.uuid4().hex[:12]
        self.action = action
        self.args = args or []
        self.done = threading.Event()
        self.result = None


class MockHandler(BaseHTTPRequestHandler):
    tasks: list[MockTask] = []
    results: list[dict] = []

    def _check_token(self) -> bool:
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        if auth != expected:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "unauthorized"}).encode())
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "mock server ok"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode()) if length else {}

        if self.path == POLL_PATH:
            if not self._check_token():
                return
            if MockHandler.tasks:
                task = MockHandler.tasks.pop(0)
                self._json({"task": {"id": task.id, "action": task.action, "args": task.args}})
            else:
                self._json({"task": None})

        elif self.path == RESULT_PATH:
            if not self._check_token():
                return
            task_id = body.get("task_id", "")
            result = body.get("result", {})
            MockHandler.results.append({"task_id": task_id, "result": result})
            logger.info("got result for task %s: %s", task_id, json.dumps(result, ensure_ascii=False))
            self._json({"status": "ok"})

        else:
            self._json({"error": "not found"}, 404)

    def _json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        logger.debug("HTTP %s", fmt % args)


def run_mock_server(host: str = "127.0.0.1", port: int = 6188):
    server = HTTPServer((host, port), MockHandler)
    logger.info("mock server running at http://%s:%s", host, port)
    logger.info("poll: POST http://%s:%s%s", host, port, POLL_PATH)
    logger.info("result: POST http://%s:%s%s", host, port, RESULT_PATH)
    logger.info("token: %s", TOKEN)
    logger.info("")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def interactive_test(server_url: str = "http://127.0.0.1:6188", token: str = TOKEN):
    print()
    print("=" * 54)
    print("  Kards Agent 交互测试")
    print("=" * 54)
    print()
    print("可用的测试指令:")
    print("  1 - 添加 capture 任务 (截图识别)")
    print("  2 - 添加 screenshot 任务 (截屏)")
    print("  3 - 添加 hand 任务 (手牌)")
    print("  4 - 添加 suggest 任务 (AI建议)")
    print("  5 - 添加 action/play 任务 (出牌)")
    print("  6 - 添加 action/end_turn 任务 (结束回合)")
    print("  a - 启动Agent (自动轮询任务)")
    print("  q - 退出")
    print()

    import subprocess
    agent_proc = None

    while True:
        cmd = input("> ").strip().lower()

        if cmd == "q":
            if agent_proc:
                agent_proc.terminate()
            break

        elif cmd == "a":
            if agent_proc and agent_proc.poll() is None:
                print("Agent 已在运行")
                continue
            env = {
                **dict(os.environ),
                "KARDS_SERVER_URL": server_url,
                "KARDS_ACCESS_TOKEN": token,
            }
            agent_proc = subprocess.Popen(
                ["python", "agent.py"],
                env=env,
            )
            print("Agent 已启动 (PID %d)" % agent_proc.pid)

        elif cmd in ("1", "2", "3", "4", "5", "6"):
            task_map = {
                "1": ("capture", []),
                "2": ("screenshot", []),
                "3": ("hand", []),
                "4": ("suggest", []),
                "5": ("action", ["play 0"]),
                "6": ("action", ["end_turn"]),
            }
            action, args = task_map[cmd]
            task = MockTask(action, args)
            MockHandler.tasks.append(task)
            print("添加任务: %s %s (id=%s)" % (action, args, task.id))

        else:
            print("未知指令, 输入 1-6 或 a/q")


if __name__ == "__main__":
    import os

    server = run_mock_server()
    try:
        interactive_test()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        logger.info("mock server stopped")
