# -*- coding: utf-8 -*-
"""
BalanceChecker：DeepSeek API 余额查询模块
"""
import requests
from config import DEEPSEEK_API_KEY

# DeepSeek 官方余额查询接口
DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"

# 请求头，需要带上你的 API Key
HEADERS = {
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    "Content-Type": "application/json",
}


def get_balance_info():
    """
    查询 DeepSeek 账户余额信息。
    成功时返回 (balance_info, None)
    失败时返回 (None, error_message)
    """
    try:
        response = requests.get(DEEPSEEK_BALANCE_URL, headers=HEADERS, timeout=10)
        # 检查 HTTP 状态码
        if response.status_code == 200:
            data = response.json()
            # 接口返回的数据结构示例：
            # {
            #   "is_available": true,
            #   "balance_infos": [
            #       {"currency": "CNY", "total_balance": "110.00", ...}
            #   ]
            # }
            if data.get("balance_infos") and len(data["balance_infos"]) > 0:
                # 提取第一个账户的余额信息
                balance_data = data["balance_infos"][0]
                total_balance = float(balance_data.get("total_balance", 0.0))
                currency = balance_data.get("currency", "CNY")
                is_available = data.get("is_available", False)

                balance_info = {
                    "is_available": is_available,
                    "total_balance": total_balance,
                    "currency": currency,
                }
                return balance_info, None
            else:
                return None, "API 返回的数据格式异常"
        elif response.status_code == 401:
            return None, "认证失败，请检查 config.py 中的 API Key 是否正确"
        elif response.status_code == 402:
            return None, "账户余额不足，请尽快充值！"
        else:
            return None, f"请求失败，状态码: {response.status_code}"
    except requests.exceptions.Timeout:
        return None, "请求超时，请检查网络连接"
    except requests.exceptions.ConnectionError:
        return None, "网络连接错误，无法访问 DeepSeek API"
    except Exception as e:
        return None, f"查询余额时发生未知错误: {e}"


def format_balance_message(balance_info):
    """
    根据余额信息，格式化用于弹窗显示的文本。
    """
    if balance_info is None:
        return "抱歉，暂时无法获取余额信息。"

    total = balance_info["total_balance"]
    currency = balance_info["currency"]

    # 判断余额是否充足，这里设个阈值，低于 1 元就预警
    if total < 1.0:
        return f"⚠️ 余额预警：当前余额为 {total:.2f} {currency}，已不足 1 元，请尽快充值以免影响使用！"
    else:
        return f"✅ 当前账户余额为：{total:.2f} {currency}"