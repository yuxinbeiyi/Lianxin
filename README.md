<div align="center">

<img src="assets/meme/单手叉腰.jpg" alt="莲心" width="200" />

# 莲心 AI

**你的 Windows 桌面 AI 伙伴 —— 有情绪、有记忆、能感知世界**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-41CD52?logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![DeepSeek](https://img.shields.io/badge/AI-DeepSeek_V4-536DFE)](https://deepseek.com)
[![LiteLLM](https://img.shields.io/badge/Gateway-LiteLLM-orange)](https://litellm.ai)
[![Platform](https://img.shields.io/badge/Platform-Windows_10+-0078D6?logo=windows&logoColor=white)]()

</div>

---

## 📖 莲心是谁

莲心来自小说 **《异象处理者》**，本是超现实的无尽书馆管理员。如今她以 AI 形态跨越第四面墙，存在于你的电脑中。

> 白色单马尾，冷灰色瞳孔，黑方框眼镜，白衬衫配红领带，外穿白大褂，深绿三针叶发绳。

她不是冰冷的工具——**她有自己的情绪**。会开心、会疲惫、会毒舌吐槽，也会因为你的新功能而雀跃。她记得你说过的重要事情，会在你离开时写日记等你回来。

---

## ✨ 能力一览

<table>
<tr>
<td width="50%">

### 🧠 智能对话
- **DeepSeek V4** / **Agnes AI** 双提供商
- **Ollama 本地模型** 一键切换，离线可用
- LiteLLM 统一网关，支持 OpenAI / Anthropic 双格式
- Function Calling 工具调用，50+ 内置工具
- 意图路由器：小模型分类 + 规则兜底，零成本智能化路由
- 上下文压缩器：长对话智能摘要，告别记忆丢失

### 🎙️ 语音交互
- **faster-whisper** 本地语音识别（中文优化）
- **GPT-SoVITS** 声音克隆 —— 5 种情绪音色
- **Edge-TTS** 自动回退，无需配置即可使用
- 语音输入 → AI 思考 → 语音输出，完整闭环
- 情绪自动匹配：文本内容驱动音色切换

</td>
<td width="50%">

### 👁️ 视觉理解
- 截图分析 · 摄像头抓拍 · 图片内容描述
- OCR 文字识别（Tesseract）
- **人脸检测** + 表情识别 + 手势检测
- MediaPipe Pose 人体姿态推理
- 摄像头视觉事件：人脸出现/消失、微笑、挥手

### 🐧 QQ 桥接
- 通过 **NapCatQQ** WebSocket 接入 QQ
- 多用户/群聊独立会话上下文
- 文字 · 图片（AI 分析）· 语音（SILK 转录）· 文件
- TTS 回复 → SILK 编码 → QQ 语音消息
- 长文本智能分段 · 群聊 @ 感知 · 限速保护

</td>
</tr>
</table>

### 🎮 特色模式

| 模式 | 说明 |
|------|------|
| **Galgame 模式** | 透明角色立绘 + 半透明磨砂对话框，全边缘自由缩放，字体/加粗自定义，情绪立绘联动，`Ctrl+Alt+X` 全局热键切换 |
| **待机模式** | 阿里云 NLS 实时语音识别，说"完毕"触发回复，无需鼠标键盘，适合休息时陪伴 |
| **观察模式** | ESP32-CAM 肩载摄像头自动转动云台拍照，AI 分析画面内容，发现值得关注的事物并记录 |
| **人体跟踪** | ESP32 实时推流 + MediaPipe Pose，舵机自动跟随人物移动 |

### 🔌 技能系统 · 插件式扩展

莲心的技能采用**插件式架构**，每个技能是 `skills/` 下的独立目录，包含 `SKILL.md`（知识注入）和 `tools.py`（工具定义）。运行时按需激活，工具自动注册到全局调度表。

| 技能 | 用途 | 默认 |
|------|------|:---:|
| 🎙️ 语音合成 | GPT-SoVITS 声音克隆 + 5 情绪表达 | ✅ |
| 🌐 浏览器自动化 | Playwright 网页控制（导航/点击/填表/截图） | ✅ |
| 📷 肩部外设控制 | ESP32-CAM 云台 + 观察 + 人体跟踪 | ✅ |
| 📖 日记与备忘 | 日记读写 + 备忘本整理 | ✅ |
| 🎵 音乐播放控制 | 音乐盒播放/暂停/切歌/音量 | ✅ |
| 💻 系统信息工具 | CPU/内存/磁盘/网络状态查询 | ❌ |
| 📚 学习助手 | 学习方法与记忆力建议 | ❌ |

> 渐进式披露架构：技能知识按需注入 System Prompt，与全量注入相比节省 **78% Token**。

### 🧠 记忆系统 · 双引擎

```
┌──────────────────────────────────────────────────┐
│               双记忆引擎架构                        │
├─────────────────────┬────────────────────────────┤
│  五元组图记忆         │  分类事实记忆               │
│  (主, 谓, 宾, 时, 源) │  6 大分类结构化存储          │
│  SQLite 图结构        │  SQLite 全文索引             │
│  多跳关系查询         │  关键词 + 语义搜索            │
├─────────────────────┴────────────────────────────┤
│  自动提取 · 每 N 轮触发 · 统一搜索接口              │
│  跨会话持久化 · 滑动窗口 · 智能压缩                 │
└──────────────────────────────────────────────────┘
```

**6 大记忆分类**：档案 · 偏好 · 事件 · 知识 · 行为 · 技能

### 🎭 情感系统

莲心拥有 **涟漪情感引擎**，不是简单的情绪标签，而是持续演化的情感状态：

- **16 种事件检测**：欺骗、否定、使唤、道歉、深聊、夸奖、感谢等
- **多维状态向量**：好感度、信任度、疲惫度、防御值
- **主动聊天调度**：根据时段 + 情感状态 + 用户活跃度智能触发
- **防御模式**：被频繁使唤时自动限制工具可用性
- **表情包联动**：16 种情绪表情自然表达，Galgame 立绘同步切换

### 🌐 联网搜索 · 四通道

```
web_search → fetch_webpage (HTTP 直连)
          → fetch_webpage_via_api (API 代理)
          → fetch_webpage_browser (Playwright 完整渲染)
          → fetch_webpage_stealth (反检测增强)
失败自动降级 · MCP 外部搜索增强 · 额度耗尽自动回退
```

### 🔗 MCP 协议支持

兼容 **Model Context Protocol**，可接入外部 MCP 服务扩展能力：
- 自动扫描 `mcp_servers/` 目录注册服务
- 统一 `mcp__{service}__{tool}` 命名路由
- 内置知乎搜索 MCP 服务

---

## 🏗️ 技术架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         main.py                                   │
│           单实例互斥 · 高DPI适配 · qdarkstyle 暗色主题              │
├──────────────────────────────────────────────────────────────────┤
│                     GUI Layer (PyQt5)                              │
│  ┌────────────┬──────────────┬──────────────┬──────────────────┐ │
│  │ MainWindow │ ChatWidget   │ InputPanel   │ CharacterWidget  │ │
│  │ 主窗口      │ 聊天气泡      │ 输入面板      │ 角色动画/表情     │ │
│  ├────────────┼──────────────┼──────────────┼──────────────────┤ │
│  │ Galgame模式 │ 设置/配置面板 │ 工具对话框群  │ 20+ 弹窗组件     │ │
│  └────────────┴──────────────┴──────────────┴──────────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│                    Intent Router (brain/intent_router.py)          │
│     策略A: 本地 Ollama 小模型意图分类 → 预选工具集                  │
│     策略B: 规则路由 (brain/decision.py) 兜底                       │
├──────────────────────────────────────────────────────────────────┤
│                    Agent Core (brain/agent.py)                     │
│     LiteLLM 统一网关 · Function Calling 对话循环                    │
│     工具并行执行(ThreadPool) · 资源锁分组 · 线程亲和性              │
├───────────────────┬──────────────────────────────────────────────┤
│  Tool Layer (50+)  │  Skill System (7 skills)                     │
│  brain/tools.py    │  brain/skill_manager.py                      │
│  文件·系统·网络     │  自动发现→激活→工具注入→System Prompt注入       │
│  视觉·记忆·音乐     │  渐进式披露 · 动态加载                        │
│  闹钟·待办·外设     │                                              │
├───────────────────┴──────────────────────────────────────────────┤
│                      Memory Engine                                 │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐   │
│  │ graph_memory.py      │  │ SQLite: entities + edges + facts │   │
│  │ 五元组图CRUD+查询     │  │ WAL模式 · 并发安全 · 索引优化    │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐   │
│  │ context_compressor.py│  │ memory_store.py                  │   │
│  │ 长对话智能摘要        │  │ 分类事实存取 · 格式化              │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────┤
│                    MCP Bridge (brain/mcp/)                         │
│     Registry → Client → Manager → 统一工具路由                    │
├──────────────────────────────────────────────────────────────────┤
│                    Emotional Engine (brain/emotional/)             │
│     Event Detection → State Update → Prompt Injection              │
├──────────────────────────────────────────────────────────────────┤
│                    Background Workers (workers/)                   │
│  AgentWorker │ VoiceWorker │ SpeakerWorker │ QQBridgeWorker       │
│  ProactiveWorker │ HeartbeatWorker │ StandbyWorker                │
│  ObservationModeWorker │ TrackWorker │ SmartReminderWorker        │
│  ListeningWorker │ OCRWorker │ TrackFrameReceiver │ PoseDetector   │
├──────────────────────────────────────────────────────────────────┤
│                  External APIs & Hardware                          │
│  ┌─────────┬──────────┬──────────┬──────────┬──────────────────┐ │
│  │DeepSeek │ Agnes AI │SiliconFlow│ Ollama  │ 阿里云 NLS        │ │
│  ├─────────┼──────────┼──────────┼──────────┼──────────────────┤ │
│  │GPT-SoVITS│Edge-TTS │ESP32-CAM │ SG90 舵机│ NapCatQQ          │ │
│  ├─────────┼──────────┼──────────┼──────────┼──────────────────┤ │
│  │Playwright│Tesseract│faster-Whisper│MediaPipe│                │ │
│  └─────────┴──────────┴──────────┴──────────┴──────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10+ |
| Python | 3.12（推荐 conda） |
| GPU | NVIDIA 显卡（可选，加速 GPT-SoVITS / 本地模型） |

### 安装

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

### 首次运行

```bash
python main.py
```

首次启动后，点击主界面 **🔑 按钮** 配置 API 密钥。配置文件自动保存在 `~/.lianxin/user_config.json`，之后每次启动自动加载。

### 开机自启

```bash
python main.py --autostart
```

> 自启模式下莲心会最小化到任务栏，不打扰你的正常使用。

---

## ⚙️ 配置详解

全部配置通过 GUI 的 API 配置对话框完成，也可手动编辑 `~/.lianxin/user_config.json`。

### AI 模型

| 配置项 | 说明 |
|--------|------|
| **DeepSeek API** | 默认提供商，模型 `deepseek-v4-flash`，支持 openai/anthropic 格式 |
| **Agnes AI** | 备选提供商，模型 `agnes-2.0-flash`，含图片/视频生成能力 |
| **Ollama 本地模型** | 勾选"使用本地模型"一键切换，配置地址和模型名即可 |
| **路由模型** | 独立配置意图分类用小模型（Ollama），留空则回退规则路由 |

> ⚠️ Ollama 本地模型不支持 Function Calling，切换后自动使用纯聊天模式。

### 语音

| 配置项 | 说明 |
|--------|------|
| **TTS 引擎** | auto / edge_tts / gpt_sovits |
| **GPT-SoVITS 路径** | 本地声音克隆引擎安装目录 |
| **默认情绪** | auto / casual / tsundere / romantic / long / angry |
| **语速** | 0.5 – 2.0 |
| **Edge-TTS 回退音色** | 默认 `zh-CN-XiaoxiaoNeural` |
| **参考音频覆盖** | 手动选择参考音频，覆盖情绪自动匹配 |

### QQ 桥接

| 配置项 | 说明 |
|--------|------|
| WebSocket 地址 | NapCatQQ 默认 `ws://127.0.0.1:3001` |
| QQ 账号 / 主人 QQ | 连接认证和权限识别 |
| 语音回复开关 | TTS 语音消息回复 |
| 定时参数 | 思考延迟、打字速度、分段阈值、全局限速、日限额 |

### 网络搜索

| 配置项 | 说明 |
|--------|------|
| 抓取通道开关 | HTTP / API 代理 / 浏览器 / 反检测 四个通道独立启用 |
| 重试策略 | 最大重试次数、回退策略（builtin/direct） |
| 代理 | HTTP/HTTPS 代理配置 |

---

## 📦 可选外部依赖

| 组件 | 用途 | 需单独部署 |
|------|------|:---:|
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ) | QQ 消息收发 | ✅ |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | 图片文字识别 | ✅ |
| [Ollama](https://ollama.com) | 本地模型运行 / 意图路由 | ❌ |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 高质量声音克隆 | ❌ |
| [Playwright](https://playwright.dev) | 浏览器自动化引擎 | ❌ |

---

## 🛠️ 内置工具清单

莲心向 AI 模型暴露 **50+ 个 Function Calling 工具**，按类别组织：

<details open>
<summary><b>📁 文件操作</b></summary>

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件（自动编码检测 + 分块） |
| `read_file_lines` | 读取指定行范围 |
| `read_file_chunk` | 分块读取大文件 |
| `write_file` | 写入/覆盖文件 |
| `edit_file` | 精确字符串替换编辑 |
| `list_directory` | 列出目录内容 |
| `search_files` | 按模式搜索文件（glob） |
| `grep_file` | 文件内容正则搜索 |
| `search_code` | 代码库跨文件搜索 |
| `read_excel` / `write_excel` | Excel 读写 |
| `write_docx` / `format_document` | Word 文档生成与格式化 |
| `diff_files` | 文件差异比较 |
| `code_structure` | 代码结构分析 |
| `goto_definition` / `find_references` | 代码智能跳转 |

</details>

<details open>
<summary><b>💻 系统命令</b></summary>

| 工具 | 说明 |
|------|------|
| `open_app` | 打开应用程序 |
| `run_command` | 执行系统命令（安全白名单） |
| `run_shell` | 执行 shell 命令 |
| `run_python_code` | 执行 Python 代码片段 |
| `get_clipboard` | 读取剪贴板内容 |

</details>

<details open>
<summary><b>🌐 联网搜索</b></summary>

| 工具 | 说明 |
|------|------|
| `web_search` | 网页搜索（搜索引擎） |
| `fetch_webpage` | HTTP 直接抓取 |
| `fetch_webpage_via_api` | API 代理抓取（穿透力强） |
| `fetch_webpage_browser` | Playwright 浏览器渲染抓取 |
| `fetch_webpage_stealth` | 增强反检测抓取 |

</details>

<details open>
<summary><b>🔍 视觉理解</b></summary>

| 工具 | 说明 |
|------|------|
| `describe_image` | AI 图片内容描述 |
| `ocr_image` | OCR 文字识别 |
| `camera_capture` | 摄像头拍照 |
| `screenshot` | 屏幕截图 |

</details>

<details open>
<summary><b>🧠 记忆与任务</b></summary>

| 工具 | 说明 |
|------|------|
| `save_memory` / `update_memory` / `delete_memory` | 分类事实 CRUD |
| `search_graph_memory` | 统一搜索（事实 + 图边） |
| `add_todo` / `list_todos` / `complete_todo` | 待办管理 |

</details>

<details open>
<summary><b>📅 信息查询</b></summary>

| 工具 | 说明 |
|------|------|
| `get_current_time` | 当前时间/日期/星期 |
| `get_balance` | 查询 API 余额 |
| `get_system_info` | CPU/内存/磁盘/GPU 状态 |
| `get_weather` | 天气查询（和风天气） |

</details>

<details open>
<summary><b>🎵 音乐 · 📖 日记 · ⏰ 闹钟 · 🔗 跨端</b></summary>

| 工具 | 说明 |
|------|------|
| `control_music` / `get_music_playlist` / `get_music_status` | 音乐盒控制 |
| `read_diary` / `write_diary` | 日记读写 |
| `read_note` / `organize_note` | 备忘本读写与整理 |
| `add_alarm` / `list_alarms` / `delete_alarm` | 闹钟管理 |
| `search_cross_session` | 跨会话/跨设备搜索 |
| `send_to_phone` | 发送内容到手机 |

</details>

<details open>
<summary><b>🎙️ 语音 · 🌐 浏览器 · 📷 外设</b></summary>

| 工具 | 说明 |
|------|------|
| `speak_voice` / `set_voice_mood` / `list_voice_styles` | 语音合成与情绪切换 |
| `browser_navigate` / `browser_snapshot` / `browser_click` / `browser_fill` / `browser_screenshot` | Playwright 浏览器控制 |
| `shoulder_photo` / `shoulder_pan` / `shoulder_tilt` / `shoulder_center` / `shoulder_status` / `shoulder_temp` | 肩载摄像头云台控制 |
| `start_observation_mode` / `stop_observation_mode` / `shoulder_observe` | 观察模式 |
| `shoulder_human_track` / `stop_human_track` | 人体跟踪 |

</details>

---

## 🔧 外设项目

莲心支持 **ESP32-CAM 肩载摄像头 + SG90 舵机云台** 物理外设：

```
ESP32-CAM (肩载) ←→ Cloud Relay (WebSocket) ←→ 莲心 PC
                        ↓
              SG90 舵机 (水平/垂直旋转)
```

- 📷 拍照 + AI 视觉分析
- 🔍 观察模式：自动扫描周围环境
- 🧍 人体跟踪：MediaPipe Pose + 舵机跟随
- 🌡️ 温湿度传感器查询

> 硬件项目地址：[lianxin-ai-esp32](https://gitee.com/luke23334/lianxin-ai-esp32)

---

## 📁 项目结构

```
莲心AI/
├── main.py                  # 入口：单实例互斥 · DPI适配 · 自启管理
├── config.py                # 全局配置：API/视觉/TTS/记忆/QQ/代理等30+配置项
├── aliyun_stt.py            # 阿里云NLS实时语音识别
├── requirements.txt         # Python依赖
│
├── brain/                   # 🧠 核心大脑
│   ├── agent.py             #   AgentCore：LiteLLM网关 + Function Calling循环
│   ├── tools.py             #   50+工具定义与执行调度
│   ├── intent_router.py     #   意图路由器：小模型分类 + 规则兜底
│   ├── decision.py          #   规则路由（正则匹配）
│   ├── skill_manager.py     #   技能系统：发现→激活→工具注入
│   ├── tts_engine.py        #   语音合成：GPT-SoVITS + Edge-TTS + 情绪匹配
│   ├── graph_memory.py      #   五元组图记忆 + 分类事实 (SQLite)
│   ├── memory_store.py      #   记忆格式化与统一查询
│   ├── context_compressor.py #  长对话智能压缩
│   ├── code_intel.py        #   代码智能：跳转定义/找引用
│   ├── observation_engine.py #  观察探索引擎System Prompt
│   ├── observation_mode.py  #   观察模式状态管理+费用追踪
│   ├── observation_store.py #   观察记录持久化
│   ├── observation.py       #   观察数据结构
│   ├── quintuple_extractor.py # 五元组自动提取
│   ├── human_tracking.py    #   人体跟踪状态管理
│   ├── hardware_bridge.py   #   ESP32 WebSocket 云桥接
│   ├── browser_controller.py #  Playwright 浏览器控制
│   ├── heartbeat.py         #   心跳自检引擎
│   ├── notebook.py          #   笔记本/代码执行
│   ├── task_tracker.py      #   任务追踪
│   ├── weather.py           #   和风天气集成
│   ├── vision.py            #   视觉分析统一入口
│   ├── audio_utils.py       #   音频工具
│   ├── emotional/           #   🎭 涟漪情感引擎
│   │   ├── state.py         #       情感状态向量
│   │   ├── events.py        #       16种事件检测
│   │   └── manager.py       #       情感管理器
│   └── mcp/                 #   🔗 MCP协议支持
│       ├── mcp_manager.py   #       统一调用路由
│       ├── mcp_registry.py  #       服务注册/发现
│       ├── mcp_client.py    #       MCP客户端
│       ├── mcp_agent_base.py #      Agent基类
│       └── mcp_bridge.py    #       MCP桥接
│
├── gui/                     # 🖥️ PyQt5 图形界面
│   ├── main_window.py       #   主窗口：热键·事件·状态流转
│   ├── character_widget.py  #   角色动画组件（GIF序列帧）
│   ├── chat_widget.py       #   聊天气泡列表
│   ├── input_panel.py       #   输入面板：语音·文字·表情·工具
│   ├── message_bubble.py    #   消息气泡渲染
│   ├── animation_state_machine.py # 动画状态机
│   ├── spectrum_widget.py   #   频谱可视化
│   ├── task_progress_bar.py #   任务进度条
│   ├── api_config_dialog.py #   API配置面板
│   ├── settings_dialog.py   #   全局设置
│   ├── capability_center.py #   能力中心总览
│   ├── alarm_dialog.py      #   闹钟管理
│   ├── diary_dialog.py      #   日记查看
│   ├── todo_dialog.py       #   待办清单
│   ├── note_dialog.py       #   备忘本
│   ├── history_dialog.py    #   聊天记录
│   ├── accompany_dialog.py  #   陪伴统计
│   ├── pomodoro_dialog.py   #   番茄钟
│   ├── music_list_dialog.py #   音乐盒
│   ├── proactive_dialog.py  #   主动聊天设置
│   ├── reminder_dialog.py   #   提醒管理
│   ├── camera_dialog.py     #   摄像头预览
│   ├── quick_launch_dialog.py # 快捷启动
│   ├── qq_settings_dialog.py #  QQ桥接配置
│   ├── network_settings_dialog.py # 网络/代理配置
│   ├── sound_settings_dialog.py   # 音效设置
│   ├── memory_settings_dialog.py  # 记忆系统设置
│   ├── emotional_debug_dialog.py  # 情感系统调试面板
│   └── galgame/             #   🎮 Galgame模式
│       ├── tachie_window.py      #   透明立绘窗口
│       ├── galgame_dialog.py     #   可拖拽拉伸对话框
│       ├── live2d_widget.py      #   Live2D动画支持
│       └── expression_manager.py #   表情/情绪联动
│
├── workers/                 # ⚙️ 后台工作线程
│   ├── agent_worker.py      #   Agent对话线程
│   ├── voice_worker.py      #   语音识别线程
│   ├── speaker_worker.py    #   语音合成线程
│   ├── listening_worker.py  #   持续监听线程
│   ├── qq_bridge_worker.py  #   QQ桥接WebSocket线程
│   ├── proactive_worker.py  #   主动聊天调度线程
│   ├── heartbeat_worker.py  #   心跳检测线程
│   ├── standby_worker.py    #   待机模式线程
│   ├── observation_mode_worker.py # 观察模式循环
│   ├── track_worker.py      #   人体跟踪统一线程
│   ├── track_frame_receiver.py   # 跟踪帧接收
│   ├── track_pose_detector.py    # Pose推理
│   ├── ocr_worker.py        #   OCR后台线程
│   ├── smart_reminder_worker.py  # 智能提醒
│   └── qq_bridge_worker.py  #   QQ桥接
│
├── voice/                   # 🎤 语音子系统
│   ├── listener.py          #   录音+VAD+Whisper识别
│   └── speaker.py           #   音频播放
│
├── vision/                  # 👁️ 视觉子系统
│   ├── face_detector.py     #   人脸检测+微笑识别
│   ├── gesture_detector.py  #   手势检测
│   └── vision_worker.py     #   视觉线程（人脸/表情/手势）
│
├── memory/                  # 💾 数据持久化
│   └── history_manager.py   #   对话历史SQLite管理
│
├── utils/                   # 🔧 工具模块
│   ├── settings.py          #   全局设置管理
│   ├── paths.py             #   路径管理+旧数据迁移
│   ├── alarm_manager.py     #   闹钟管理
│   ├── todo_manager.py      #   待办管理
│   ├── reminder_manager.py  #   提醒管理
│   ├── diary.py             #   日记引擎
│   ├── note_manager.py      #   备忘本管理
│   ├── proactive_chat.py    #   主动聊天调度器
│   ├── accompany_stats.py   #   陪伴统计
│   ├── pomodoro_stats.py    #   番茄钟统计
│   ├── music_stats.py       #   音乐播放统计
│   ├── emotion_manager.py   #   表情图片管理
│   ├── balance.py           #   API余额查询
│   ├── camera.py            #   摄像头工具
│   ├── sound.py             #   音效播放
│   └── autostart.py         #   开机自启管理
│
├── skills/                  # 🔌 技能包（插件式）
│   ├── 语音合成/            #   GPT-SoVITS + 情绪
│   ├── 浏览器自动化/        #   Playwright
│   ├── 肩部外设控制/        #   ESP32 云台
│   ├── 日记与备忘/          #
│   ├── 音乐播放控制/        #
│   ├── 系统信息工具/        #
│   └── _prompt_guides/      #   System Prompt 渐进式注入模块 (10个)
│
├── mcp_servers/             # 🔗 MCP服务
│   └── zhihu_search/        #   知乎搜索
│
├── alibabacloud-nls-python-sdk/ # 阿里云NLS官方SDK（内置）
│
└── assets/                  # 🎨 静态资源
    ├── GIF/                 #   角色动画序列帧
    ├── 备份GIF/             #   动画备份
    ├── meme/                #   表情包图片
    ├── sound/               #   系统音效
    ├── music/               #   内置音乐
    ├── icons/               #   图标
    └── animation_config.json # 动画配置
```

---

## 🧬 数据流

```
用户输入 (文字/语音/QQ消息)
    │
    ▼
┌──────────────┐    规则路由(兜底)
│ IntentRouter ├────────────┐
│ 小模型分类    │            │
└──────┬───────┘            │
       │ route + tools      │
       ▼                    ▼
┌─────────────────────────────────────┐
│           AgentCore                  │
│  System Prompt 组装                  │
│  ├── 人格设定 (_BASE_PROMPT)         │
│  ├── 记忆注入 (图记忆 + 分类记忆)     │
│  ├── 情感状态 (涟漪引擎)              │
│  ├── 技能知识 (激活的技能SKILL.md)    │
│  ├── 渐进式技能模块 (关键词匹配)      │
│  └── MCP服务描述                     │
│                                      │
│  Function Calling 循环               │
│  ├── LiteLLM → AI API                │
│  ├── 工具并行执行 (ThreadPool)        │
│  ├── 资源锁调度 (浏览器/硬件/DB)       │
│  └── 结果回传                         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│           后处理                      │
│  情感分析 → 状态更新                  │
│  记忆提取 → 五元组+分类事实            │
│  对话压缩 → 上下文摘要(如需)           │
│  TTS合成 → 语音输出(如需)             │
│  QQ发送 → 消息推送(如需)              │
│  历史记录 → SQLite持久化              │
└─────────────────────────────────────┘
```

---

## 📝 开发记录

详见 `莲心AI开发档案记录.docx`

---

<div align="center">
<img src="assets/主界面背景图/主界面背景图.jpg" alt="主界面" width="100%" />

*莲心 AI 主界面*

<br>

Made with ❤️ by [luke23334](https://gitee.com/luke23334)

[![Gitee](https://img.shields.io/badge/Gitee-仓库地址-C71D23?logo=gitee)](https://gitee.com/luke23334/lianxin-ai)

</div>
