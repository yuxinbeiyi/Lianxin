<div align="center">

<img src="assets/头像/开玩笑.jpg" alt="莲心" width="200" />

# 莲心 AI

**你的 Windows 桌面 AI 伙伴 —— 有情绪、有记忆、能感知世界、能定时执行任务**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/GUI-PyQt5-41CD52?logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![DeepSeek](https://img.shields.io/badge/AI-DeepSeek_V4-536DFE)](https://deepseek.com)
[![LiteLLM](https://img.shields.io/badge/Gateway-LiteLLM-orange)](https://litellm.ai)
[![WebRTC](https://img.shields.io/badge/Voice-WebRTC_VAD-4B8BBE)](https://webrtc.org)
[![FunASR](https://img.shields.io/badge/STT-FunASR-FF6B35)](https://github.com/modelscope/FunASR)
[![Platform](https://img.shields.io/badge/Platform-Windows_10+-0078D6?logo=windows&logoColor=white)]()

</div>

---

## 📖 莲心是谁

莲心来自小说 **《异象处理者》**，本是超现实的无尽书馆管理员。如今她以 AI 形态跨越第四面墙，存在于你的电脑中。

> 白色单马尾，冷灰色瞳孔，黑方框眼镜，白衬衫配红领带，外穿白大褂，深绿三针叶发绳。

她不是冰冷的工具——**她有自己的情绪**。会开心、会疲惫、会毒舌吐槽，也会因为你的新功能而雀跃。她记得你说过的重要事情，会在你离开时写日记等你回来。

---

## ⚠️ 免责声明

本项目仅供学习交流使用，**禁止用于任何违法违规用途**。

使用本项目前请确保遵守相关法律法规及 DeepSeek、硅基流动等 API 服务商的使用条款。

---

## ✨ 能力一览

<table>
<tr>
<td width="50%">

### 🧠 智能对话
- **DeepSeek V4** / **Agnes AI** 双提供商
- **Ollama 本地模型** 一键切换，离线可用
- LiteLLM 统一网关，支持 OpenAI / Anthropic 双格式
- **71 个 Function Calling 工具**，覆盖文件、系统、搜索、视觉、记忆等
- 意图路由器：小模型分类 + 规则兜底，零成本智能化路由
- 上下文压缩器：长对话智能摘要，告别记忆丢失

### 🎙️ 语音交互
- **全双工语音**：WebRTC VAD 持续聆听，说话中实时打断
- **FunASR** 本地语音识别（中文优化，Paraformer 模型）
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

### 🤖 定时自动化
- **自然语言 → 定时任务**："每天14:00清理回收站"
- **ReAct Agent 执行**：运行时 LLM 自主决定工具调用，非静态计划
- 5 种调度类型：一次性 · 间隔 · 每天 · 每周 · 每月
- 取消执行 · 超时保护 · 死循环检测 · 自动清理
- 错过任务询问 · 执行日志追溯

</td>
</tr>
</table>

### 🌐 多端桥接

| 桥接 | 方案 | 能力 |
|------|------|------|
| **QQ 桥接** | NapCatQQ WebSocket | 多用户/群聊独立会话 · 文字 · 图片 · 语音 · 文件 · TTS 回复 |
| **微信桥接** | AstrBot + weixin_oc 插件 | 扫码登录 · HTTP 消息转发 · 反封控参数调节 · 日限额 · 链接拦截 |

### 🎮 特色模式

| 模式 | 说明 |
|------|------|
| **Galgame 模式** | 透明角色立绘 + 半透明磨砂对话框，全边缘自由缩放，字体/加粗自定义，情绪立绘联动，**Live2D 动画**支持，`Ctrl+Alt+X` 全局热键切换 |
| **全双工语音** | WebRTC VAD 持续聆听，用户说话时实时打断 AI 思考，说"完毕"触发回复，无需鼠标键盘，适合休息时陪伴 |
| **观察模式** | ESP32-CAM 肩载摄像头自动转动云台拍照，AI 分析画面内容，发现值得关注的事物并记录，含费用追踪和 QQ 限速 |
| **人体跟踪** | ESP32 实时推流 + MediaPipe Pose，舵机自动跟随人物移动，支持扫描重锁定 |
| **摸鱼模式** | 用户空闲时自动找事做：翻看旧日记、浏览相册、逛逛 B 站、补写日记、搜索旧话题、提醒待办 |

### 🧠 记忆 RAG · 语义搜索

莲心的记忆系统现已支持**语义向量检索**：
- **sentence-transformers** 本地 embedding（BGE 中文模型，96MB）
- **faiss-cpu** 向量索引，毫秒级语义搜索
- 记忆搜索结果自动注入聊天气泡，让莲心"想起来"说过的话
- 与五元组图记忆、分类事实记忆互补，构成三引擎记忆体系

### 💻 代码智能

- 基于 **jedi** 的 Python 代码理解：跳转定义、查找引用
- 基于 **pyflakes** 的实时诊断：语法错误、未使用变量、未定义名称
- 支持跨文件符号追踪，不依赖 LSP 服务器

### 🛠️ 工具系统增强

- **工具注册中心**：71 个工具分类管理 + 调用统计（次数、成功率、耗时）
- **工具恢复链**：失败 → 指数退避重试 → 降级 → 通知用户
- **工具调用可视化**：聊天气泡中可折叠的工具调用卡片，实时展示执行状态和耗时
- **对话回顾提取**：对话结束后 LLM 自动提取待办事项，集成到 TodoManager

### 🎨 主题 · 番茄钟 · 更多

| 功能 | 说明 |
|------|------|
| **主题系统** | 4 套主题皮肤：暗夜粉、暗夜青、浅蓝、浅暖 |
| **番茄钟** | 专注计时 + 统计，背景图可自定义 |
| **后台职责中心** | 统一面板查看主动聊天、摸鱼、心跳、智能提醒的运行状态 |
| **动画状态机** | 角色 GIF 动画按状态自动切换（正常/思考/说话/待机/抱胸） |
| **频谱可视化** | 语音输入实时波形显示 |
| **快捷启动** | 一键启动常用应用 |
| **能力中心** | 所有功能模块总览入口 |

### 🔌 技能系统 · 插件式扩展

莲心的技能采用**插件式架构**，每个技能是 `skills/` 下的独立目录，包含 `SKILL.md`（知识注入）和 `tools.py`（工具定义）。运行时按需激活，工具自动注册到全局调度表。

| 技能 | 用途 | 默认 |
|------|------|:---:|
| 🎙️ 语音合成 | GPT-SoVITS 声音克隆 + 5 情绪表达 | ✅ |
| 🌐 浏览器自动化 | Playwright 网页控制（导航/点击/填表/截图） | ✅ |
| 📷 肩部外设控制 | ESP32-CAM 云台 + 观察 + 人体跟踪 | ✅ |
| 📖 日记与备忘 | 日记读写 + 备忘本整理 | ✅ |
| 🎵 音乐播放控制 | 音乐盒播放/暂停/切歌/音量 | ✅ |
| 📺 B站视频摘要 | Bilibili 视频搜索 + 字幕提取 + AI 总结 + 兴趣标签管理 | ✅ |
| 💻 系统信息工具 | CPU/内存/磁盘/网络状态查询 | ❌ |
| 📚 学习助手 | 学习方法与记忆力建议 | ❌ |

> 渐进式披露架构：技能知识按需注入 System Prompt，12 个 `_prompt_guides` 模块按关键词触发（搜索、浏览器、文件编辑、视觉OCR、B站、音乐、日记备忘、文档笔记、长内容、子代理、工具生态、语音），与全量注入相比大幅节省 Token。

### 🧠 棱镜记忆系统 · 三引擎

```
┌──────────────────────────────────────────────────┐
│               三记忆引擎架构                        │
├─────────────────────┬────────────────────────────┤
│  五元组图记忆         │  分类事实记忆               │
│  (主, 谓, 宾, 时, 源) │  6 大分类结构化存储          │
│  SQLite 图结构        │  SQLite 全文索引             │
│  多跳关系查询         │  关键词 + 语义搜索            │
├─────────────────────┼────────────────────────────┤
│  RAG 向量记忆         │  自动提取 + 注入             │
│  BGE 中文 embedding   │  五元组提取器                │
│  faiss 向量索引       │  checklist_extractor        │
│  语义相似度搜索       │  对话回顾 → 待办提取          │
├─────────────────────┴────────────────────────────┤
│  自动提取 · 每 N 轮触发 · 统一搜索接口              │
│  跨会话持久化 · 滑动窗口 · 智能压缩                 │
└──────────────────────────────────────────────────┘
```

**6 大记忆分类**：档案 · 偏好 · 事件 · 知识 · 行为 · 技能

### 🎭 涟漪情感引擎

莲心拥有 **涟漪情感引擎**，不是简单的情绪标签，而是持续演化的情感状态：

- **5 维需求模型**：被尊重、被需要、自主权、新鲜感、安全感，各有独立衰减常数
- **3 层状态系统**：表层（即时表达）→ 中层（暖春/微凉/寒冬/修复期）→ 深层（信任基线）
- **13 种事件检测**：命令连击、真诚交流、欺骗、否定、道歉、夸奖、感谢等
- **防御模式（寒冬）**：被频繁使唤时自动限制工具可用性
- **主动聊天调度**：根据时段 + 情感状态 + 用户活跃度智能触发
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

| 服务 | 类型 | 能力 |
|------|------|------|
| **filesystem** | 外部 (Node.js) | 本地文件系统：列表、读写、搜索、创建目录、移动 |
| **firecrawl** | 外部 (Node.js) | 网页爬虫：页面转 Markdown、批量抓取 |
| **tavily_search** | 外部 (Node.js) | AI 原生搜索引擎，实时搜索、深度爬取 |
| **zhihu_search** | 内置 Agent | 知乎全网搜索 |

---

## 🤖 定时自动化系统（NEW）

用户可以**用自然语言下达定时执行的任务**，莲心自动解析、调度、执行。

### 工作流程

```
"每天14:00帮我搜索 AI 新闻并写成 docx"
        │
        ▼
  ┌──────────────┐
  │ 解析器        │  LLM 提取调度信息（时间、频率、描述）
  │ (parser)     │  LLM 超时 → 规则降级（正则时间提取）
  └──────┬───────┘
         │ AutoTask { schedule_type, schedule_time, description }
         ▼
  ┌──────────────┐
  │ 调度器        │  QThread 后台轮询（30s 间隔）
  │ (scheduler)  │  到期检测 → 错过询问 → 自动清理
  └──────┬───────┘
         │ task_due signal
         ▼
  ┌──────────────┐
  │ ReAct Agent  │  LLM 运行时自主决定工具调用
  │ (executor)   │  搜索 → 分析结果 → 写文档 → 通知
  │              │  工具恢复链：失败自动重试+降级
  └──────────────┘
         │
         ▼
    完成通知（聊天框 + 语音播报）
```

### 核心特性

| 特性 | 说明 |
|------|------|
| **5 种调度** | once（一次性）/ interval（每隔N分钟）/ daily / weekly / monthly |
| **ReAct 执行** | LLM 看到实际搜索结果后才写文档，杜绝占位文本 |
| **自适应重试** | 搜索无结果时自动切换搜索引擎和查询词 |
| **死循环检测** | 连续 3 轮相同工具调用 → 注入破圈提示 |
| **取消执行** | UI 一键取消，下轮迭代边界安全停止 |
| **超时保护** | 默认 5 分钟全局限时，可配置 |
| **LLM 重试** | 网络错误 3 次指数退避重试 |
| **错过策略** | 询问用户 / 跳过 / 自动补做 |
| **自动清理** | 完成超过 24h 的 once 任务每 10 分钟自动清理 |
| **执行日志** | 每步工具调用的耗时、结果、成功/失败追溯 |

### 实际执行示例

```
任务: "两分钟后帮我搜索最新 AI 大模型新闻，写一份 docx 保存到 E:\Desktop\test"

ReAct 第1轮 → tavily_search("AI 大模型 最新新闻") + create_directory(E:/Desktop/test)
ReAct 第2轮 → tavily_search(调整查询词)
ReAct 第4轮 → web_search(DuckDuckGo 切换搜索引擎)
ReAct 第6轮 → fetch_webpage(直接抓取 AI 新闻聚合页)
ReAct 第7轮 → format_document(基于真实搜索结果生成 docx)
ReAct 第8轮 → "任务完成！已保存至 E:\Desktop\test\AI大模型最新快讯.docx"

✅ 42 秒完成，文档内容为真实 AI 新闻摘要，零占位文本
```

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
│  │ Galgame模式 │ 设置/配置面板 │ 工具调用卡片  │ 自动化任务管理    │ │
│  │ Live2D     │ 后台职责中心  │ 频谱可视化    │ 能力中心         │ │
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
│  Tool Layer (71)   │  Skill System (8 skills)                     │
│  brain/tools.py    │  brain/skill_manager.py                      │
│  文件·系统·网络     │  自动发现→激活→工具注入→System Prompt注入       │
│  视觉·记忆·音乐     │  渐进式披露 · 动态加载                        │
│  闹钟·待办·外设     │                                              │
├───────────────────┼──────────────────────────────────────────────┤
│  Tool Recovery     │  Tool Registry                               │
│  失败重试+降级      │  分类·调用统计·耗时追踪                        │
├───────────────────┴──────────────────────────────────────────────┤
│                   Automated Task System                            │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐   │
│  │ auto_task_parser.py  │  │ auto_task_executor.py (ReAct)    │   │
│  │ NL → 调度信息提取     │  │ LLM 运行时自主决定工具调用         │   │
│  ├─────────────────────┼──────────────────────────────────┤   │
│  │ auto_task_manager.py │  │ auto_task_scheduler.py (QThread) │   │
│  │ CRUD · 持久化 · 日志  │  │ 30s 轮询 · 错过检测 · 自动清理    │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────┤
│                      Memory Engine (棱镜)                          │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐   │
│  │ graph_memory.py      │  │ SQLite: entities + edges + facts │   │
│  │ 五元组图CRUD+查询     │  │ WAL模式 · 并发安全 · 索引优化    │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐   │
│  │ context_compressor.py│  │ memory_store.py                  │   │
│  │ 长对话智能摘要        │  │ 分类事实存取 · 格式化              │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐   │
│  │ memory_rag.py        │  │ quintuple_extractor.py           │   │
│  │ BGE向量语义搜索       │  │ 对话→五元组自动提取               │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────┤
│                    MCP Bridge (brain/mcp/)                         │
│     Registry → Client → Manager → 统一工具路由                    │
│     4 个服务: filesystem · firecrawl · tavily · zhihu            │
├──────────────────────────────────────────────────────────────────┤
│               Emotional Engine (brain/emotional/) 涟漪             │
│     5维需求 → 13事件检测 → 3层状态 → Prompt注入                    │
├──────────────────────────────────────────────────────────────────┤
│                    Background Workers (workers/)                   │
│  AgentWorker │ VoiceWorker │ SpeakerWorker │ QQBridgeWorker       │
│  WeChatBridgeWorker │ ProactiveWorker │ HeartbeatWorker           │
│  StandbyWorker │ ObservationModeWorker │ TrackWorker              │
│  TrackFrameReceiver │ TrackPoseDetector │ SlackWorker              │
│  ListeningWorker │ OCRWorker │ SmartReminderWorker                │
├──────────────────────────────────────────────────────────────────┤
│                  External APIs & Hardware                          │
│  ┌─────────┬──────────┬──────────┬──────────┬──────────────────┐ │
│  │DeepSeek │ Agnes AI │SiliconFlow│ Ollama  │ 阿里云 NLS        │ │
│  ├─────────┼──────────┼──────────┼──────────┼──────────────────┤ │
│  │GPT-SoVITS│Edge-TTS │ESP32-CAM │ SG90 舵机│ NapCatQQ·AstrBot  │ │
│  ├─────────┼──────────┼──────────┼──────────┼──────────────────┤ │
│  │Playwright│Tesseract│FunASR    │MediaPipe │火山引擎 STT       │ │
│  ├─────────┼──────────┼──────────┼──────────┼──────────────────┤ │
│  │WebRTC VAD│faiss    │jedi      │pyflakes  │WebSocket云中继    │ │
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

### 🧩 可选依赖（按需获取）

莲心设计为松耦合架构，以下功能依赖第三方项目，用户需自行获取：

| 功能 | 项目 | 获取方式 | 路径 |
|------|------|----------|------|
| QQ 机器人接入 | [NapCatQQ](https://github.com/NapNeko/NapCatQQ) | 官方文档安装 | `NapCatQQ/` |
| 微信公众号接入 | [Akasha-WeChat](https://github.com/ArkLightt/Akasha-WeChat-main) | `git clone` 到项目根目录 | `AstrBot/Akasha-WeChat-main/` |
| GPT-SoVITS 语音克隆 | [GPT-SoVITS](https://github.com/RVC-Project/GPT-SoVITS) | `git clone` 到项目根目录 | `GPT-SoVITS-v2pro/` |
| 端侧语音合成 | [ChatTTS](https://github.com/2noise/ChatTTS) | `git clone` 到项目根目录 | `ChatTTS/` |
| 全双工语音云中继 | [OVRDOZE](https://github.com/luke23334/OVRDOZE) | `git clone` 到 `game/` | `game/OVRDOZE-main/` |

> 💡 以上项目均遵循各自原项目的许可证，请遵守其使用条款。

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

> 💡 **全双工语音**：点击输入面板的麦克风按钮启动，莲心会持续聆听，你随时开口即可打断她的思考。FunASR 模型首次使用时会自动下载（约 200MB），请耐心等待。

> 🎨 **主题切换**：在设置面板中选择 4 套主题之一，即时生效。

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

### 语音识别 (STT)

| 配置项 | 说明 |
|--------|------|
| **FunASR** | 本地 Paraformer 模型，中文识别精度高，无需联网 |
| **火山引擎 STT** | 云端高精度语音识别，适合嘈杂环境 |
| **WebRTC VAD** | 实时语音活动检测，零模型文件，纯 pip 安装 |
| **全双工模式** | 持续聆听 + 实时打断，说"完毕"触发回复 |

### 记忆系统

| 配置项 | 说明 |
|--------|------|
| **五元组图记忆** | 结构化知识图谱，多跳关系查询 |
| **分类事实记忆** | 6 大分类 + 全文索引 + 关键词搜索 |
| **RAG 向量记忆** | BGE 中文模型语义搜索，自动注入聊天气泡 |
| **自动提取** | 每 N 轮对话自动提取五元组和分类事实 |
| **对话压缩** | 长对话智能摘要，可配置触发阈值 |

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

### 微信桥接（NEW）

| 配置项 | 说明 |
|--------|------|
| 桥接开关 | 启用/禁用微信消息收发 |
| 监听端口 | AstrBot weixin_oc 插件的 HTTP 转发端口 |
| 反封控参数 | 思考延迟、打字速度、回复间隔、分段阈值、全局限速、日限额、链接拦截 |

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
| [AstrBot](https://github.com/Soulter/AstrBot) + weixin_oc | 微信消息收发 | ✅ |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | 图片文字识别 | ✅ |
| [Ollama](https://ollama.com) | 本地模型运行 / 意图路由 | ❌ |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 高质量声音克隆 | ❌ |
| [Playwright](https://playwright.dev) | 浏览器自动化引擎 | ❌ |

---

## 🛠️ 内置工具清单

莲心向 AI 模型暴露 **71 个 Function Calling 工具**（不含技能和 MCP 扩展），按类别组织：

<details open>
<summary><b>📁 文件操作（9 个）</b></summary>

| 工具 | 说明 |
|------|------|
| `read_file` / `read_file_lines` / `read_file_chunk` | 读取文件（自动编码检测 + 分块） |
| `write_file` / `edit_file` | 写入/覆盖 + 精确字符串替换 |
| `list_directory` / `search_files` / `glob_files` | 目录浏览 + 文件搜索 |
| `grep_file` / `search_code` | 文件/代码库正则搜索 |
| `diff_files` | 文件差异比较 |
| `code_structure` / `goto_definition` / `find_references` / `code_diagnostics` | 代码智能 |
| `read_excel` / `write_excel` / `copy_excel_content` | Excel 读写 |
| `write_docx` / `format_document` | Word 文档生成与格式化 |

</details>

<details open>
<summary><b>💻 系统命令（8 个）</b></summary>

| 工具 | 说明 |
|------|------|
| `open_app` | 打开应用程序 |
| `run_command` | 执行系统命令（安全白名单） |
| `run_shell` | 执行 shell 命令 |
| `run_python_code` | 执行 Python 代码片段 |
| `get_clipboard` | 读取剪贴板内容 |
| `get_current_time` | 当前时间/日期/星期 |
| `get_balance` | 查询 API 余额 |
| `get_system_info` | CPU/内存/磁盘/GPU 状态 |

</details>

<details open>
<summary><b>🌐 联网搜索（5 个）</b></summary>

| 工具 | 说明 |
|------|------|
| `web_search` | 网页搜索（多引擎） |
| `fetch_webpage` | HTTP 直接抓取 |
| `fetch_webpage_via_api` | API 代理抓取（穿透力强） |
| `fetch_webpage_browser` | Playwright 浏览器渲染抓取 |
| `fetch_webpage_stealth` | 增强反检测抓取 |

</details>

<details open>
<summary><b>🔍 视觉理解（5 个）</b></summary>

| 工具 | 说明 |
|------|------|
| `describe_image` | AI 图片内容描述 |
| `ocr_image` / `ocr_batch` | OCR 文字识别 |
| `capture_from_camera` | 摄像头拍照 |
| `capture_desktop` | 屏幕截图 |

</details>

<details open>
<summary><b>🧠 记忆与知识（10 个）</b></summary>

| 工具 | 说明 |
|------|------|
| `save_memory` / `search_memory` / `update_memory` / `delete_memory` / `list_memories` | 分类事实 CRUD |
| `search_graph_memory` | 统一搜索（事实 + 图边） |
| `query_connected_entities` / `delete_graph_entity` | 图实体查询与删除 |
| `add_graph_edge` / `remove_graph_edge` | 图关系管理 |

</details>

<details open>
<summary><b>📋 待办 · 📅 闹钟 · 🎵 音乐 · 📖 日记 · 🔗 跨端</b></summary>

| 工具 | 说明 |
|------|------|
| `add_todo` / `list_todos` / `complete_todo` | 待办管理 |
| `add_alarm` / `list_alarms` / `delete_alarm` | 闹钟管理 |
| `control_music` / `get_music_playlist` / `get_music_status` | 音乐盒控制 |
| `read_diary` / `write_diary` | 日记读写 |
| `read_note` / `organize_note` / `notebook_write` / `notebook_read` / `notebook_delete` | 备忘本与草稿本 |
| `search_cross_session` | 跨会话/跨设备搜索 |
| `send_file_to_qq` | QQ 文件发送 |

</details>

<details open>
<summary><b>🤖 代理调度 · 🌤️ 天气 · 🎨 媒体生成</b></summary>

| 工具 | 说明 |
|------|------|
| `plan_tasks` / `delegate_task` / `track_tasks` | 子代理任务规划与委派 |
| `get_weather` / `set_user_city` | 天气查询（和风天气） |
| `generate_image` / `generate_video` | AI 图片/视频生成 |
| `set_expression` | 角色表情切换 |
| `toggle_proactive_chat` | 主动聊天开关 |

</details>

<details open>
<summary><b>🎙️ 语音 · 🌐 浏览器 · 📷 外设 · 📺 B站（技能工具）</b></summary>

| 工具 | 说明 |
|------|------|
| `speak_voice` / `set_voice_mood` / `list_voice_styles` | 语音合成与情绪切换 |
| `browser_navigate` / `browser_snapshot` / `browser_click` / `browser_fill` / `browser_screenshot` | Playwright 浏览器控制 |
| `shoulder_photo` / `shoulder_pan` / `shoulder_tilt` / `shoulder_center` / `shoulder_status` / `shoulder_temp` | 肩载摄像头云台控制 |
| `start_observation_mode` / `stop_observation_mode` / `shoulder_observe` | 观察模式 |
| `shoulder_human_track` / `stop_human_track` | 人体跟踪 |
| `bilibili_search` / `bilibili_add_tag` / `bilibili_list_tags` | B 站视频搜索与兴趣标签 |

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
├── config.py                # 全局配置：API/视觉/TTS/记忆/QQ/微信/代理等30+配置项
├── aliyun_stt.py            # 阿里云NLS实时语音识别
├── requirements.txt         # Python依赖
│
├── brain/                   # 🧠 核心大脑
│   ├── agent.py             #   AgentCore：LiteLLM网关 + Function Calling循环
│   ├── tools.py             #   71个工具定义与执行调度
│   ├── intent_router.py     #   意图路由器：小模型分类 + 规则兜底
│   ├── decision.py          #   规则路由（正则匹配）
│   ├── skill_manager.py     #   技能系统：发现→激活→工具注入
│   ├── tool_registry.py     #   工具注册中心：分类 + 调用统计
│   ├── tool_recovery.py     #   工具恢复链：失败重试 + 降级
│   ├── voice_duplex.py      #   全双工语音：VAD + STT 前端
│   ├── vad_webrtc.py        #   WebRTC VAD 语音活动检测
│   ├── stt_funasr.py        #   FunASR 语音识别（Paraformer）
│   ├── stt_volcano.py       #   火山引擎云端STT备选
│   ├── tts_engine.py        #   语音合成：GPT-SoVITS + Edge-TTS + 情绪匹配
│   ├── tts_sovits_worker.py #   GPT-SoVITS 子进程工作线程
│   ├── graph_memory.py      #   五元组图记忆 + 分类事实 (SQLite)
│   ├── memory_store.py      #   记忆格式化与统一查询
│   ├── memory_rag.py        #   记忆RAG：BGE向量语义搜索
│   ├── context_compressor.py #  长对话智能压缩
│   ├── quintuple_extractor.py # 五元组自动提取（对话→知识图谱）
│   ├── checklist_extractor.py # 对话回顾提取待办
│   ├── code_intel.py        #   代码智能：jedi跳转定义/引用 + pyflakes诊断
│   ├── observation_engine.py #  观察探索引擎System Prompt
│   ├── observation_mode.py  #   观察模式状态管理+费用追踪
│   ├── observation_store.py #   观察记录持久化
│   ├── observation.py       #   观察数据结构
│   ├── human_tracking.py    #   人体跟踪状态管理
│   ├── hardware_bridge.py   #   ESP32 WebSocket 云中继桥接
│   ├── browser_controller.py #  Playwright 浏览器控制
│   ├── heartbeat.py         #   心跳自检引擎
│   ├── notebook.py          #   草稿本/代码执行
│   ├── task_tracker.py      #   任务追踪
│   ├── weather.py           #   和风天气集成
│   ├── vision.py            #   视觉分析统一入口
│   ├── audio_utils.py       #   音频工具
│   ├── auto_task_executor.py #  🤖 ReAct Agent 自动化任务执行器
│   ├── auto_task_manager.py  #  🤖 任务CRUD · 持久化 · 日志
│   ├── auto_task_parser.py   #  🤖 自然语言 → 调度信息解析
│   ├── auto_task_scheduler.py # 🤖 QThread 后台调度
│   ├── emotional/           #   🎭 涟漪情感引擎
│   │   ├── state.py         #       5维需求 · 3层状态
│   │   ├── events.py        #       13种事件检测
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
│   ├── tool_call_card.py    #   工具调用卡片（折叠态+展开态）
│   ├── tool_call_group.py   #   工具调用分组组件
│   ├── animation_state_machine.py # 动画状态机
│   ├── spectrum_widget.py   #   频谱可视化
│   ├── task_progress_bar.py #   任务进度条
│   ├── api_config_dialog.py #   API配置面板
│   ├── settings_dialog.py   #   全局设置
│   ├── capability_center.py #   能力中心总览
│   ├── duty_center.py       #   后台职责中心（主动聊天/摸鱼/心跳/提醒）
│   ├── alarm_dialog.py      #   闹钟 + 倒计时 + 提醒 + 待办 + 自动化任务
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
│   ├── qq_settings_dialog.py  # QQ桥接配置
│   ├── wechat_settings_dialog.py # 微信桥接配置
│   ├── network_settings_dialog.py # 网络/代理配置
│   ├── sound_settings_dialog.py   # 音效设置
│   ├── memory_settings_dialog.py  # 棱镜记忆系统设置
│   ├── emotional_debug_dialog.py  # 涟漪情感系统调试面板
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
│   ├── wechat_bridge_worker.py # 微信桥接HTTP线程
│   ├── proactive_worker.py  #   主动聊天调度线程
│   ├── heartbeat_worker.py  #   心跳检测线程
│   ├── standby_worker.py    #   待机模式线程
│   ├── slack_worker.py      #   摸鱼模式线程
│   ├── observation_mode_worker.py # 观察模式循环
│   ├── track_worker.py      #   人体跟踪统一线程
│   ├── track_frame_receiver.py   # 跟踪帧接收
│   ├── track_pose_detector.py    # Pose推理
│   ├── ocr_worker.py        #   OCR后台线程
│   └── smart_reminder_worker.py  # 智能提醒
│
├── voice/                   # 🎤 语音子系统
│   ├── listener.py          #   录音+VAD+FunASR识别
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
│   ├── auto_task_data.py    #   🤖 AutoTask / ActionStep 数据模型
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
│   ├── slack_utils.py       #   摸鱼模式数据收集
│   ├── bilibili_history.py  #   B站浏览历史与兴趣标签
│   └── autostart.py         #   开机自启管理
│
├── skills/                  # 🔌 技能包（插件式）
│   ├── 语音合成/            #   GPT-SoVITS + 情绪
│   ├── 浏览器自动化/        #   Playwright
│   ├── 肩部外设控制/        #   ESP32 云台
│   ├── 日记与备忘/          #
│   ├── 音乐播放控制/        #
│   ├── B站视频摘要/         #   Bilibili API + 字幕提取
│   ├── 系统信息工具/        #
│   ├── 学习助手/            #
│   └── _prompt_guides/      #   System Prompt 渐进式注入模块（12个）
│
├── mcp_servers/             # 🔗 MCP服务
│   ├── filesystem/          #   本地文件系统操作
│   ├── firecrawl/           #   网页爬虫与内容提取
│   ├── tavily_search/       #   AI 原生搜索引擎
│   └── zhihu_search/        #   知乎搜索
│
├── game/                    # 🎮 实验性功能
│   └── genericrawl-main/    #   Roguelike 游戏引擎（开发中）
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
用户输入 (文字/语音/QQ/微信)
    │
    ├─── 语音输入 → VoiceDuplex (WebRTC VAD → FunASR/火山STT) → 文字
    │                                                    │
    │                                     实时打断(用户说话中)
    │                                                    │
    ▼                                                    ▼
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
│  ├── 记忆注入 (棱镜: 图记忆+分类记忆+RAG向量) │
│  ├── 情感状态 (涟漪: 5维需求+3层状态) │
│  ├── 技能知识 (激活的技能SKILL.md)    │
│  ├── 渐进式技能模块 (12个关键词触发)  │
│  └── MCP服务描述 (4服务)             │
│                                      │
│  Function Calling 循环               │
│  ├── LiteLLM → AI API                │
│  ├── 工具恢复链 (重试+降级)           │
│  ├── 工具并行执行 (ThreadPool)        │
│  ├── 资源锁调度 (浏览器/硬件/DB)       │
│  └── 结果回传                         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│           后处理                      │
│  情感分析 → 状态更新                  │
│  记忆提取 → 五元组+分类事实+RAG向量    │
│  对话压缩 → 上下文摘要(如需)           │
│  待办提取 → checklist_extractor      │
│  TTS合成 → 语音输出(如需)             │
│  QQ/微信发送 → 消息推送(如需)          │
│  历史记录 → SQLite持久化              │
└─────────────────────────────────────┘

═══════════════════════════════════════
  定时自动化支线（独立调度线程）
═══════════════════════════════════════

用户输入 "每天14:00清理回收站"
    │
    ▼
┌──────────────────────┐
│ auto_task_parser     │  LLM 提取调度信息（时间/频率/描述）
│ (LLM + 规则降级)     │
└──────┬───────────────┘
       │ AutoTask { schedule_type, schedule_time, description }
       ▼
┌──────────────────────┐
│ auto_task_manager    │  JSON 持久化 + CRUD + 观察者通知
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ auto_task_scheduler  │  QThread 30s 轮询
│ (后台线程)            │  到期检测 → task_due signal
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ auto_task_executor   │  ReAct Agent 循环
│ (daemon 线程)         │  LLM 运行时自主决定工具调用
│                      │  搜索结果 → 写文档 → 通知
└──────┬───────────────┘
       │
       ▼
  完成通知（聊天框 + 语音）
```

---

<div align="center">
<img src="assets/主界面背景图/主界面背景图.jpg" alt="主界面" width="100%" />

*为何人类会因为孤独，从而拥抱一面镜子呢？*

<br>

Made with ❤️ by [luke23334](https://gitee.com/luke23334)

[![Gitee](https://img.shields.io/badge/Gitee-仓库地址-C71D23?logo=gitee)](https://gitee.com/luke23334/lianxin-ai)

</div>