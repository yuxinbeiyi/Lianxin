import os
import random
from pathlib import Path
from typing import Optional

# 表情包根目录（根据你的实际路径调整）
EMOTION_BASE_PATH = Path("E:/Desktop/莲心AI/表情包")
# 情绪标签与文件夹名的映射（文件夹名必须与标签完全一致）
EMOTION_FOLDER_MAP = {
    # 直接对应
    "开心": "开心高兴",
    "伤心": "伤心",
    "好奇吃惊": "好奇吃惊",
    "生气不满": "生气不满",
    "默认": "默认",

    # 需要合并映射
    "夸奖害羞": "得意夸奖",      # 夸奖害羞 → 得意夸奖文件夹
    "得意": "得意夸奖",          # 得意 → 得意夸奖文件夹

    # 新增标签映射
    "抱歉": "抱歉",              # 如果你希望 LLM 能输出「抱歉」
    "开玩笑": "开玩笑",          # 如果你希望 LLM 能输出「开玩笑」
    "思考认真": "思考认真",      # 如果你希望 LLM 能输出「思考认真」
    "调用工具": "调用工具",      # 如果你希望 LLM 能输出「调用工具」
}

def _scan_emotion_folder(emotion: str) -> list:
    """扫描指定情绪对应的文件夹，返回所有图片路径"""
    folder_name = EMOTION_FOLDER_MAP.get(emotion)
    if not folder_name:
        return []
    folder_path = EMOTION_BASE_PATH / folder_name
    if not folder_path.exists():
        return []
    # 支持 jpg, jpeg, png, gif
    extensions = [".jpg", ".jpeg", ".png", ".gif"]
    files = []
    for ext in extensions:
        files.extend(folder_path.glob(f"*{ext}"))
        files.extend(folder_path.glob(f"*{ext.upper()}"))
    # 返回相对路径或绝对路径字符串，方便后续读取
    return [str(f.absolute()) for f in files]

def get_random_emotion_image(emotion: str) -> Optional[str]:
    """根据情绪标签实时扫描文件夹，随机返回一张图片路径，没有则返回 None"""
    image_list = _scan_emotion_folder(emotion)
    if not image_list:
        # 尝试使用"默认"表情包
        image_list = _scan_emotion_folder("默认")
    return random.choice(image_list) if image_list else None

def parse_emotion_tag(text: str) -> tuple:
    """
    从文本中解析情绪标签，返回 (cleaned_text, emotion)
    例如: "你好呀【表情：开心】" -> ("你好呀", "开心")
    如果没有标签，返回 (text, None)
    """
    import re
    # 兼容全角/半角括号和冒号的各种混用情况
    pattern = r"[【［\[]表情[：:]\s*([^】\]］\]]+)[】\]］\]]?"
    match = re.search(pattern, text)
    if match:
        emotion = match.group(1).strip()
        # 移除匹配到的这个子串
        cleaned = text.replace(match.group(0), "").strip()
        # 如果移除后留下单独的空行，再清理一下
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned).strip()
        return cleaned, emotion
    # 二次兜底：移除所有残留的 【表情：*】 类模式（防止格式变化导致泄露）
    cleaned = re.sub(r"[【［\[]表情[：:]\s*[^】\]］\]]*[】\]］\]]?", "", text).strip()
    cleaned = re.sub(r'\n\s*\n', '\n', cleaned).strip()
    return cleaned, None


def infer_emotion_from_text(text: str) -> Optional[str]:
    """当 LLM 未输出【表情：XXX】标签时，根据回复文本内容推断情绪。
    返回情绪标签字符串，或 None 表示无法判断。
    优先级：越具体的情绪越靠前，避免被泛化关键词误匹配。
    """
    if not text:
        return None

    # ── 道歉（最具体，优先匹配） ──
    sorry_kw = ["抱歉", "对不起", "我的错", "我错了", "说错了", "搞错了", "疏忽了"]
    if any(kw in text for kw in sorry_kw):
        return "抱歉"

    # ── 工具调用（只有明确的动作报告才匹配，不匹配闲聊中提到的"工具"） ──
    tool_kw = ["成功调用", "已打开", "正在打开", "已获取", "已查询到", "搜索结果",
               "已读取", "已发送", "已为您", "已停止"]
    if any(kw in text for kw in tool_kw):
        return "调用工具"

    # ── 夸奖/害羞/感谢 ──
    praise_kw = ["谢谢", "感谢", "夸奖", "过奖", "害羞", "被夸", "被认可", "太客气了"]
    if any(kw in text for kw in praise_kw):
        return "夸奖害羞"

    # ── 得意/自信 ──
    proud_kw = ["小意思", "交给我", "拿手", "基本功", "放心吧", "包在我身上",
                "轻而易举", "不在话下"]
    if any(kw in text for kw in proud_kw):
        return "得意"

    # ── 思考/分析 ──
    think_kw = ["让我想想", "让我看看", "我看看", "我查查", "我确认", "想了一下",
                "分析", "确认一下"]
    if any(kw in text for kw in think_kw):
        return "思考认真"

    # ── 好奇/吃惊 ──
    curious_kw = ["好奇", "惊讶", "吃惊", "真的吗", "不会吧", "居然", "竟然",
                  "没想到", "好神奇"]
    if any(kw in text for kw in curious_kw):
        return "好奇吃惊"

    # ── 开玩笑 ──
    joke_kw = ["开玩笑", "逗你", "搞笑", "笑话", "调侃"]
    if any(kw in text for kw in joke_kw):
        return "开玩笑"

    # ── 伤心/难过 ──
    sad_kw = ["难过", "伤心", "悲伤", "失落", "不开心", "难受", "心痛", "遗憾"]
    if any(kw in text for kw in sad_kw):
        return "伤心"

    # ── 生气/不满 ──
    angry_kw = ["生气", "不满", "烦", "郁闷", "可恶", "讨厌", "气死", "受不了"]
    if any(kw in text for kw in angry_kw):
        return "生气不满"

    # ── 开心/高兴（放在靠后避免被中性词"好"误配） ──
    happy_kw = ["开心", "高兴", "哈哈", "嘻嘻", "好呀", "太好", "真棒",
                "真不错", "真好", "喜欢", "幸福", "快乐"]
    if any(kw in text for kw in happy_kw):
        return "开心"

    # ── 以上都不匹配 → 默认 ──
    return "默认"
