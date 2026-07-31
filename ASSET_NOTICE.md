# 素材与模型发布清单

本仓库包含界面图片、动画、音乐和视觉模型等二进制资源。公开发布前，维护者应逐项记录来源、作者、许可证、修改方式与再分发许可。维护者于 2026-07-31 确认：`assets/` 内的项目视觉素材为 AI 生成资源，可随仓库发布；这一确认不覆盖具有外部来源标识的音频文件和第三方模型权重。

来源或许可证不明确的资源不应随公开仓库发布。表情包目录默认不提交任何图片，用户可在本地 `表情包/` 下放入自己喜欢的图片；程序在目录为空时会自动跳过表情包发送。其他此类资源可由用户在本地自行放入指定目录，或通过独立下载脚本取得；下载脚本应明确资源来源与许可。

## 发布状态

| 范围 | 当前结论 | 发布处理 | 发布前仍需确认 |
|---|---|---|---|
| `assets/主界面背景图/`、`assets/自习室/` | 维护者确认的 AI 生成壁纸与场景图 | 随仓库发布 | 保留生成记录或来源说明 |
| `assets/GIF/`、`assets/头像/` | 维护者确认的 AI 生成角色动画与头像 | 随仓库发布 | 保留生成记录或来源说明 |
| `assets/icons/`、主题与网页前端文件 | 项目界面资源与代码 | 随仓库发布 | 第三方图标若有，补充许可证 |
| `assets/music/` | 维护者确认的 AI 生成音乐 | 随仓库发布 | 保留生成记录或来源说明 |
| `assets/sound/` | Pixabay 音效素材，来源：[Pixabay Sound Effects](https://pixabay.com/zh/sound-effects/) | 随仓库发布；使用与再分发遵循 Pixabay 当期许可 | 为每个新文件保留原始下载页或资源 ID |
| `models/` | 本地模型权重 | 不随仓库发布 | 通过下载说明列出模型许可证与下载地址 |
| `vision/models/` | MediaPipe 第三方视觉运行时模型 | 不随仓库发布；按 `vision/models/README.md` 下载到本地 | 使用前核验上游模型许可证与版本 |
| `表情包/` | 用户个性化素材 | 仅保留 `.gitkeep`，图片不提交 | 无 |

## Vision Models

`vision/models/` is not distributed in the public repository. Its optional
MediaPipe model files must be downloaded locally following
`vision/models/README.md`. Each user is responsible for reviewing the upstream
license and model-specific terms before use or redistribution.

## 登记模板

新增二进制素材前，请将下列字段加入本文件：

```text
路径：
资源名称：
来源 / 作者：
许可证：
是否修改：
是否允许再分发：
核验日期：
```

在清单完成前，不应宣称仓库内全部媒体和模型可以自由再分发。
