"""
Kards Bot 诊断测试脚本
在本地跑这个脚本，可以测试各个模块是否正常工作。
不需要Kards游戏运行，但需要安装好依赖。
"""

from __future__ import annotations

import importlib
import os
import sys
import subprocess
import traceback

PASS = 0
FAIL = 0
SKIP = 0


def test(name: str):
    def decorator(fn):
        def wrapper(*a, **kw):
            global PASS, FAIL, SKIP
            try:
                fn(*a, **kw)
                PASS += 1
                print(f"  [OK] {name}")
            except ImportError as e:
                SKIP += 1
                print(f"  [SKIP] {name}: 缺少依赖 ({e.name})")
            except ModuleNotFoundError as e:
                SKIP += 1
                print(f"  [SKIP] {name}: 缺少模块 ({e.name})")
            except Exception as e:
                FAIL += 1
                print(f"  [FAIL] {name}: {e}")
                traceback.print_exc()
        return wrapper
    return decorator


def need(*modules):
    for m in modules:
        importlib.import_module(m)


@test("系统工具检查")
def t_system_tools():
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    print(f"  桌面环境: {session}")
    tools = ["grim", "hyprctl", "tesseract"]
    for tool in tools:
        r = subprocess.run(["which", tool], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"    {tool}: OK")
        else:
            print(f"    {tool}: 未安装 (可选)")


@test("CardInfo 数据类")
def t_card_info():
    sys.path.insert(0, os.path.dirname(__file__))
    from kards_bot.game_state import CardInfo
    c = CardInfo(index=1, name="测试卡", cost=4, attack=3, defense=2, x=100, y=200, width=80, height=120)
    assert c.name == "测试卡"
    assert c.cost == 4
    print(f"  [{c.index}] {c.name} ({c.cost}K) {c.attack}/{c.defense}")


@test("GameState 数据类")
def t_game_state():
    from kards_bot.game_state import GameState, CardInfo
    state = GameState(
        my_health=20, my_kredits=6,
        my_hand=[CardInfo(index=0, name="步兵", cost=3, attack=2, defense=3)],
        my_units=[CardInfo(index=0, name="前线步兵", cost=2, attack=3, defense=2)],
        opp_health=18, opp_hand_count=4,
        opp_units=[CardInfo(index=0, name="敌方步兵", cost=3, attack=2, defense=3)],
    )
    text = state.to_text()
    assert "步兵" in text
    assert "前线步兵" in text
    assert "敌方步兵" in text
    print(f"  to_text() 输出:\n{text}")


@test("DecisionEngine 规则决策")
def t_decision():
    import asyncio
    from kards_bot.game_state import GameState, CardInfo
    from kards_bot.ai import DecisionEngine
    state = GameState(
        my_health=20, my_kredits=6,
        my_hand=[
            CardInfo(index=0, name="步兵", cost=3, attack=2, defense=3),
            CardInfo(index=1, name="重坦", cost=6, attack=5, defense=5),
            CardInfo(index=2, name="轻坦", cost=4, attack=3, defense=3),
        ],
        my_units=[CardInfo(index=0, name="前线步兵", cost=2, attack=3, defense=2)],
        opp_health=18, opp_hand_count=4,
        opp_units=[CardInfo(index=0, name="敌方步兵", cost=3, attack=2, defense=3)],
    )
    engine = DecisionEngine()
    actions = asyncio.run(engine.decide(state))
    print(f"  建议操作: {actions}")
    assert len(actions) > 0
    assert actions[-1] == "end_turn"


@test("KardsBot 初始化")
def t_bot_init():
    need("numpy", "cv2")
    from kards_bot.bot import KardsBot
    bot = KardsBot()
    assert bot.get_state() is None
    print("  KardsBot 创建成功")


@test("ScreenCapturer 截图后端检测")
def t_screen_backend():
    need("numpy", "cv2")
    from kards_bot.screen import ScreenCapturer
    cap = ScreenCapturer()
    print(f"  后端: {cap._backend}, 桌面: {os.environ.get('XDG_SESSION_TYPE', 'unknown')}")


@test("ScreenCapturer 窗口查找")
def t_screen_window():
    need("numpy", "cv2")
    from kards_bot.screen import ScreenCapturer
    cap = ScreenCapturer()
    window = cap.find_window()
    if window:
        print(f"  找到窗口: x={window.get('x')} y={window.get('y')} w={window.get('width')} h={window.get('height')}")
    else:
        print("  未找到Kards窗口 (正常, 如果没开游戏)")


@test("InputSimulator 后端检测")
def t_input_backend():
    from kards_bot.input import InputSimulator
    sim = InputSimulator()
    print(f"  后端: {sim._backend}")
    assert sim._backend in ("ydotool", "pyautogui", "wayland", "unknown")


@test("GameStateParser 图像分析 (需截图)")
def t_parser():
    need("numpy", "cv2")
    from kards_bot.screen import ScreenCapturer
    from kards_bot.game_state import GameStateParser
    cap = ScreenCapturer()
    img = cap.capture()
    if img is None:
        raise AssertionError("无法截图")
    parser = GameStateParser()
    state = parser.parse(img, ocr=None)
    print(f"  手牌检测: {len(state.my_hand)} 张, 费用区域: {state.my_kredits}")
    print(f"  手牌位置: {[(c.x, c.y, c.width, c.height) for c in state.my_hand]}")


def run_all():
    global PASS, FAIL, SKIP
    print("=" * 54)
    print("  Kards Bot 诊断测试")
    print("=" * 54)

    tests = [
        t_system_tools,
        t_card_info,
        t_game_state,
        t_decision,
        t_bot_init,
        t_screen_backend,
        t_screen_window,
        t_input_backend,
        t_parser,
    ]

    for t in tests:
        t()

    print("\n" + "-" * 54)
    print(f"  结果: {PASS} 通过, {FAIL} 失败, {SKIP} 跳过")
    print("-" * 54)

    return FAIL == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
