# tests/test_notebook.py
"""会话草稿本单元测试 — 直接运行 python tests/test_notebook.py"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from brain.notebook import Notebook, get_notebook


def test_write_read():
    """基本写入/读取"""
    nb = Notebook()
    r = nb.write("test1", "hello world")
    assert "已写入" in r, f"写入失败: {r}"
    assert nb.read("test1") == "hello world", "读取不一致"
    print("  ✅ test_write_read")


def test_read_all():
    """列出所有笔记"""
    nb = Notebook()
    nb.write("a", "111")
    nb.write("b", "222")
    r = nb.read()
    assert "[a]" in r and "[b]" in r, f"列表不完整: {r}"
    print("  ✅ test_read_all")


def test_delete():
    """删除笔记"""
    nb = Notebook()
    nb.write("del_me", "xxx")
    nb.delete("del_me")
    assert "没有" in nb.read("del_me"), "删除后仍可读"
    print("  ✅ test_delete")


def test_key_clean():
    """key 清洗：中文/空格/大写 → 干净 key"""
    nb = Notebook()
    nb.write("我的 笔记", "content")
    r = nb.read()
    assert "我的_笔记" not in r, "中文未清洗"
    assert "_____" not in r, "空格转下划线后应进一步清洗"
    print("  ✅ test_key_clean (key 被清洗为纯 [a-z0-9_-])")


def test_value_max_length():
    """超长内容截断"""
    nb = Notebook()
    huge = "x" * 10000
    r = nb.write("big", huge)
    stored = nb.read("big")
    assert len(stored) <= 8000, f"超过 8000 限制: {len(stored)}"
    assert "已写入" in r, f"应正常写入: {r}"
    print("  ✅ test_value_max_length")


def test_max_entries():
    """满 50 条后拒绝写入"""
    nb = Notebook()
    for i in range(50):
        nb.write(f"k{i}", str(i))
    r = nb.write("k50", "overflow")
    assert "已满" in r or "最多" in r, f"应拒绝写入: {r}"
    print("  ✅ test_max_entries")


def test_persistence():
    """持久化写入 → 新建 Notebook 实例 → 仍可读取"""
    nb1 = Notebook()
    nb1.write("persist_key", "cross-session", persist=True)
    nb1.clear()  # 清空内存

    nb2 = Notebook()  # 新建实例，应自动加载持久化数据
    val = nb2.read("persist_key")
    assert val == "cross-session", f"持久化失败: {val}"
    # 清理
    nb2.delete("persist_key")
    print("  ✅ test_persistence")


def test_non_persist_clear():
    """非持久笔记 — clear() 后消失"""
    nb = Notebook()
    nb.write("temp", "data", persist=False)
    nb.clear()
    assert "没有" in nb.read("temp"), "清空后仍有数据"
    print("  ✅ test_non_persist_clear")


def test_thread_safety():
    """并发写入不崩溃"""
    import threading
    nb = get_notebook()
    errors = []

    def writer(i):
        try:
            nb.write(f"thread_{i}", f"value_{i}")
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"并发异常: {errors}"
    print("  ✅ test_thread_safety")


if __name__ == "__main__":
    print("=== 会话草稿本单元测试 ===\n")
    tests = [
        test_write_read, test_read_all, test_delete,
        test_key_clean, test_value_max_length, test_max_entries,
        test_persistence, test_non_persist_clear, test_thread_safety,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  💥 {t.__name__} 崩溃: {e}")
    print(f"\n结果: {passed}/{len(tests)} 通过")
