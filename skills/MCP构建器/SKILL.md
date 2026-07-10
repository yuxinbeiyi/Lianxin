---
name: MCP 构建器
description: 创建高质量 MCP（模型上下文协议）服务器的指南，使 LLM 能够通过精心设计的工具与外部服务交互。在构建 MCP 服务器以集成外部 API 或服务时使用，无论是 Python（FastMCP）还是 Node/TypeScript（MCP SDK）。
license: Complete terms in LICENSE.txt
---

# MCP 服务器开发指南

## 概述

创建 MCP（模型上下文协议）服务器，使 LLM 能够通过精心设计的工具与外部服务交互。MCP 服务器的质量由其帮助 LLM 完成现实世界任务的能力来衡量。

---

# 流程

## 🚀 高层工作流

创建高质量 MCP 服务器涉及四个主要阶段：

### 第一阶段：深度研究与规划

#### 1.1 理解现代 MCP 设计

**API 覆盖 vs. 工作流工具：**
在全面的 API 端点覆盖和专用工作流工具之间取得平衡。工作流工具对特定任务更方便，而全面覆盖让代理有灵活性来组合操作。性能因客户端而异——有些客户端受益于组合基本工具的代码执行，而其他客户端更适合高级工作流。不确定时，优先考虑全面的 API 覆盖。

**工具命名和可发现性：**
清晰、描述性的工具名称帮助代理快速找到正确的工具。使用一致的前缀（例如 `github_create_issue`、`github_list_repos`）和面向操作的命名。

**上下文管理：**
代理受益于简洁的工具描述和过滤/分页结果的能力。设计返回聚焦、相关数据的工具。有些客户端支持代码执行，可以帮助代理高效过滤和处理数据。

**可操作的错误消息：**
错误消息应引导代理找到解决方案，提供具体建议和后续步骤。

#### 1.2 学习 MCP 协议文档

**浏览 MCP 规范：**

从站点地图开始查找相关页面：`https://modelcontextprotocol.io/sitemap.xml`

然后获取带有 `.md` 后缀的特定页面以获取 markdown 格式（例如 `https://modelcontextprotocol.io/specification/draft.md`）。

需要查阅的关键页面：
- 规范概述和架构
- 传输机制（可流式传输的 HTTP、stdio）
- 工具、资源和提示词定义

#### 1.3 学习框架文档

**推荐技术栈：**
- **语言**：TypeScript（高质量的 SDK 支持和在许多执行环境中良好的兼容性。此外 AI 模型擅长生成 TypeScript 代码，受益于其广泛使用、静态类型和良好的 linting 工具）
- **传输**：远程服务器使用可流式传输的 HTTP，采用无状态 JSON（比有状态会话和流式响应更易于扩展和维护）。本地服务器使用 stdio。

**加载框架文档：**

- **MCP 最佳实践**：[📋 查看最佳实践](./reference/mcp_best_practices.md) - 核心指南

**TypeScript（推荐）：**
- **TypeScript SDK**：使用 WebFetch 加载 `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md`
- [⚡ TypeScript 指南](./reference/node_mcp_server.md) - TypeScript 模式和示例

**Python：**
- **Python SDK**：使用 WebFetch 加载 `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`
- [🐍 Python 指南](./reference/python_mcp_server.md) - Python 模式和示例

#### 1.4 规划实现

**理解 API：**
查阅服务的 API 文档以识别关键端点、认证要求和数据模型。根据需要通过网络搜索和 WebFetch 获取。

**工具选择：**
优先考虑全面的 API 覆盖。列出要实现的端点，从最常见的操作开始。

---

### 第二阶段：实现

#### 2.1 搭建项目结构

参见语言特定指南了解项目搭建：
- [⚡ TypeScript 指南](./reference/node_mcp_server.md) - 项目结构、package.json、tsconfig.json
- [🐍 Python 指南](./reference/python_mcp_server.md) - 模块组织、依赖

#### 2.2 实现核心基础设施

创建共享工具：
- 带认证的 API 客户端
- 错误处理辅助函数
- 响应格式化（JSON/Markdown）
- 分页支持

#### 2.3 实现工具

对每个工具：

**输入模式：**
- 使用 Zod（TypeScript）或 Pydantic（Python）
- 包含约束和清晰的描述
- 在字段描述中添加示例

**输出模式：**
- 尽可能为结构化数据定义 `outputSchema`
- 在工具响应中使用 `structuredContent`（TypeScript SDK 特性）
- 帮助客户端理解和处理工具输出

**工具描述：**
- 功能的简洁摘要
- 参数描述
- 返回类型模式

**实现：**
- I/O 操作使用 async/await
- 适当的错误处理，包含可操作的消息
- 适用时支持分页
- 使用现代 SDK 时同时返回文本内容和结构化数据

**注解：**
- `readOnlyHint`：true/false
- `destructiveHint`：true/false
- `idempotentHint`：true/false
- `openWorldHint`：true/false

---

### 第三阶段：审查与测试

#### 3.1 代码质量

审查：
- 无重复代码（DRY 原则）
- 一致的错误处理
- 完整类型覆盖
- 清晰的工具描述

#### 3.2 构建与测试

**TypeScript：**
- 运行 `npm run build` 验证编译
- 使用 MCP Inspector 测试：`npx @modelcontextprotocol/inspector`

**Python：**
- 验证语法：`python -m py_compile your_server.py`
- 使用 MCP Inspector 测试

参见语言特定指南了解详细的测试方法和质量检查清单。

---

### 第四阶段：创建评估

实现 MCP 服务器后，创建全面的评估来测试其有效性。

**加载 [✅ 评估指南](./reference/evaluation.md) 获取完整评估指南。**

#### 4.1 理解评估目的

使用评估来测试 LLM 是否能有效使用你的 MCP 服务器来回答现实、复杂的问题。

#### 4.2 创建 10 个评估问题

要创建有效的评估，遵循评估指南中概述的过程：

1. **工具检查**：列出可用工具并理解其能力
2. **内容探索**：使用只读操作探索可用数据
3. **问题生成**：创建 10 个复杂、现实的问题
4. **答案验证**：自己解答每个问题以验证答案

#### 4.3 评估要求

确保每个问题是：
- **独立的**：不依赖其他问题
- **只读的**：只需要非破坏性操作
- **复杂的**：需要多次工具调用和深度探索
- **现实的**：基于人类会关心的真实用例
- **可验证的**：单一、清晰的答案，可通过字符串比较验证
- **稳定的**：答案不会随时间变化

#### 4.4 输出格式

创建具有此结构的 XML 文件：

```xml
<evaluation>
  <qa_pair>
    <question>查找关于以动物代号命名的 AI 模型发布的讨论。有一个模型需要特定安全等级，使用 ASL-X 格式。以斑点野生猫命名的模型正在确定什么数字 X？</question>
    <answer>3</answer>
  </qa_pair>
<!-- 更多 qa_pairs... -->
</evaluation>
```

---

# 参考文件

## 📚 文档库

在开发过程中根据需要加载这些资源：

### 核心 MCP 文档（首先加载）
- **MCP 协议**：从站点地图 `https://modelcontextprotocol.io/sitemap.xml` 开始，然后获取带 `.md` 后缀的特定页面
- [📋 MCP 最佳实践](./reference/mcp_best_practices.md) - 通用 MCP 指南，包括：
  - 服务器和工具命名约定
  - 响应格式指南（JSON vs Markdown）
  - 分页最佳实践
  - 传输选择（可流式 HTTP vs stdio）
  - 安全和错误处理标准

### SDK 文档（在第一/二阶段加载）
- **Python SDK**：从 `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md` 获取
- **TypeScript SDK**：从 `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md` 获取

### 语言特定实现指南（在第二阶段加载）
- [🐍 Python 实现指南](./reference/python_mcp_server.md) - 完整的 Python/FastMCP 指南：
  - 服务器初始化模式
  - Pydantic 模型示例
  - 使用 `@mcp.tool` 注册工具
  - 完整的工作示例
  - 质量检查清单

- [⚡ TypeScript 实现指南](./reference/node_mcp_server.md) - 完整的 TypeScript 指南：
  - 项目结构
  - Zod 模式模式
  - 使用 `server.registerTool` 注册工具
  - 完整的工作示例
  - 质量检查清单

### 评估指南（在第四阶段加载）
- [✅ 评估指南](./reference/evaluation.md) - 完整的评估创建指南：
  - 问题创建指南
  - 答案验证策略
  - XML 格式规范
  - 示例问题和答案
  - 使用提供的脚本运行评估