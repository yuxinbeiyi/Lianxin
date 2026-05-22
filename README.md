# 莲心AI — Windows 桌面 AI 助手

基于 PyQt5 + DeepSeek API 的桌面个人 AI 助手，支持语音对话、视觉理解、QQ 桥接、硬件外设等功能。
![输入图片说明](assets/meme/%E5%8D%95%E6%89%8B%E5%8F%89%E8%85%B0.jpg)


## 功能概览

- **智能聊天**：DeepSeek 大模型驱动，支持文字/语音输入输出
- **语音交互**：faster-whisper（语音识别）+ Edge-TTS / 阿里云 NLS（语音合成）
- **视觉理解**：截图分析、摄像头抓拍、图片内容描述
- **QQ 桥接**：通过 NapCatQQ 实现 QQ 消息收发、语音/图片处理
- **本地模型**：支持 Ollama 一键切换，离线运行 1.5B 小模型
- **Galgame 模式**：Live2D 角色立绘，PixiJS 渲染，拖拽/缩放/对话框切换
- **智能观察系统**：ESP32 肩载摄像头自主扫描周围环境，AI 分析记录
- **技能系统**：插件式技能包，运行时按需激活/停用
- **记忆系统**：长期记忆存取、关键词搜索、自动日期标记
- **工具集成**：闹钟、待办、日记、番茄钟、音乐盒、快捷启动等

## 技术架构

```
┌─────────────────────────────────────────────────┐
│                    GUI (PyQt5)                    │
│   main_window / chat_widget / galgame / ...      │
├─────────────────────────────────────────────────┤
│              Decision Layer (decision.py)         │
│         规则路由：纯聊天 / 全 Agent（含工具）        │
├─────────────────────────────────────────────────┤
│               Agent Core (brain/agent.py)         │
│       Function Calling 对话循环 + 工具执行         │
├──────────────────┬──────────────────────────────┤
│   Tools (45+)     │   Skills System              │
│   brain/tools.py  │   brain/skill_manager.py     │
├──────────────────┴──────────────────────────────┤
│             Workers (后台线程)                     │
│   AgentWorker / VoiceWorker / SpeakerWorker      │
│   ProactiveWorker / QQBridgeWorker / ...         │
├─────────────────────────────────────────────────┤
│        External APIs                              │
│   DeepSeek / SiliconFlow / Ollama / 阿里云 NLS    │
└─────────────────────────────────────────────────┘
```

## 环境要求

- Windows 10+
- Python 3.12（推荐 conda 环境）
- NVIDIA 显卡（可选，用于本地模型加速）

## 安装

```bash
# 克隆仓库
git clone https://gitee.com/luke23334/lianxin-ai.git
cd lianxin-ai

# 创建虚拟环境
conda create -n lianxin python=3.12
conda activate lianxin

# 安装依赖
pip install -r requirements.txt
```

## 配置

首次运行后，在 `~/.lianxin/user_config.json` 中配置各 API 密钥，或通过界面 🔑 按钮配置：

- **DeepSeek API**：聊天模型（默认 deepseek-v4-flash）
- **SiliconFlow API**：视觉理解模型
- **阿里云 NLS**：语音识别（可选）
- **QQ 桥接**：NapCatQQ WebSocket 连接

### 本地模型（Ollama）

1. 安装 [Ollama](https://ollama.com)，拉取模型
2. 在 API 配置对话框中勾选"使用本地模型(Ollama)"
3. 配置 Ollama 地址（默认 `http://localhost:11434/v1`）和模型名
4. 保存后即时生效，无需重启

> 注意：本地模型不支持 Function Calling，切换后将自动使用纯聊天模式。

## 运行

```bash
python main.py
```

支持 `--autostart` 参数实现开机自启最小化启动。

## 项目结构

```
莲心AI/
├── main.py              # 入口
├── config.py            # 配置管理
├── brain/               # AI 核心
│   ├── agent.py         # AgentCore 对话循环
│   ├── decision.py      # 三层路由决策
│   ├── tools.py         # 工具定义与执行
│   ├── skill_manager.py # 技能系统
│   ├── memory_store.py  # 记忆存储
│   ├── observation_engine.py  # 智能观察引擎
│   ├── observation_store.py   # 观察记忆库
│   └── vision.py        # 视觉理解
├── gui/                 # PyQt5 界面
│   ├── main_window.py   # 主窗口
│   ├── chat_widget.py   # 聊天组件
│   ├── character_widget.py # 角色动画
│   └── galgame/         # Galgame Live2D 模式
├── workers/             # 后台工作线程
├── voice/               # 语音处理
├── vision/              # 视觉处理
├── utils/               # 工具函数
├── skills/              # 技能包目录
├── assets/              # 资源文件（GIF/音乐/图片）
└── memory/              # 运行时数据（SQLite/JSON）
```

## 外设项目

ESP32-CAM 肩载摄像头 + SG90 舵机云台项目：  
https://gitee.com/luke23334/lianxin-ai-esp32

## 开发记录

详见 `莲心AI开发档案记录.docx`
![输入图片说明](assets/meme/%E4%B8%BB%E7%95%8C%E9%9D%A2%E8%83%8C%E6%99%AF%E5%9B%BE.jpg)