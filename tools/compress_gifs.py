"""
GIF 压缩工具：将莲心动画 GIF 大幅压缩，消除 UI 卡顿。

用法：
    python tools/compress_gifs.py

依赖：pip install pillow

说明：
检测 assets/GIF/ 下所有 .gif 文件，将分辨率缩小一半、颜色数降至 128，
文件体积通常会缩小 80-95%（如 20MB → 1-2MB）。
原始文件备份为 .gif.bak，可放心测试。
"""

import os
import shutil
from pathlib import Path

GIF_DIR = Path(__file__).parent.parent / "assets" / "GIF"

# 大于此阈值的 GIF 才会被压缩（1MB = 1024KB = 1048576 字节）
SIZE_THRESHOLD = 512 * 1024

try:
    from PIL import Image
except ImportError:
    print("请先安装 Pillow: pip install pillow")
    exit(1)


def compress_gif(path: Path, scale: float = 0.75, max_colors: int = 200):
    """压缩 GIF：缩小分辨率 + 减少颜色数，保持动画帧。"""
    print(f"  压缩中: {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB)", end="")

    # 备份原文件
    bak = path.with_suffix(".gif.bak")
    if not bak.exists():
        shutil.copy2(path, bak)

    with Image.open(path) as img:
        frames = []
        durations = []
        try:
            while True:
                frames.append(img.copy())
                durations.append(img.info.get("duration", 50))
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        if not frames:
            print(" 跳过（无帧）")
            return

        # 缩小分辨率
        new_size = (int(frames[0].width * scale), int(frames[0].height * scale))
        compressed = []
        for f in frames:
            resized = f.resize(new_size, Image.LANCZOS)
            # 转调色板模式减少颜色
            if resized.mode == "RGBA":
                resized = resized.quantize(colors=max_colors, method=2)
            elif resized.mode == "RGB":
                resized = resized.quantize(colors=max_colors, method=Image.MEDIANCUT)
            compressed.append(resized)

        # 保存
        compressed[0].save(
            path,
            save_all=True,
            append_images=compressed[1:],
            duration=durations,
            loop=0,
            optimize=True,
        )

    saved_pct = (1 - path.stat().st_size / bak.stat().st_size) * 100
    print(f" → {path.stat().st_size / 1024 / 1024:.1f} MB  (压缩 {saved_pct:.0f}%)")


def main():
    if not GIF_DIR.exists():
        print(f"未找到 GIF 目录: {GIF_DIR}")
        return

    gif_files = sorted(GIF_DIR.rglob("*.gif"))
    targets = [f for f in gif_files if f.stat().st_size > SIZE_THRESHOLD]

    if not targets:
        print(f"未找到超过 {SIZE_THRESHOLD / 1024:.0f} KB 的大 GIF，无需压缩。")
        return

    print(f"发现 {len(targets)} 个大 GIF 文件，开始压缩...\n")
    for f in targets:
        compress_gif(f)

    print(f"\n完成！原始文件已备份为 .gif.bak")
    print("如果效果不满意，重命名 .gif.bak → .gif 即可恢复。")


if __name__ == "__main__":
    main()
