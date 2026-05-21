"""
系统信息工具技能 — 自定义工具
提供 get_system_info 工具，查询 Windows 系统运行状态。
"""

import subprocess
import json


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": (
                "查询当前 Windows 系统的运行状态信息。"
                "支持查询 CPU 使用率、内存占用、磁盘空间、网络状态等。"
                "当用户问'电脑卡不卡'、'还剩多少内存'、'磁盘够不够用'、'我的IP是什么'时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["cpu", "memory", "disk", "network", "all"],
                        "description": "查询类别：cpu(CPU使用率)、memory(内存)、disk(磁盘)、network(网络)、all(全部)"
                    }
                },
                "required": ["category"]
            }
        }
    },
]


def _get_cpu_usage() -> str:
    """通过 PowerShell 获取 CPU 使用率。"""
    try:
        script = (
            "Get-CimInstance Win32_Processor | "
            "Select-Object -Property Name, LoadPercentage | "
            "ConvertTo-Json"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, list):
                data = data[0]
            name = data.get("Name", "未知")
            load = data.get("LoadPercentage", "N/A")
            return f"CPU: {name}\n使用率: {load}%"
        return f"CPU 使用率: 查询失败"
    except subprocess.TimeoutExpired:
        return "CPU 查询超时"
    except Exception as e:
        return f"CPU 查询出错: {e}"


def _get_memory_info() -> str:
    """获取内存信息。"""
    try:
        script = (
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object TotalVisibleMemorySize, FreePhysicalMemory | "
            "ConvertTo-Json"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            total_kb = int(data["TotalVisibleMemorySize"])
            free_kb = int(data["FreePhysicalMemory"])
            used_kb = total_kb - free_kb
            total_gb = total_kb / 1024 / 1024
            used_gb = used_kb / 1024 / 1024
            free_gb = free_kb / 1024 / 1024
            pct = (used_kb / total_kb) * 100
            return (
                f"内存总量: {total_gb:.1f} GB\n"
                f"已用: {used_gb:.1f} GB ({pct:.0f}%)\n"
                f"可用: {free_gb:.1f} GB"
            )
        return "内存查询失败"
    except Exception as e:
        return f"内存查询出错: {e}"


def _get_disk_info() -> str:
    """获取磁盘信息。"""
    try:
        script = (
            "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
            "Select-Object DeviceID, Size, FreeSpace | "
            "ConvertTo-Json"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            lines = ["磁盘信息："]
            for disk in data:
                device = disk["DeviceID"]
                total = int(disk["Size"]) if disk.get("Size") else 0
                free = int(disk["FreeSpace"]) if disk.get("FreeSpace") else 0
                used = total - free
                total_gb = total / 1024 / 1024 / 1024
                used_gb = used / 1024 / 1024 / 1024
                free_gb = free / 1024 / 1024 / 1024
                pct = (used / total) * 100 if total > 0 else 0
                lines.append(
                    f"  {device}  {total_gb:.0f} GB | "
                    f"已用 {used_gb:.0f} GB ({pct:.0f}%) | "
                    f"可用 {free_gb:.0f} GB"
                )
            return "\n".join(lines)
        return "磁盘查询失败"
    except Exception as e:
        return f"磁盘查询出错: {e}"


def _get_network_info() -> str:
    """获取网络信息。"""
    try:
        # IP 地址
        ip_script = (
            "Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias '*' | "
            "Where-Object {$_.InterfaceAlias -notlike '*Loopback*'} | "
            "Select-Object InterfaceAlias, IPAddress | ConvertTo-Json"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ip_script],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        lines = ["网络信息："]
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            for item in data:
                iface = item.get("InterfaceAlias", "未知")
                ip = item.get("IPAddress", "N/A")
                lines.append(f"  {iface}: {ip}")
        else:
            lines.append("  IP 查询失败")

        return "\n".join(lines)
    except Exception as e:
        return f"网络查询出错: {e}"


def get_system_info(category: str = "all") -> str:
    """主工具函数，根据类别返回系统信息。"""
    if category == "cpu":
        return _get_cpu_usage()
    elif category == "memory":
        return _get_memory_info()
    elif category == "disk":
        return _get_disk_info()
    elif category == "network":
        return _get_network_info()
    else:  # all
        parts = [
            _get_cpu_usage(),
            "",
            _get_memory_info(),
            "",
            _get_disk_info(),
            "",
            _get_network_info(),
        ]
        return "\n".join(parts)


TOOL_EXECUTORS = {
    "get_system_info": lambda inp: get_system_info(inp.get("category", "all")),
}
