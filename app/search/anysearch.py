"""
AnySearch API 客户端
接口编号: IF-001
协议: MCP Streamable HTTP (https://api.anysearch.com/mcp)
工具: search, batch_search, extract, get_sub_domains

设计原则:
  1. 上层只依赖 SearchResultItem 数据结构
  2. 底层解析 Markdown 格式的 MCP 响应，转换成结构化对象
  3. 支持单条搜索、批量搜索、URL正文提取
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, HttpUrl


# ═══════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════

class SearchDepth(str):
    BASIC = "basic"
    ADVANCED = "advanced"
    FULL = "full"


class SearchQuery(BaseModel):
    """单条搜索请求。"""
    query: str = Field(..., description="搜索关键词", max_length=500)
    max_results: int = Field(default=10, ge=1, le=10, description="最大结果数(AnySearch上限10)")
    domain: str | None = Field(default=None, description="垂直领域(需先调用get_sub_domains)")
    sub_domain: str | None = None
    sub_domain_params: dict[str, Any] | None = None
    category: str | None = Field(default=None, description="业务分类标签(追溯用)")
    batch_id: str | None = None


class SearchResultItem(BaseModel):
    """单条搜索结果(统一格式)。"""
    result_id: str
    title: str
    url: HttpUrl
    source_domain: str
    source_name: str | None = None
    snippet: str = ""
    content: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    language: str | None = None
    score: float | None = None
    query_origin: str | None = None

    @classmethod
    def make_id(cls, url: str, title: str) -> str:
        seed = f"{url}|{title}".lower()
        return "res_" + hashlib.sha256(seed.encode()).hexdigest()[:12]


class SearchQueryResponse(BaseModel):
    """单条查询的响应。"""
    query: str
    total_found: int = 0
    results: list[SearchResultItem] = Field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None


class SearchBatchResponse(BaseModel):
    """批量搜索响应。"""
    batch_id: str
    total_queries: int
    success_queries: int
    failed_queries: int
    total_results: int
    unique_results: int
    responses: list[SearchQueryResponse]
    started_at: datetime
    finished_at: datetime


# ═══════════════════════════════════════════════════════
# Markdown 解析器
# ═══════════════════════════════════════════════════════

def _parse_search_results(md_text: str, query_origin: str | None = None) -> tuple[int, list[SearchResultItem]]:
    """
    解析 AnySearch 返回的 Markdown 搜索结果。

    格式示例:
        ## Search Results (5 results, 331ms)

        ### 1. Title Here
        - **URL**: https://...
        - 摘要正文...

        ### 2. ...
    """
    results: list[SearchResultItem] = []

    # 提取总结果数
    total_match = re.search(r'\((\d+)\s+results', md_text)
    total_found = int(total_match.group(1)) if total_match else 0

    # 提取延迟
    latency_match = re.search(r'(\d+)\s*ms\)', md_text)
    latency_ms = int(latency_match.group(1)) if latency_match else 0

    # 按 ### 分割每条结果
    # 匹配: ### 数字. 标题
    pattern = re.compile(
        r'###\s+\d+\.\s+(.+?)\n'    # 标题
        r'-\s+\*\*URL\*\*:\s+(\S+)\n'  # URL
        r'-\s+(.*?)(?=\n###\s+\d+\.|\n##\s|$)',  # 摘要内容
        re.DOTALL
    )

    now = datetime.now(timezone.utc)

    for match in pattern.finditer(md_text):
        title = match.group(1).strip()
        url = match.group(2).strip()
        snippet = match.group(3).strip()

        # 清理摘要（去掉开头的重复标题等）
        snippet = _clean_snippet(snippet, title)

        # 提取域名
        try:
            parsed = urlparse(url)
            source_domain = parsed.netloc.replace("www.", "")
        except Exception:
            source_domain = "unknown"

        result = SearchResultItem(
            result_id=SearchResultItem.make_id(url, title),
            title=title,
            url=url,
            source_domain=source_domain,
            snippet=snippet,
            published_at=_extract_published_date(url, title + " " + snippet),
            fetched_at=now,
            query_origin=query_origin,
        )
        results.append(result)

    return total_found, results


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_flexible_date(value) -> datetime | None:
    """宽松解析日期（ISO / 'Aug 17, 2026' / 纯日期串），失败返回 None。"""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})$", v)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(2)))
            except ValueError:
                return None
    return None


def _extract_published_date(url: str, text: str) -> datetime | None:
    """
    多信号估算发布时间（架构评审 #2）。
    优先级: URL 中的日期 > 文本中最近的合法日期。
    仅接受 [now-400d, now+1d] 范围内的日期，避免误抓正文里的历史年份。
    """
    now = datetime.now(timezone.utc)
    lo, hi = now - timedelta(days=400), now + timedelta(days=1)

    def valid(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt if lo <= dt <= hi else None

    # 1) URL 日期: /2026-08-17/  /2026/08/17/  /20260817/
    m = re.search(r"/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", url)
    if m:
        dt = valid(_safe_date(*map(int, m.groups())))
        if dt:
            return dt
    m = re.search(r"/(20\d{2})(\d{2})(\d{2})(?:/|$)", url)
    if m:
        dt = valid(_safe_date(*map(int, m.groups())))
        if dt:
            return dt

    # 2) 文本日期，取最近的合法值
    candidates: list[datetime] = []
    for m in re.finditer(r"(20\d{2})-(\d{1,2})-(\d{1,2})", text):
        dt = _safe_date(*map(int, m.groups()))
        if dt:
            candidates.append(dt)
    for m in re.finditer(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})", text):
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            dt = _safe_date(int(m.group(3)), mon, int(m.group(2)))
            if dt:
                candidates.append(dt)
    for m in re.finditer(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text):
        dt = _safe_date(*map(int, m.groups()))
        if dt:
            candidates.append(dt)

    best = None
    for dt in sorted(candidates, reverse=True):
        v = valid(dt)
        if v:
            best = v
            break
    if best:
        return best

    # 3) 月级日期仅作为"明显旧"信号：超过 35 天才返回（将被时效过滤丢弃），
    #    当月/近期月份返回 None（保留），避免误杀标题含当月的时新内容
    month_candidates: list[datetime] = []
    for m in re.finditer(r"(20\d{2})年(\d{1,2})月(?!\d)", text):
        dt = _safe_date(int(m.group(1)), int(m.group(2)), 1)
        if dt:
            month_candidates.append(dt)
    for m in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d{2})\b", text):
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            dt = _safe_date(int(m.group(2)), mon, 1)
            if dt:
                month_candidates.append(dt)
    stale_cut = now.replace(tzinfo=None) - timedelta(days=35)
    for dt in sorted(month_candidates, reverse=True):
        if dt < stale_cut:
            return dt.replace(tzinfo=timezone.utc)
    return None


def _safe_date(y: int, m: int, d: int) -> datetime | None:
    try:
        return datetime(y, m, d)
    except ValueError:
        return None


def _clean_snippet(snippet: str, title: str) -> str:
    """清理搜索结果摘要中的噪声。"""
    # 去掉开头的重复标题
    if snippet.startswith(title):
        snippet = snippet[len(title):].lstrip(" –:|")

    # 去掉广告/促销内容
    snippet = re.sub(r'🚨.*?REGISTER NOW\.?', '', snippet)
    snippet = re.sub(r'Flash Sale.*?REGISTER NOW\.?', '', snippet, flags=re.IGNORECASE)

    # 去掉 "Posted: ... Image Credits:..." 这类前缀
    snippet = re.sub(
        r'^.*?(?:Posted|Published|Updated)[^.]*?(?:\d{4})?\s*[-–—]\s*',
        '',
        snippet,
        flags=re.IGNORECASE,
    )

    return snippet.strip()


def _parse_batch_results(md_text: str) -> list[tuple[str, int, list[SearchResultItem]]]:
    """
    解析 batch_search 的 Markdown 响应。

    格式:
        ## Query 1: query text

        ## Search Results (3 results, 297ms)
        ### 1. ...

        ## Query 2: ...
    """
    queries: list[tuple[str, int, list[SearchResultItem]]] = []

    # 分割每个查询的结果块
    # 匹配: ## Query N: query_text
    blocks = re.split(r'\n## Query \d+:\s+', md_text)
    # 第一个块是前缀（可能为空），跳过
    if not md_text.startswith("## Query 1:") and len(blocks) > 1:
        blocks = blocks[1:]
    elif md_text.startswith("## Query 1:"):
        # split 后第一个元素是空的
        blocks = blocks[1:] if blocks[0] == "" else blocks

    now = datetime.now(timezone.utc)

    for i, block in enumerate(blocks):
        if not block.strip():
            continue

        # 第一行是查询文本（到换行符为止）
        first_newline = block.find('\n')
        if first_newline == -1:
            query_text = block.strip()
            rest = ""
        else:
            query_text = block[:first_newline].strip()
            rest = block[first_newline:]

        # 解析这个查询的搜索结果
        total_found, results = _parse_search_results(rest, query_origin=query_text)
        queries.append((query_text, total_found, results))

    return queries


# ═══════════════════════════════════════════════════════
# 客户端
# ═══════════════════════════════════════════════════════

class AnySearchClient:
    """
    AnySearch MCP HTTP 客户端。

    用法:
        client = AnySearchClient(api_key="as_sk_...")
        resp = await client.search(SearchQuery(query="OpenAI new model"))
        for r in resp.results:
            print(r.title, r.url)
    """

    MCP_URL = "https://api.anysearch.com/mcp"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANYSEARCH_API_KEY", "")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        self._request_id = 0

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "X-Anysearch-Client": "mcp/1.0.0",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _mcp_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具。"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        resp = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result", {})

    async def search(self, query: SearchQuery) -> SearchQueryResponse:
        """执行单条搜索。"""
        import time
        start = time.time()

        try:
            args: dict[str, Any] = {
                "query": query.query,
                "max_results": query.max_results,
            }
            if query.domain:
                args["domain"] = query.domain
            if query.sub_domain:
                args["sub_domain"] = query.sub_domain
            if query.sub_domain_params:
                args["sub_domain_params"] = query.sub_domain_params

            result = await self._mcp_call("tools/call", {
                "name": "search",
                "arguments": args,
            })
            content_list = result.get("content", [])
            md_text = content_list[0].get("text", "") if content_list else ""

            total_found, results = _parse_search_results(
                md_text,
                query_origin=query.query,
            )

            latency_ms = int((time.time() - start) * 1000)
            return SearchQueryResponse(
                query=query.query,
                total_found=total_found,
                results=results,
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            return SearchQueryResponse(
                query=query.query,
                total_found=0,
                results=[],
                latency_ms=latency_ms,
                error=str(e),
            )

    async def search_batch(
        self,
        queries: list[SearchQuery],
        batch_id: str | None = None,
    ) -> SearchBatchResponse:
        """
        批量搜索。
        AnySearch batch_search 上限 5 条/批，自动分批。
        """
        import asyncio
        import time

        started = datetime.now(timezone.utc)
        start_ts = time.time()

        if not batch_id:
            batch_id = "batch_" + hashlib.md5(
                str(started.timestamp()).encode()
            ).hexdigest()[:10]

        # AnySearch batch_search 最多 5 条，分批执行
        BATCH_SIZE = 5
        all_responses: list[SearchQueryResponse] = []

        for i in range(0, len(queries), BATCH_SIZE):
            batch_queries = queries[i:i + BATCH_SIZE]
            batch_args = []

            for q in batch_queries:
                arg: dict[str, Any] = {
                    "query": q.query,
                    "max_results": q.max_results,
                }
                if q.domain:
                    arg["domain"] = q.domain
                if q.sub_domain:
                    arg["sub_domain"] = q.sub_domain
                batch_args.append(arg)

            try:
                result = await self._mcp_call("tools/call", {
                    "name": "batch_search",
                    "arguments": {"queries": batch_args},
                })
                content_list = result.get("content", [])
                md_text = content_list[0].get("text", "") if content_list else ""

                parsed = _parse_batch_results(md_text)

                # 按顺序匹配原始查询
                for j, q in enumerate(batch_queries):
                    if j < len(parsed):
                        q_text, total_found, results = parsed[j]
                        all_responses.append(SearchQueryResponse(
                            query=q.query,
                            total_found=total_found,
                            results=results,
                            latency_ms=0,
                        ))
                    else:
                        all_responses.append(SearchQueryResponse(
                            query=q.query,
                            total_found=0,
                            results=[],
                            latency_ms=0,
                            error="No result in batch response",
                        ))
            except Exception as e:
                for q in batch_queries:
                    all_responses.append(SearchQueryResponse(
                        query=q.query,
                        total_found=0,
                        results=[],
                        latency_ms=0,
                        error=str(e),
                    ))

            # 批次之间稍微休息，避免限流
            if i + BATCH_SIZE < len(queries):
                await asyncio.sleep(0.5)

        finished = datetime.now(timezone.utc)

        # 统计
        success = sum(1 for r in all_responses if r.error is None)
        failed = len(all_responses) - success

        all_results: list[SearchResultItem] = []
        seen_ids: set[str] = set()
        for resp in all_responses:
            for r in resp.results:
                if r.result_id not in seen_ids:
                    seen_ids.add(r.result_id)
                    all_results.append(r)

        return SearchBatchResponse(
            batch_id=batch_id,
            total_queries=len(all_responses),
            success_queries=success,
            failed_queries=failed,
            total_results=sum(len(r.results) for r in all_responses),
            unique_results=len(all_results),
            responses=all_responses,
            started_at=started,
            finished_at=finished,
        )

    async def extract(self, url: str) -> str:
        """提取 URL 的全文内容(Markdown)。"""
        result = await self._mcp_call("tools/call", {
            "name": "extract",
            "arguments": {"url": url},
        })
        content_list = result.get("content", [])
        return content_list[0].get("text", "") if content_list else ""

    async def close(self) -> None:
        await self._client.aclose()



# ═══════════════════════════════════════════════════════
# Tavily 搜索客户端
# ═══════════════════════════════════════════════════════

class TavilyClient:
    """
    Tavily Search API 客户端。
    作为 AnySearch 的补充/备选搜索引擎。
    """

    API_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        import os
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        time_range: str | None = None,
    ) -> list[SearchResultItem]:
        """执行 Tavily 搜索，返回统一格式的 SearchResultItem。"""
        if not self.api_key:
            return []

        params = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": False,
            "include_images": False,
        }
        if time_range:
            params["time_range"] = time_range

        try:
            resp = await self._client.post(self.API_URL, json=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️  Tavily search failed: {e}", flush=True)
            return []

        now = datetime.now(timezone.utc)
        results = []
        for r in data.get("results", []):
            url = r.get("url", "")
            title = r.get("title", "")
            snippet = r.get("content", "")
            domain = r.get("domain", "") or _extract_domain(url)
            score = r.get("score")

            results.append(SearchResultItem(
                result_id=SearchResultItem.make_id(url, title),
                title=title,
                url=url,
                source_domain=domain,
                snippet=snippet,
                published_at=_parse_flexible_date(r.get("published_date")),
                fetched_at=now,
                score=score,
                query_origin=query,
            ))

        return results

    async def close(self) -> None:
        await self._client.aclose()


def _extract_domain(url: str) -> str:
    """从 URL 提取域名。"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return "unknown"
