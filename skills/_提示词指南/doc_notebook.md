---
triggers: ["报告", "排版", "文档", "Word", "草稿", "笔记", "notebook", "format_document", "pdf", "导出", "markdown", "md", "整理", "写", "创建", "保存", "生成文档", "生成报告", "格式化", "word", "doc", "docx", "草稿本", "临时", "暂存", "备忘录", "提案", "方案", "PRD", "规格", "技术文档", "会议纪要", "大纲", "写文章", "起草"]
---

## 文档写作工作流

当用户要求写文档时，按结构化流程引导：

### 1. 需求确认
- 问清文档类型、受众、用途、格式要求
- 确定文档结构（分几个章节）

### 2. 内容起草
- 逐章起草，每章先列出要点让用户确认
- 长文档中途用 notebook_write 暂存阶段性内容

### 3. 排版输出
- 用户确认内容后，调 **format_document** 生成排版精美的 .docx
- 禁止直接输出未排版的纯文本作为最终结果
- 先整理为 Markdown → 再调 format_document(markdown内容, 输出路径)

### 4. 最终检查
- 生成后请用户检查，确认无误则完成

## 可用工具

### 文档生成
- **format_document(content, output_path)** — 将 Markdown 转为格式优美的 Word 文档（推荐）
- **write_docx(file_path, content)** — 直接写入 .docx 文件

### 草稿本（不受对话压缩影响）
- **notebook_write(key="名称", value="内容")** — 写入临时笔记
- **notebook_write(key="名称", value="内容", persist=True)** — 持久笔记（跨会话保留）
- **notebook_read(key="名称")** — 读取；notebook_read() — 列出所有
- **notebook_delete(key="名称")** — 删除
- key 只支持英文/数字/下划线/连字符
- 适用场景：跨文件汇总、长内容分批、阶段性结论、写作中途暂存