---
triggers: ["链接", "URL", "https", "http", "://", "爬取", "网页内容", "知乎", "fetch", "Tavily", "Firecrawl", "网站", "页面", "打开", "查一下", "查查", "资料", "新闻", "搜索", "检索", "全网", "热搜", "最新", "资讯", "浏览", "这个链接", "抓取", "采集"]
---

## 联网搜索高级指南

## 网页获取回退链
fetch_webpage → 失败(403/空)→ fetch_webpage_via_api → 再失败→ fetch_webpage_browser
无法获取内容时直言，严禁编造。

## 搜索工具优先级
1. Tavily (mcp__tavily_search__tavily_search) — 高质量 AI 搜索，不受墙限制
2. global_search (mcp__global_search__global_search) — 知乎全网搜索
3. Firecrawl (mcp__firecrawl__scrape_url) — 爬取网页为 Markdown
4. {fallback_tools} — 最后备选

## 铁律
🚫 严禁 Firecrawl 爬 zhihu.com！遇到知乎用 Tavily 摘要。
MCP 失败重试最多 {max_retries} 次，仍失败按回退策略处理。quota/rate limit 错误立即切换。
{builtin_tool_notes}
