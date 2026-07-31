"""Phase 6 浏览器自动化功能测试 v2（自定义 ref 系统）"""
import sys
sys.path.insert(0, ".")

from brain.browser_controller import BrowserController, get_browser, close_browser

print("=" * 50)
print("Phase 6 浏览器自动化测试 v2")
print("=" * 50)

try:
    browser = get_browser()

    # Test 1: 导航 + 快照
    print("\n[Test 1] 导航到百度首页...")
    snapshot = browser.navigate("https://www.baidu.com")
    print(snapshot[:1500])
    print("  [PASS]")

    # Test 2: 截图
    print("\n[Test 2] 截取百度首页...")
    path = browser.screenshot()
    print(f"  截图: {path}")
    print("  [PASS]")

    # Test 3: 找输入框并填写
    print("\n[Test 3] 找搜索框并填写...")
    textbox = None
    for r in browser._last_refs:
        if r.get("role") in ("textbox", "searchbox"):
            textbox = r
            break
    if textbox:
        ref = textbox["ref"]
        print(f"  搜索框: ref={ref}, name='{textbox.get('name', '')}'")
        result = browser.fill(ref, "莲心AI")
        print(f"  填写结果 (前 600 字符): {result[:600]}")
        print("  [PASS]")
    else:
        print("  [SKIP] 未找到输入框")

    # Test 4: 找按钮并点击
    print("\n[Test 4] 找搜索按钮并点击...")
    button = None
    for r in browser._last_refs:
        if r.get("role") == "button":
            name = r.get("name", "")
            if "百度" in name or "搜索" in name or len(name) < 10:
                button = r
                break
    if button:
        ref = button["ref"]
        print(f"  搜索按钮: ref={ref}, name='{button.get('name', '')}'")
        result = browser.click(ref)
        print(f"  结果 (前 600 字符): {result[:600]}")
        print("  [PASS]")
    else:
        print("  [SKIP] 未找到搜索按钮")

    # Test 5: 搜索结果截图
    print("\n[Test 5] 截取搜索结果页...")
    path = browser.screenshot()
    print(f"  截图: {path}")
    print("  [PASS]")

except Exception as e:
    print(f"\n  [FAIL] {e}")
    import traceback
    traceback.print_exc()
finally:
    close_browser()
    print("\n浏览器已关闭")

print("\n" + "=" * 50)
print("测试完成")
print("=" * 50)
