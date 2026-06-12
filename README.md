# 莲心AI — Windows 桌面 AI 助手

基于 PyQt5 + DeepSeek API 的桌面个人 AI 助手，支持语音对话、视觉理解、QQ 桥接、硬件外设等功能。
<img src="assets/meme/单手叉腰.jpg" alt="莲心形象照" width="250" />


## 功能概览

| 模块 | 功能 |
|------|------|
| 💬 **智能聊天** | DeepSeek V4 大模型驱动，Function Calling 工具调用，支持文字/语音输入输出 |
| 🎙️ **语音交互** | faster-whisper 语音识别 + GPT-SoVITS 声音克隆 + Edge-TTS 自动回退，5 种情绪音色 |
| 👁️ **视觉理解** | 截图分析、摄像头抓拍、图片内容描述，支持 OCR 文字识别 |
| 🐧 **QQ 桥接** | 通过 NapCatQQ 实现 QQ 消息收发、语音/图片/文件处理，多用户独立会话 |
| 🖥️ **本地模型** | 支持 Ollama 一键切换，离线运行本地小模型 |
| 🎮 **Galgame 模式** | 透明角色立绘窗口 + 可拖拽拉伸对话框，全边缘自由缩放，字体/加粗设置，静音同步 |
| 📷 **智能观察系统** | ESP32-CAM 肩载摄像头 + SG90 舵机云台，AI 自主扫描周围环境并记录 |
| 🧍 **人体跟踪** | ESP32 实时推流 + MediaPipe Pose 推理 + 舵机自动跟随人物 |
| 🧠 **记忆系统** | 五元组图记忆 + 分类事实记忆，自动提取，关键词搜索，跨会话持久化 |
| 🔌 **技能系统** | 插件式技能包，运行时按需激活/停用，含 7 个内置技能 |
| ⏰ **工具集成** | 闹钟、倒计时、待办清单、提醒、日记、备忘本、番茄钟、音乐盒、快捷启动 |
| 🌙 **待机模式** | 阿里云 NLS 语音唤醒 + 小纸条文件交互，无需鼠标键盘 |
| 🎭 **情感系统** | 自动情绪检测 + 表情包随机发送 + 角色动画切换 |
| 🌐 **联网搜索** | 网页搜索、内容抓取（HTTP/API/浏览器三种模式）、Playwright 浏览器自动化 |
| 🔗 **MCP 支持** | 兼容 MCP 协议，支持本地/外部 MCP 服务接入 |


## 技术架构

```
┌──────────────────────────────────────────────────────────┐
│                     GUI (PyQt5)                           │
│  main_window / chat_widget / character_widget            │
│  input_panel / galgame (立绘+对话框) / 各种弹窗           │
├──────────────────────────────────────────────────────────┤
│              意图路由层 (intent_router.py)                 │
│     LLM 路由：纯聊天 / 全 Agent（含工具）+ 工具预选         │
│     + 规则路由 (decision.py) 兜底                          │
├──────────────────────────────────────────────────────────┤
│                Agent Core (brain/agent.py)                │
│     Function Calling 对话循环 + 工具并行执行 + 资源锁       │
├────────────────────┬─────────────────────────────────────┤
│  Tools (50+)        │  Skills System                     │
│  brain/tools.py     │  brain/skill_manager.py            │
│  + 7 技能包工具      │  自动发现/激活/停用/工具注入          │
├────────────────────┴─────────────────────────────────────┤
│              Workers (后台线程)                            │
│  AgentWorker / VoiceWorker / SpeakerWorker               │
│  QQBridgeWorker / ProactiveWorker / StandbyWorker        │
│  ObservationModeWorker / TrackWorker / SmartReminder...  │
├──────────────────────────────────────────────────────────┤
│          External APIs & Hardware                         │
│  DeepSeek / SiliconFlow / Ollama / 阿里云 NLS             │
│  ESP32-CAM / SG90 舵机 / NapCatQQ / Playwright           │
└──────────────────────────────────────────────────────────┘
```

## 环境要求

- **操作系统**：Windows 10+
- **Python**：3.12（推荐 conda 环境）
- **GPU**：NVIDIA 显卡（可选，用于 GPT-SoVITS 声音克隆和本地模型加速）


## 快速开始

# 克隆仓库
git clone https://gitee.com/luke23334/lianxin-ai.git
cd lianxin-ai

# 创建虚拟环境
conda create -n lianxin python=3.12
conda activate lianxin

# 安装依赖
pip install -r requirements.txt


## 配置

首次运行后，配置文件自动生成在 `~/.lianxin/user_config.json`，也可通过界面 🔑 按钮配置：

| 配置项 | 说明 |
|--------|------|
| **DeepSeek API** | 聊天模型（默认 `deepseek-v4-flash`），支持 Anthropic 格式 |
| **SiliconFlow API** | 视觉理解模型（`Qwen/Qwen3-VL-30B-A3B-Instruct`） |
| **阿里云 NLS** | 语音识别（待机模式唤醒词检测） |
| **本地模型 (Ollama)** | 一键切换，配置地址和模型名即可 |
| **TTS 语音合成** | GPT-SoVITS 路径、情绪风格、语速、Edge-TTS 回退音色 |
| **QQ 桥接** | NapCatQQ WebSocket 地址、QQ 号、主人信息、语音回复开关 |
| **网络代理** | HTTP/HTTPS 代理配置 |

### 本地模型（Ollama）

1. 安装 [Ollama](https://ollama.com)，拉取模型
2. 在 API 配置对话框中勾选"使用本地模型(Ollama)"
3. 配置 Ollama 地址（默认 `http://localhost:11434/v1`）和模型名
4. 保存后即时生效，无需重启

> 注意：本地模型不支持 Function Calling，切换后将自动使用纯聊天模式。

## 可选外部依赖

| 组件 | 用途 | 需要单独安装 |
|------|------|-------------|
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ) | QQ 聊天功能（WebSocket 连接） | 是 |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | 图片文字识别 | 是 |
| [Ollama](https://ollama.com) | 本地模型运行 | 否（可选） |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 声音克隆（高质量语音合成） | 否（可选） |

> NapCatQQ 和 Tesseract 需要用户自行部署，莲心不内置这两者。

---

## 核心功能详解

### 🎮 Galgame 模式

点击主界面顶部 🎮 Galgame 按钮开启，也可通过 `Ctrl+Alt+X` 全局热键切换。

- **透明立绘**：可拖拽定位，右键隐藏/显示对话框，支持 GIF 动画
- **对话窗口**：全边缘（上下左右+四角）自由拉伸，半透明磨砂玻璃风格
- **字体设置**：⚙ 按钮调节字体大小（8-24pt）和加粗
- **静音同步**：🔇 按钮与主界面共享静音状态，停止语音播放
- **输入框自适应**：1 行默认，内容超出自动扩展至 2→3 行
- **表情联动**：AI 回复内容自动匹配对应情绪立绘

### 🐧 QQ 桥接

通过 NapCatQQ 实现 QQ 机器人功能：

- **多用户独立会话**：每个 QQ 用户/群聊拥有独立对话上下文
- **消息类型**：文字、图片（AI 视觉分析）、语音（SILK 转录）、文件（内容提取）
- **语音回复**：莲心说话 → TTS 合成 → SILK 编码 → QQ 语音消息
- **长文本分段**：超长回复自动分段发送，用 "。。" 结尾触发多段接收
- **群聊 @ 旁听**：缓存群聊上下文，@ 莲心时感知对话背景
- **观察/跟踪模式**：远程启动肩载摄像头观察或人体跟踪
- **限速保护**：全局限速 + 每用户日限额 + 深夜静默

### 📷 智能观察系统

ESP32-CAM 肩载摄像头 + SG90 舵机云台，通过 WebSocket 与莲心通信：

- **观察模式**：莲心自动转动云台拍照，分析画面内容，记录发现
- **人体跟踪**：ESP32 实时推流 → MediaPipe Pose 推理 → 舵机自动跟随人物
- **手动控制**：拍照、水平/垂直旋转、复位、温度/湿度查询
- **观察记忆**：所有观察记录持久化，支持关键词搜索和回溯

> 硬件项目地址：https://gitee.com/luke23334/lianxin-ai-esp32

### 🧠 记忆系统

- **五元组图记忆**：以 `(主语, 谓语, 宾语, 时间, 来源)` 形式存储实体关系
- **分类事实记忆**：6 大分类（档案/偏好/事件/知识/行为/技能）
- **自动提取**：每 N 轮对话自动提取新记忆，无需手动操作
- **智能搜索**：`search_graph_memory` 统一搜索，支持多跳关系查询

### 🎙️ 语音合成

- **GPT-SoVITS**：声音克隆，通过参考音频定义莲心专属声线
- **5 种情绪**：casual（日常温柔）、tsundere（傲娇）、romantic（深情）、long（长句稳定）、angry（生气）
- **自动情绪匹配**：不指定情绪时根据文本内容自动匹配
- **Edge-TTS 回退**：GPT-SoVITS 不可用时无缝切换云端 TTS
- **持久 worker**：模型只加载一次，后续合成秒级响应

### 🌙 待机模式

不用鼠标键盘，通过语音与莲心交互：

- 阿里云 NLS 实时语音识别子进程
- 说"完毕"触发 AI 回复，30 秒超时自动清空
- 回复自动朗读，朗读完毕自动继续监听
- 适合做家务、休息等手离开键盘的场景

### 🔌 技能系统

插件式技能包，每个技能包含 `SKILL.md`（知识注入）和 `tools.py`（工具定义）：

| 技能 | 说明 | 自动激活 |
|------|------|----------|
| 语音合成 | GPT-SoVITS 声音克隆 + 情绪表达 | ✅ |
| 浏览器自动化 | Playwright 网页控制（导航/点击/填表/截图） | ✅ |
| 肩部外设控制 | ESP32-CAM 云台 + 观察 + 人体跟踪 | ✅ |
| 日记与备忘 | 日记读写 + 备忘本整理 | ✅ |
| 音乐播放控制 | 音乐盒播放/暂停/切歌/音量 | ✅ |
| 系统信息工具 | CPU/内存/磁盘/网络状态查询 | ❌ |
| 学习助手 | 学习方法与记忆力建议 | ❌ |

---

## 工具列表

莲心内置 50+ 个 Function Calling 工具，分为以下类别：

| 类别 | 工具 | 说明 |
|------|------|------|
| 📁 文件操作 | read_file, write_file, list_directory, search_files, read_excel, write_excel, write_docx, format_document 等 | 文件读写、搜索、Excel/Word 处理 |
| 💻 系统命令 | open_app, run_command, get_clipboard, run_python_code | 打开应用、执行命令、剪贴板 |
| 🌐 联网搜索 | web_search, fetch_webpage, fetch_webpage_via_api, fetch_webpage_browser | 搜索和网页内容抓取 |
| 🔍 视觉理解 | describe_image, ocr_image, camera_capture, screenshot | 图片分析、OCR、拍照、截图 |
| 🧠 记忆与任务 | save_memory, update_memory, delete_memory, search_graph_memory, add_todo, list_todos, complete_todo | 记忆存取、待办管理 |
| 📅 信息查询 | get_current_time, get_balance, get_system_info | 时间日期、余额、系统状态 |
| 🎵 音乐 | control_music, get_music_playlist, get_music_status | 音乐盒控制 |
| 📖 日记 | read_diary, write_diary, read_note, organize_note | 日记读写、备忘本 |
| 📷 肩部外设 | shoulder_photo, shoulder_pan, shoulder_tilt, shoulder_center, start_observation_mode, shoulder_human_track 等 | 云台控制、观察、跟踪 |
| 🎙️ 语音 | speak_voice, set_voice_mood, list_voice_styles | 语音合成、情绪设置 |
| 🌐 浏览器 | browser_navigate, browser_snapshot, browser_click, browser_fill, browser_screenshot | Playwright 浏览器控制 |
| ⏰ 闹钟 | add_alarm, list_alarms, delete_alarm | 闹钟管理 |
| 🔗 跨端 | search_cross_session, send_to_phone | 跨设备搜索和发送 |

---

## 外设项目

ESP32-CAM 肩载摄像头 + SG90 舵机云台项目：  
https://gitee.com/luke23334/lianxin-ai-esp32

---

## 开发记录

详见 `莲心AI开发档案记录.docx`

<img src="assets/meme/主界面背景图.jpg" alt="主界面截图" width="100%" />
