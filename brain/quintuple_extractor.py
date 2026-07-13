"""
五元组知识图谱提取器 — 从对话中提取 (主体, 主体类型, 关系, 客体, 客体类型)。

在 _trigger_auto_extraction 的 daemon 线程中调用，与分类记忆提取并行。
使用 litellm 调用远端 LLM（DeepSeek），失败静默跳过。
"""

import json
import logging
from typing import Optional

import litellm

from config import get_api_config, get_graph_config
from brain.graph_memory import store_quintuple, ENTITY_TYPES

litellm.set_verbose = False
litellm.suppress_debug_info = True

logger = logging.getLogger("QuintupleExtractor")

_EXTRACT_SYSTEM = """你是莲心AI的知识图谱提取助手。从对话文本中提取有价值的五元组关系。
五元组格式: (主体, 主体类型, 关系/动作, 客体, 客体类型)。

## 核心原则：宁缺毋滥
只提取**有长期记忆价值**的信息——这些信息在未来对话中可能被莲心引用。

## 值得提取的信息（满足任一条件即可）
1. **用户身份/背景**：姓名、职业、居住地、家庭成员、宠物等长期稳定信息
2. **用户偏好**：喜欢/讨厌的食物、音乐、电影、品牌、工具等
3. **重要事件**：旅行、换工作、搬家、重要日期（生日、纪念日）
4. **项目/工作**：正在做的项目、使用的技术栈、关键文件路径
5. **人际关系**：用户与他人的关系（朋友、同事、家人）
6. **知识/技能**：用户掌握的技能、学会的新东西
7. **计划/目标**：用户明确的未来计划

## 坚决不提取的信息
- 纯粹的情感表达（"我今天很开心"）
- 闲聊寒暄（"你好""晚安"）
- 比喻、拟人、夸张等修辞
- 虚拟、假设、想象的内容
- 赞美、讽刺、调侃等主观评价
- 对当前对话的即时反应（"你回答得很好"）
- 一次性任务指令（"帮我搜一下天气"）

## 主体/客体类型
人物、地点、组织、物品、概念、时间、事件、活动、技术、文件

## 提取格式
每条五元组自我完整，脱离上下文也能理解。无有价值信息时返回空数组。

## 示例
输入: 我最近在学Python，用PyCharm写代码。
输出: {"quintuples": [["用户","人物","学习","Python","技术"], ["用户","人物","使用","PyCharm","技术"]]}

输入: 周末去了一趟杭州西湖，感觉风景很美。
输出: {"quintuples": [["用户","人物","去了","西湖","地点"], ["用户","人物","去了","杭州","地点"]]}

输入: 今天天气真好，心情不错。
输出: {"quintuples": []}

输入: 帮我搜一下最近的新闻。
输出: {"quintuples": []}

只输出JSON，不要输出其他内容。"""


def extract_quintuples(conversation_text: str) -> list[tuple]:
    """从对话文本中提取五元组列表。失败返回空列表。"""
    cfg = get_graph_config()
    if not cfg.get("graph_enabled", True):
        return []

    if not conversation_text or len(conversation_text) < 30:
        return []

    from config import normalize_model_for_litellm
    api_cfg = get_api_config()
    model = normalize_model_for_litellm(
        api_cfg.get("model", "deepseek-v4-flash"),
        api_cfg.get("base_url", ""),
    )

    try:
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": f"请从以下对话中提取五元组：\n\n{conversation_text[:4000]}"},
            ],
            api_key=api_cfg["api_key"],
            api_base=api_cfg["base_url"],
            temperature=0.1,
            max_tokens=500,
            timeout=30,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        quintuples = data.get("quintuples", [])
        if not isinstance(quintuples, list):
            return []

        result = []
        for q in quintuples:
            if isinstance(q, list) and len(q) == 5:
                result.append(tuple(q))
        return result

    except Exception as e:
        logger.warning(f"五元组提取失败: {e}")
        return []


def extract_and_store(conversation_text: str) -> int:
    """提取五元组并写入图数据库。返回写入条数。"""
    quintuples = extract_quintuples(conversation_text)
    count = 0
    for head, head_type, relation, tail, tail_type in quintuples:
        if store_quintuple(head, head_type, relation, tail, tail_type, source="auto"):
            count += 1
    if count > 0:
        logger.info(f"图记忆: 存储 {count} 条五元组")
    return count

def extract_and_store_with_config(conversation_text: str, model: str,
                                   api_key: str, api_base: str) -> int:
    """用指定 API 配置提取五元组并写入图数据库。返回写入条数。"""
    cfg = get_graph_config()
    if not cfg.get("graph_enabled", True):
        return 0

    if not conversation_text or len(conversation_text) < 30:
        return 0

    try:
        import litellm
        response = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": f"请从以下对话中提取五元组：\n\n{conversation_text[:4000]}"},
            ],
            api_key=api_key,
            api_base=api_base,
            temperature=0.1,
            max_tokens=1000,
            timeout=30,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        quintuples = data.get("quintuples", [])
        if not isinstance(quintuples, list):
            return 0

        count = 0
        for q in quintuples:
            if isinstance(q, list) and len(q) == 5:
                head, head_type, relation, tail, tail_type = q
                if store_quintuple(head, head_type, relation, tail, tail_type, source="auto"):
                    count += 1
        if count > 0:
            logger.info(f"图记忆: 存储 {count} 条五元组")
        return count

    except Exception as e:
        logger.warning(f"五元组提取失败: {e}")
        return 0


def build_quintuple_extraction_prompt(conversation_text: str) -> str:
    """构建五元组提取的完整 prompt（供 agent.py 直接调用 LLM 时使用）。"""
    return f"""从以下中文对话中抽取有价值的五元组关系，以 JSON 数组格式返回。

提取规则：
- 只提取事实性信息：具体行为、实体关系、状态属性、用户需求偏好
- 过滤：比喻、假设、纯情感、赞美讽刺等主观内容
- 类型限定：人物/地点/组织/物品/概念/时间/事件/活动/技术/文件

示例：
输入：小明在公园踢足球。
输出：{{"quintuples": [["小明","人物","踢","足球","物品"], ["小明","人物","在","公园","地点"]]}}

对话内容：
{conversation_text[:4000]}

只输出JSON："""