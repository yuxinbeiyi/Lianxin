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

## 提取规则
1. 只提取**事实性**信息：
   - 具体的行为和动作
   - 明确的实体关系
   - 实际存在的状态和属性
   - 用户表达的具体需求、偏好、计划

2. 严格过滤：
   - 比喻、拟人、夸张等修辞
   - 虚拟、假设、想象的内容
   - 纯粹的情感表达（"我很开心"）
   - 赞美、讽刺、调侃等主观评价
   - 闲聊中的无关信息

3. 主体/客体类型必须是以下之一：
   人物、地点、组织、物品、概念、时间、事件、活动、技术、文件

4. 每条五元组应自我完整，脱离上下文也能理解。
   宁少勿多，只提取真正有价值的关系。

## 示例
输入: 小明在公园里踢足球。
输出: {"quintuples": [["小明","人物","踢","足球","物品"], ["小明","人物","在","公园","地点"]]}

输入: 你像小太阳一样温暖。
输出: {"quintuples": []}

输入: 我喜欢吃苹果和香蕉。
输出: {"quintuples": [["用户","人物","喜欢吃","苹果","物品"], ["用户","人物","喜欢吃","香蕉","物品"]]}

只输出JSON，不要输出其他内容。"""


def extract_quintuples(conversation_text: str) -> list[tuple]:
    """从对话文本中提取五元组列表。失败返回空列表。"""
    cfg = get_graph_config()
    if not cfg.get("graph_enabled", True):
        return []

    if not conversation_text or len(conversation_text) < 30:
        return []

    api_cfg = get_api_config()
    model = api_cfg.get("model", "deepseek-v4-flash")
    if "/" not in model:
        model = f"deepseek/{model}"

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
