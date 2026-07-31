# 系统信息工具 - 获取 CPU/内存/磁盘/网络/GPU 运行状态
# 多重回退：PowerShell → wmic → psutil/nvidia-smi

import subprocess
import json
import os

# PowerShell 可能的路径（按优先级）
_POWERSHELL_PATHS = [
    "powershell.exe",
    "pwsh.exe",
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    r"C:\Program Files\PowerShell\7\pwsh.exe",
]


def _find_powershell() -> str | None:
    """查找可用的 PowerShell 路径。"""
    for path in _POWERSHELL_PATHS:
        try:
            result = subprocess.run(
                [path, "-NoProfile", "-Command", "exit 0"],
                capture_output=True, timeout=5,
                encoding="utf-8", errors="replace"
            )
            if result.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _run_powershell(script: str, timeout: int = 10) -> tuple[bool, str]:
    """运行 PowerShell 脚本，返回 (成功, 输出)。"""
    ps = _find_powershell()
    if not ps:
        return False, "PowerShell 不可用"
    try:
        result = subprocess.run(
            [ps, "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            return True, result.stdout.strip()
        return False, result.stderr.strip() or "PowerShell 返回空结果"
    except subprocess.TimeoutExpired:
        return False, "PowerShell 执行超时"
    except Exception as e:
        return False, f"PowerShell 执行异常: {e}"


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": (
                "查询当前 Windows 系统的运行状态信息。"
                "支持查询 CPU 使用率、内存占用、磁盘空间、网络状态、显卡信息。"
                "当用户问'电脑卡不卡'、'还剩多少内存'、'磁盘够不够用'、'我的GPU是什么'时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["cpu", "memory", "disk", "network", "gpu", "all"],
                        "description": "查询类别：cpu(CPU使用率)、memory(内存)、disk(磁盘)、network(网络)、gpu(显卡)、all(全部)"
                    }
                },
                "required": ["category"]
            }
        }
    },
]


def _get_cpu_usage() -> str:
    """获取 CPU 使用率（多重回退）。"""
    # ① PowerShell
    ok, out = _run_powershell(
        "Get-CimInstance Win32_Processor | "
        "Select-Object -Property Name, LoadPercentage | "
        "ConvertTo-Json"
    )
    if ok:
        try:
            data = json.loads(out)
            if isinstance(data, list):
                data = data[0]
            name = data.get("Name", "未知")
            load = data.get("LoadPercentage", "N/A")
            return f"CPU: {name}\n使用率: {load}%"
        except (json.JSONDecodeError, KeyError):
            pass

    # ② wmic
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "Name,LoadPercentage", "/format:csv"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split(",")
                if len(parts) >= 3:
                    return f"CPU: {parts[1].strip()}\n使用率: {parts[2].strip()}%"
    except Exception:
        pass

    # ③ psutil
    try:
        import psutil
        usage = psutil.cpu_percent(interval=0.5)
        count = psutil.cpu_count()
        return f"CPU: {count} 核\n使用率: {usage}%"
    except ImportError:
        pass
    except Exception:
        pass

    return "CPU 信息获取失败：当前运行环境不支持查询（PowerShell/wmic/psutil 均不可用）"


def _get_memory_info() -> str:
    """获取内存信息（多重回退）。"""
    # ① PowerShell
    ok, out = _run_powershell(
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object TotalVisibleMemorySize, FreePhysicalMemory | "
        "ConvertTo-Json"
    )
    if ok:
        try:
            data = json.loads(out)
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
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # ② wmic
    try:
        result = subprocess.run(
            ["wmic", "OS", "get",
             "TotalVisibleMemorySize,FreePhysicalMemory", "/format:csv"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split(",")
                if len(parts) >= 3:
                    total_kb = int(parts[1].strip())
                    free_kb = int(parts[2].strip())
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
    except Exception:
        pass

    # ③ psutil
    try:
        import psutil
        mem = psutil.virtual_memory()
        return (
            f"内存总量: {mem.total / (1024**3):.1f} GB\n"
            f"已用: {mem.used / (1024**3):.1f} GB ({mem.percent:.0f}%)\n"
            f"可用: {mem.available / (1024**3):.1f} GB"
        )
    except ImportError:
        pass
    except Exception:
        pass

    return "内存信息获取失败：当前运行环境不支持查询（PowerShell/wmic/psutil 均不可用）"


def _get_disk_info() -> str:
    """获取磁盘信息（多重回退）。"""
    # ① PowerShell
    ok, out = _run_powershell(
        "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
        "Select-Object DeviceID, Size, FreeSpace | "
        "ConvertTo-Json"
    )
    if ok:
        try:
            data = json.loads(out)
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
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # ② wmic
    try:
        result = subprocess.run(
            ["wmic", "logicaldisk", "where", "DriveType=3",
             "get", "DeviceID,Size,FreeSpace", "/format:csv"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            disk_lines = ["磁盘信息："]
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 4:
                    device = parts[1].strip()
                    total = int(parts[2].strip()) if parts[2].strip() else 0
                    free = int(parts[3].strip()) if parts[3].strip() else 0
                    used = total - free
                    total_gb = total / 1024 / 1024 / 1024
                    used_gb = used / 1024 / 1024 / 1024
                    free_gb = free / 1024 / 1024 / 1024
                    pct = (used / total) * 100 if total > 0 else 0
                    disk_lines.append(
                        f"  {device}  {total_gb:.0f} GB | "
                        f"已用 {used_gb:.0f} GB ({pct:.0f}%) | "
                        f"可用 {free_gb:.0f} GB"
                    )
            if len(disk_lines) > 1:
                return "\n".join(disk_lines)
    except Exception:
        pass

    # ③ psutil
    try:
        import psutil
        lines = ["磁盘信息："]
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                lines.append(
                    f"  {part.device}  {usage.total / (1024**3):.0f} GB | "
                    f"已用 {usage.used / (1024**3):.0f} GB ({usage.percent:.0f}%) | "
                    f"可用 {usage.free / (1024**3):.0f} GB"
                )
            except Exception:
                continue
        if len(lines) > 1:
            return "\n".join(lines)
    except ImportError:
        pass
    except Exception:
        pass

    return "磁盘信息获取失败：当前运行环境不支持查询（PowerShell/wmic/psutil 均不可用）"


def _get_gpu_info() -> str:
    """获取 GPU 信息（nvidia-smi 优先，PowerShell/wmic 兜底）。"""
    lines = []
    has_nvidia = False

    # ① nvidia-smi — NVIDIA GPU 最准确的显存/利用率/温度
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            has_nvidia = True
            for i, line in enumerate(result.stdout.strip().split("\n"), 1):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    name, util, mem_used, mem_total, temp = parts[0], parts[1], parts[2], parts[3], parts[4]
                    mem_used_gb = float(mem_used) / 1024 if mem_used else 0
                    mem_total_gb = float(mem_total) / 1024 if mem_total else 0
                    lines.append(
                        f"  GPU{i}: {name}\n"
                        f"    使用率: {util}%\n"
                        f"    显存: {mem_used_gb:.1f}/{mem_total_gb:.1f} GB\n"
                        f"    温度: {temp}°C"
                    )
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # ② PowerShell — 补充非 NVIDIA 显卡 + 分辨率信息
    ok, out = _run_powershell(
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name, AdapterRAM, DriverVersion, CurrentHorizontalResolution, CurrentVerticalResolution | "
        "ConvertTo-Json"
    )
    if ok:
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            for gpu in data:
                name = gpu.get("Name", "未知")
                # 如果 nvidia-smi 已经拿到了这个 GPU，跳过 PowerShell 的不可靠数据
                if has_nvidia and "NVIDIA" in name.upper():
                    continue
                ram_bytes = gpu.get("AdapterRAM") or 0
                ram_gb = int(ram_bytes) / (1024**3) if ram_bytes else 0
                driver = gpu.get("DriverVersion", "未知")
                w = gpu.get("CurrentHorizontalResolution")
                h = gpu.get("CurrentVerticalResolution")
                res = f"{w}x{h}" if w and h else "未知"
                lines.append(
                    f"  GPU: {name}\n"
                    f"    显存: {ram_gb:.1f} GB\n"
                    f"    分辨率: {res}\n"
                    f"    驱动: {driver}"
                )
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # ③ wmic — 最终兜底
    if not lines:
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_videocontroller",
                 "get", "Name,AdapterRAM,DriverVersion", "/format:csv"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace"
            )
            if result.returncode == 0 and result.stdout.strip():
                lines_raw = result.stdout.strip().split("\n")
                for i, line in enumerate(lines_raw[1:], 1):
                    parts = line.split(",")
                    if len(parts) >= 4:
                        name = parts[1].strip()
                        ram_bytes = int(parts[2].strip()) if parts[2].strip() else 0
                        ram_gb = ram_bytes / (1024**3) if ram_bytes else 0
                        driver = parts[3].strip() if len(parts) > 3 else "未知"
                        lines.append(
                            f"  GPU{i}: {name}\n"
                            f"    显存: {ram_gb:.1f} GB\n"
                            f"    驱动: {driver}"
                        )
        except Exception:
            pass

    if lines:
        return "GPU 信息：\n" + "\n".join(lines)
    return "GPU 信息获取失败：当前运行环境不支持查询（nvidia-smi/PowerShell/wmic 均不可用）"


def _get_network_info() -> str:
    """获取网络信息（多重回退）。"""
    # ① PowerShell
    ok, out = _run_powershell(
        "Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias '*' | "
        "Where-Object {$_.InterfaceAlias -notlike '*Loopback*'} | "
        "Select-Object InterfaceAlias, IPAddress | ConvertTo-Json"
    )
    if ok:
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            lines = ["网络信息："]
            for item in data:
                iface = item.get("InterfaceAlias", "未知")
                ip = item.get("IPAddress", "N/A")
                lines.append(f"  {iface}: {ip}")
            return "\n".join(lines)
        except (json.JSONDecodeError, KeyError):
            pass

    # ② ipconfig
    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True, text=True, timeout=10,
            encoding="gbk", errors="replace"
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = ["网络信息（ipconfig）："]
            for line in result.stdout.split("\n"):
                s = line.strip()
                if any(k in s for k in ["IPv4", "IPv6", "适配器", "adapter"]):
                    lines.append(f"  {s}")
            if len(lines) > 1:
                return "\n".join(lines)
    except Exception:
        pass

    # ③ socket
    try:
        import socket
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        return f"网络信息：\n  主机名: {hostname}\n  本机 IP: {ip}"
    except Exception:
        pass

    return "网络信息获取失败：当前运行环境不支持查询"


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
    elif category == "gpu":
        return _get_gpu_info()
    else:  # all
        parts = [
            _get_cpu_usage(),
            "",
            _get_memory_info(),
            "",
            _get_disk_info(),
            "",
            _get_gpu_info(),
            "",
            _get_network_info(),
        ]
        return "\n".join(parts)


TOOL_EXECUTORS = {
    "get_system_info": lambda inp: get_system_info(inp.get("category", "all")),
}
