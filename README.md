# astrbot_plugin_kards

让 AstrBot 能玩 Kards 卡牌游戏的插件喵~

## 架构

```
远程服务器 (运行 AstrBot)
  └── astrbot_plugin_kards/main.py
       ├── 注册 Web API (/astrbot_plugin_kards/agent/*)
       └── 处理群内 /kards 指令
              ↕ HTTP (轮询)
本地电脑 (运行 Kards 游戏)
  └── agent.py + kards_bot/
       ├── ScreenCapturer  截图 (跨平台)
       ├── OcrReader       OCR 识别
       ├── GameStateParser 分析战局
       ├── DecisionEngine  AI决策 (规则/LLM)
       └── InputSimulator  模拟操作 (跨平台)
```

## 部署

### 远程服务器 (AstrBot)

1. 把整个 `astrbot_plugin_kards/` 丢到 AstrBot 的插件目录
2. 重启 AstrBot
3. 可选: 在插件配置里设置 `access_token` 防止 API 被乱调用

### 本地电脑 (玩游戏)

#### 安装 Python 依赖 (通用)

```bash
cd astrbot_plugin_kards
uv venv
uv pip install numpy opencv-python Pillow pytesseract mss pyautogui httpx
```

#### 按平台安装系统工具

**Arch Linux (Wayland)**:
```bash
sudo pacman -S grim ydotool tesseract
ydotoold &
```

**Ubuntu/Debian (X11)**:
```bash
sudo apt install tesseract-ocr xdotool
```

**Windows**: 安装 [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) 并加入 PATH

**macOS**:
```bash
brew install tesseract
```

#### 运行 Agent

```bash
source .venv/bin/activate
python agent.py --server http://远程服务器IP:6188
```

如果设置了 access_token:
```bash
python agent.py --server http://远程服务器IP:6188 --token 你的token
```

也可以用环境变量:
```bash
export KARDS_SERVER_URL=http://远程服务器IP:6188
export KARDS_ACCESS_TOKEN=你的token
python agent.py
```

## 群内指令

| 指令 | 说明 |
|------|------|
| `/kards help` | 显示帮助 |
| `/kards start` | 连接 Agent 并查看局面 |
| `/kards status` | 查看当前战况 |
| `/kards hand` | 查看手牌 |
| `/kards play <编号>` | 出牌 |
| `/kards attack <编号> [目标]` | 攻击 |
| `/kards endturn` | 结束回合 |
| `/kards suggest` | AI 给建议 |
| `/kards apply` | 执行 AI 建议 |
| `/kards screenshot` | 截图 |

## 诊断测试

在本地跑一下确认环境没问题:
```bash
source .venv/bin/activate
python test_diagnose.py
```

## 跨平台说明

| 平台 | 截图 | 模拟输入 | 窗口查找 |
|------|------|----------|----------|
| Linux (Wayland) | grim | ydotool | hyprctl |
| Linux (X11) | mss | pyautogui | xdotool |
| Windows | mss | pyautogui | pygetwindow |
| macOS | mss | pyautogui | pygetwindow |

## 注意事项

- Kards 需要在 Proton (Linux) 或原生 (Windows/macOS) 下运行, 确保游戏窗口可见
- Windows/macOS 需要允许终端模拟输入（辅助功能权限）
- 第一次使用可能需要调整 `game_state.py` 中的手牌检测阈值
- 结束回合按钮默认在右下角, 全屏 1920x1080 下可用
- ydotoold (Linux Wayland) 需要一直后台运行才能模拟点击
