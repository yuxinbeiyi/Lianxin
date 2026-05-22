# -*- coding: utf-8 -*-
"""
BalanceChecker：DeepSeek API 余额查询模块
"""
import requests

DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"


def get_balance_info(api_key: str):
    """
    查询 DeepSeek 账户 CNY 余额。
    api_key: DeepSeek API Key
    成功时返回 (balance_info, None)
    失败时返回 (None, error_message)
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(DEEPSEEK_BALANCE_URL, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            balance_infos = data.get("balance_infos", [])
            if not balance_infos:
                return None, "API 返回的数据格式异常"

            # 优先找 CNY，找不到再用第一个
            cny_entry = None
            for entry in balance_infos:
                if entry.get("currency", "").upper() == "CNY":
                    cny_entry = entry
                    break
            if cny_entry is None:
                cny_entry = balance_infos[0]

            total_balance = float(cny_entry.get("total_balance", 0.0))
            currency = cny_entry.get("currency", "CNY")
            balance_info = {
                "is_available": data.get("is_available", False),
                "total_balance": total_balance,
                "currency": currency,
            }
            return balance_info, None
        elif response.status_code == 401:
            return None, "认证失败，请检查 API Key 是否正确"
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
    """根据余额信息，格式化用于弹窗显示的文本。"""
    if balance_info is None:
        return "抱歉，暂时无法获取余额信息。"
    total = balance_info["total_balance"]
    currency = balance_info["currency"]
    if total < 1.0:
        return f"⚠️ 余额预警：当前余额为 {total:.2f} {currency}，已不足 1 元，请尽快充值以免影响使用！"
    else:
        return f"✅ 当前账户余额为：{total:.2f} {currency}"
