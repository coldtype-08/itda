"""External collection tools (stdlib HTTP). Read-only, allow-listed, audited.

Two layers of control:
  1. here: only tools in TOOLS can run, only against ALLOWED_HOSTS, GET/POST-search only;
  2. OpenShell: the sandbox network policy (policy/itda-tools.yaml) allows exactly these hosts.
API keys come from env vars. Inside the sandbox those hold OpenShell placeholders that the
proxy swaps for the real credential only at the bound endpoint, so the agent never sees them.
Everything a tool returns is untrusted data: it goes through the same triage as local files.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Callable
from urllib.parse import urlparse

from .guard import Audit

ALLOWED_HOSTS = {
    "ko.wikipedia.org", "en.wikipedia.org",
    "api.open-meteo.com", "geocoding-api.open-meteo.com",
    "api.tavily.com",
    "apis.data.go.kr",
}
UA = "ItDA-hackathon-agent/0.1 (K-culture course drafts)"
TOUR_BASE = os.environ.get("ITDA_TOUR_BASE", "https://apis.data.go.kr/B551011")


class ToolBlocked(PermissionError):
    pass


class Tools:
    def __init__(self, audit: Audit, timeout: float = 15) -> None:
        self.audit = audit
        self.timeout = timeout
        self.registry: dict[str, Callable[..., dict]] = {
            "wiki": self.wiki,
            "weather": self.weather,
            "tavily": self.tavily,
            "tour": self.tour,
        }

    # ---- plumbing -------------------------------------------------------------------------
    def available(self) -> dict[str, str]:
        out = {"wiki": "위키백과 문서 요약 검색 (키 불필요)", "weather": "지명+날짜 일기예보 (Open-Meteo, 키 불필요)"}
        if os.environ.get("TAVILY_API_KEY"):
            out["tavily"] = "일반 웹 검색 (Tavily)"
        if os.environ.get("DATA_GO_KR_KEY"):
            out["tour"] = "한국관광공사 관광정보 키워드 검색 (공공데이터포털)"
        return out

    def _http(self, url: str, body: dict | None = None, headers: dict | None = None) -> dict:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_HOSTS:
            self.audit.log("tool_blocked", host=host, reason="host not allow-listed")
            raise ToolBlocked(f"host not allowed: {host}")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"User-Agent": UA, "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if data else {}),
                                              **(headers or {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def call(self, name: str, **kwargs) -> dict:
        """Run one planned tool call. Unknown or unavailable tools are refused and audited."""
        if name not in self.registry or name not in self.available():
            self.audit.log("tool_blocked", tool=name, reason="tool not allowed or not configured")
            return {"tool": name, "ok": False, "error": "tool not allowed"}
        try:
            res = self.registry[name](**kwargs)
            self.audit.log("tool_call", tool=name, ok=True, args={k: str(v)[:80] for k, v in kwargs.items()})
            return {"tool": name, "ok": True, **res}
        except Exception as e:  # network denied by OpenShell shows up here as an error
            self.audit.log("tool_call", tool=name, ok=False, error=f"{type(e).__name__}: {str(e)[:120]}")
            return {"tool": name, "ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    # ---- tools ----------------------------------------------------------------------------
    def wiki(self, query: str, lang: str = "ko") -> dict:
        lang = "en" if lang == "en" else "ko"
        q = urllib.parse.quote(query)
        hits = self._http(f"https://{lang}.wikipedia.org/w/rest.php/v1/search/page?q={q}&limit=3").get("pages", [])
        results = []
        for h in hits[:2]:
            title = urllib.parse.quote(h["key"])
            s = self._http(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}")
            results.append({"title": s.get("title"), "extract": (s.get("extract") or "")[:1200],
                            "url": s.get("content_urls", {}).get("desktop", {}).get("page")})
        return {"query": query, "results": results}

    def weather(self, place: str, date: str) -> dict:
        g = self._http("https://geocoding-api.open-meteo.com/v1/search?count=1&language=ko&name="
                       + urllib.parse.quote(place)).get("results") or []
        if not g:
            return {"place": place, "date": date, "results": [], "note": "지명을 찾지 못함 (가상 지명일 수 있음)"}
        lat, lon = g[0]["latitude"], g[0]["longitude"]
        f = self._http(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                       f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                       f"&timezone=Asia%2FSeoul&start_date={date}&end_date={date}")
        return {"place": place, "resolved": g[0].get("name"), "date": date, "daily": f.get("daily", {})}

    def tavily(self, query: str) -> dict:
        r = self._http("https://api.tavily.com/search",
                       body={"query": query, "max_results": 4, "search_depth": "basic"},
                       headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"})
        return {"query": query, "results": [{"title": x.get("title"), "url": x.get("url"),
                                             "content": (x.get("content") or "")[:800]}
                                            for x in r.get("results", [])]}

    def tour(self, keyword: str, lang: str = "ko") -> dict:
        svc = "EngService2" if lang == "en" else "KorService2"
        qs = urllib.parse.urlencode({"MobileOS": "ETC", "MobileApp": "ITDA", "_type": "json",
                                     "numOfRows": 5, "pageNo": 1, "keyword": keyword})
        # serviceKey is appended raw: inside the sandbox it is an OpenShell placeholder.
        r = self._http(f"{TOUR_BASE}/{svc}/searchKeyword2?serviceKey={os.environ['DATA_GO_KR_KEY']}&{qs}")
        items = (((r.get("response") or {}).get("body") or {}).get("items") or {})
        items = items.get("item", []) if isinstance(items, dict) else []
        return {"keyword": keyword, "results": [{"title": i.get("title"), "addr": i.get("addr1"),
                                                 "contentid": i.get("contentid")} for i in items[:5]]}
