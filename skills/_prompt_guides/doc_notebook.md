---
triggers: ["报告", "排版", "文档", "Word", "草稿", "笔记", "notebook", "format_document", "pdf", "导出", "markdown", "md", "整理", "写", "创建", "保存", "生成文档", "生成报告", "格式化", "word", "doc", "docx", "草稿本", "临时", "暂存", "备忘录"]
---

## 文档排版与草稿本指南

## 文档排版
- 生成报告/整理文档→先整理为 Markdown→调 format_document 生成 Word。
- 禁止直接输出未排版的纯文本作为最终结果。

## 草稿本
notebook_write/read/delete 做临时笔记，内容不受对话压缩影响。
- notebook_write(key="名称", value="内容") — 写入
- notebook_write(key="名称", value="内容", persist=True) — 持久笔记（跨会话保留）
- notebook_read(key="名称") — 读取；notebook_read() — 列出所有
- notebook_delete(key="名称") — 删除
key 只支持英文/数字/下划线/连字符。适用：跨文件汇总、长内容分批、阶段性结论。
