import httpx
from fastmcp import FastMCP

from core.config import settings

mcp = FastMCP(
    name="web-search",
    instructions="Bocha AI 联网搜索 MCP 服务,提供 web_search 工具,返回 [{title, url, snippet}] 结构化结果。",
)


async def _search(query: str, count: int | None = None) -> list[dict]:
    """Bocha AI 联网搜索;失败或无结果统一返回空列表,不抛异常(联网是兜底,不该阻断问答)。

    返回归一化结构 [{title, url, snippet}],字段缺失按空串兜底,无 url 的条目丢弃。
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url='https://api.bocha.cn/v1/web-search',
                headers={
                    'Authorization': f'Bearer {settings.BOCHAAI_KEY}',
                    'Content-Type': 'application/json',
                },
                json={
                    'query': query,
                    'freshness': 'noLimit',
                    'summary': True,
                    'count': count or settings.WEB_SEARCH_COUNT,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    pages = ((data.get('data') or {}).get('webPages') or {}).get('value') or []
    results = []
    for p in pages:
        url = p.get('url')
        if not url:
            continue
        results.append({
            'title': p.get('name') or p.get('title') or '',
            'url': url,
            'snippet': p.get('summary') or p.get('snippet') or '',
        })
    return results


@mcp.tool
async def web_search(query: str, count: int | None = None) -> list[dict]:
    """联网搜索,返回 [{title, url, snippet}] 列表;失败或无结果返回空列表。"""
    return await _search(query, count)


if __name__ == '__main__':
    mcp.run(transport='streamable-http', host='127.0.0.1', port=8100)
