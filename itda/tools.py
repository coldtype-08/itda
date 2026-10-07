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
    "openapi.naver.com",
    "api.search.brave.com",
}
NAVER_KINDS = ("local", "blog", "encyc", "news", "webkr")
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
            "naver": self.naver,
            "brave": self.brave,
        }

    # ---- plumbing -------------------------------------------------------------------------
    def available(self) -> dict[str, str]:
        out = {"wiki": "위키백과 문서 요약 검색 (키 불필요)", "weather": "지명+날짜 일기예보 (Open-Meteo, 키 불필요)"}
        if os.environ.get("TAVILY_API_KEY"):
            out["tavily"] = "일반 웹 검색 (Tavily)"
        if os.environ.get("DATA_GO_KR_KEY"):
            out["tour"] = "한국관광공사 TourAPI: 관광지 검색 + 운영시간·휴무일·요금·주차·유모차 정보·개요 (공식 공공데이터)"
        if os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET"):
            out["naver"] = ("네이버 검색 API. kind=local(지도 등록 장소: 이름·주소·분류), blog(블로그 요약, 신뢰도 낮음), "
                            "encyc(지식백과), news(뉴스). 지도 리뷰·블로그 본문은 제공되지 않음")
        if os.environ.get("BRAVE_API_KEY"):
            out["brave"] = "일반 웹 검색 (Brave Search)"
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
        """Korea Tourism Organization search + detail for the top hits: hours, closed days, fees, overview."""
        svc = "EngService2" if lang == "en" else "KorService2"
        common = {"MobileOS": "ETC", "MobileApp": "ITDA", "_type": "json"}
        key = os.environ["DATA_GO_KR_KEY"]  # inside the sandbox this is an OpenShell placeholder

        def get(op: str, **params) -> list:
            qs = urllib.parse.urlencode({**common, **params})
            r = self._http(f"{TOUR_BASE}/{svc}/{op}?serviceKey={key}&{qs}")
            items = (((r.get("response") or {}).get("body") or {}).get("items") or {})
            items = items.get("item", []) if isinstance(items, dict) else []
            return items if isinstance(items, list) else [items]

        hits = get("searchKeyword2", keyword=keyword, numOfRows=5, pageNo=1)
        results = []
        for i, h in enumerate(hits[:5]):
            row = {"title": h.get("title"), "addr": h.get("addr1"), "contentid": h.get("contentid"),
                   "contenttypeid": h.get("contenttypeid"), "tel": h.get("tel")}
            if i < 2 and h.get("contentid"):
                try:  # opening hours, closed days, fees, parking, stroller/accessibility notes
                    intro = (get("detailIntro2", contentId=h["contentid"], contentTypeId=h.get("contenttypeid", "")) or [{}])[0]
                    row["detail"] = {k: _strip_tags(str(v))[:300] for k, v in intro.items()
                                     if v and any(t in k for t in ("usetime", "restdate", "usefee", "parking",
                                                                   "chkbabycarriage", "infocenter", "opentime",
                                                                   "eventstartdate", "eventenddate", "playtime"))}
                except Exception as e:  # keep the search hit even if detail fails
                    row["detail_error"] = type(e).__name__
                try:
                    common_d = (get("detailCommon2", contentId=h["contentid"]) or [{}])[0]
                    if common_d.get("overview"):
                        row["overview"] = _strip_tags(common_d["overview"])[:600]
                except Exception:
                    pass
            results.append(row)
        return {"keyword": keyword, "source": "한국관광공사 TourAPI (공공데이터포털)", "results": results}

    def naver(self, query: str, kind: str = "local", display: int = 5) -> dict:
        kind = kind if kind in NAVER_KINDS else "local"
        qs = urllib.parse.urlencode({"query": query, "display": max(1, min(int(display), 5 if kind == "local" else 10))})
        r = self._http(f"https://openapi.naver.com/v1/search/{kind}.json?{qs}",
                       headers={"X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
                                "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"]})
        keep = ("title", "description", "link", "postdate", "pubDate", "category", "address", "roadAddress",
                "mapx", "mapy", "bloggername")
        items = [{k: _strip_tags(str(i[k])) for k in keep if i.get(k)} for i in r.get("items", [])]
        return {"query": query, "kind": kind, "results": items,
                "note": "블로그·카페 결과는 개인 의견이며 협찬·체험단 글일 수 있음" if kind == "blog" else ""}

    def brave(self, query: str) -> dict:
        qs = urllib.parse.urlencode({"q": query, "count": 5, "country": "KR", "search_lang": "ko"})
        r = self._http(f"https://api.search.brave.com/res/v1/web/search?{qs}",
                       headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"]})
        return {"query": query, "results": [{"title": x.get("title"), "url": x.get("url"),
                                             "description": _strip_tags(x.get("description") or "")[:600],
                                             "age": x.get("age")}
                                            for x in (r.get("web") or {}).get("results", [])[:5]]}


def _strip_tags(s: str) -> str:
    import html
    import re
    return html.unescape(re.sub(r"<[^>]+>", "", s))
