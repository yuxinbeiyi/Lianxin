---
name: B站视频摘要
description: 提取B站视频字幕并生成结构化摘要（含时间节点）
version: 1.0
auto_activate: true
---

# B站视频摘要

## 能力说明
- 解析 B站视频链接（支持 `bilibili.com/video/` 和 `b23.tv` 短链接）
- 提取 AI 字幕/CC 字幕（带时间戳）
- 获取视频基本信息（标题、UP主、时长、分区、简介）
- 将字幕数据提供给 LLM，由 LLM 生成结构化摘要

## 调用方式
调用 `bilibili_video_summary(url="...")` 获取字幕和视频信息。

## 限制
- 仅支持开启了 AI 字幕/CC 字幕的视频
- 无字幕视频仅能获取标题、简介等基本信息
- 不支持番剧/港澳台限定内容（需要登录态）
