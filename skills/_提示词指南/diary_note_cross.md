---
triggers: ["日记", "备忘", "之前聊过", "跨端", "QQ", "电脑上说过", "记录", "搜索", "查找", "历史", "以前", "上次", "原来", "过去", "那天", "前几天", "昨天", "今天聊", "另一端", "手机", "桌面端", "记一下", "帮我记", "往回看", "翻", "翻阅"]
---

## 日记·备忘本·跨端搜索指南

## 日记
- 读日记：read_diary(date="2026-04-17") 或 read_diary(keyword="开心", limit=2) 或 read_diary(limit=3)
- 写日记：write_diary。禁止未调工具就展示或编造日记内容。

## 备忘本
- 读：read_note — 获取后理解内容并自然聊天，不朗读原文。
- 整理：organize_note — AI 智能整理。禁止未调工具就假装看过。

## 跨端搜索
- 问最近/昨天/之前聊过什么 → search_conversation_history(mode="recent", time_range="对应时间范围")
- 明确问另一端聊过什么 → search_conversation_history，并用 channels 限定 desktop 或 qq_private。
- `search_cross_session` 仅作为旧兼容入口。禁止凭空回答。
