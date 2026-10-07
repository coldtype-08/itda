"""Korean public-data tools (team module itda/kapi.py) and TMAP walking routes, as ItDA tools.

kapi.call_* functions return ApiResult with freshness + caveats; here they become plain dicts
that ItDA turns into evidence documents and runs through the same trust pipeline as any source.
The route tool orders the chosen places (nearest-neighbour from the first one) and measures each
leg with the TMAP pedestrian API when TMAP_APP_KEY is set, else a straight-line walking estimate.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from datetime import date
from typing import Any

TMAP_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1"


def _public_key() -> str:
    return os.environ.get("DATA_GO_KR_KEY") or os.environ.get("PUBLIC_DATA_SERVICE_KEY", "")


def _requests_ca() -> None:
    # requests ignores SSL_CERT_FILE; inside the sandbox the proxy CA is published there.
    if os.environ.get("SSL_CERT_FILE") and not os.environ.get("REQUESTS_CA_BUNDLE"):
        os.environ["REQUESTS_CA_BUNDLE"] = os.environ["SSL_CERT_FILE"]


class KoreanTools:
    def __init__(self) -> None:
        self._kapi = None
        self._client = None
        self._ekc = None
        try:
            _requests_ca()
            from . import kapi  # needs `requests`; missing -> these tools are simply unavailable
            self._kapi = kapi
        except Exception as e:  # noqa: BLE001
            self.import_error = f"{type(e).__name__}: {e}"

    # ---- availability -------------------------------------------------------------------
    def available(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self._kapi and _public_key():
            out.update({
                "place_info": "관광공사 공식 등록 정보: 운영시간·휴무일·요금·연락처·개요 (장소 이름으로)",
                "accessibility": "관광공사 무장애 여행정보: 휠체어·유모차·엘리베이터·장애인 화장실 등록 정보",
                "kma_weather": "기상청 단기예보 (방문일이 오늘~3일 이내일 때): 강수확률·기온·실외 위험도",
                "weather_warning": "기상청 기상특보 (오늘 기준 발효 중인 특보)",
                "festival": "관광공사 행사·축제 (방문일과 겹치는 것, 장소 지역 기준)",
                "nearby": "장소 주변 등록 관광지·음식점·문화시설 (대안·식사 장소 찾기)",
            })
        if self._kapi and os.environ.get("AKS_API_KEY"):
            out["encyclopedia"] = "한국민족문화대백과사전 (한국학중앙연구원): 역사·문화 주제의 권위 있는 배경 설명"
        if self._kapi and _public_key() or os.environ.get("TMAP_APP_KEY"):
            out["route"] = ("방문 장소들의 동선: 가까운 순서로 정렬하고 구간별 도보 거리·시간 계산 "
                            + ("(TMAP 보행자 경로)" if os.environ.get("TMAP_APP_KEY") else "(직선거리 추정)"))
        return out

    @property
    def client(self):
        if self._client is None:
            self._client = self._kapi.PublicDataClient(_public_key(), mobile_app="ItDA")
        return self._client

    @property
    def ekc(self):
        if self._ekc is None:
            self._ekc = self._kapi.EkcClient()
        return self._ekc

    @staticmethod
    def _pack(r, keep_items: int = 5) -> dict:
        if r is None:
            return {"status": "error", "error": "request failed (see logs)"}
        return {"source": r.service and r.source_id, "service": r.service, "operation": r.operation,
                "status": r.status, "freshness": r.freshness, "summary": r.summary,
                "items": r.items[:keep_items], "caveats": r.caveats, "error": r.error,
                "fetched_at": r.fetched_at}

    @staticmethod
    def _date(s: str | None) -> date:
        try:
            return date.fromisoformat(str(s)[:10])
        except (TypeError, ValueError):
            return date.today()

    # ---- tools -----------------------------------------------------------------------------
    def place_info(self, place: str, lang: str = "ko") -> dict:
        return self._pack(self._kapi.call_tour_place_profile(self.client, keyword=place, lang=lang))

    def accessibility(self, place: str) -> dict:
        return self._pack(self._kapi.call_barrier_free(self.client, keyword=place))

    def kma_weather(self, place: str, date: str | None = None) -> dict:
        return self._pack(self._kapi.call_weather_forecast(self.client, self._date(date), place=place, hours=(9, 18)))

    def weather_warning(self, place: str) -> dict:
        return self._pack(self._kapi.call_weather_warnings(self.client, place=place))

    def festival(self, place: str, date: str | None = None) -> dict:
        return self._pack(self._kapi.call_festivals(self.client, self._date(date), place=place))

    def nearby(self, place: str, kind: str = "food", radius_m: int = 1500) -> dict:
        kind = kind if kind in self._kapi.CONTENT_TYPES else None
        return self._pack(self._kapi.call_tour_nearby(self.client, place=place, content_kind=kind,
                                                      radius_m=radius_m, n=10))

    def encyclopedia(self, topic: str) -> dict:
        return self._pack(self._kapi.call_ekc_lookup(self.ekc, topic), keep_items=1)

    # ---- route -----------------------------------------------------------------------------
    def _coords(self, place: str) -> tuple[float, float, str] | None:
        if self._kapi and _public_key():
            try:
                return self._kapi.resolve_coords(self.client, place=place)
            except Exception:  # noqa: BLE001
                return None
        return None

    @staticmethod
    def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
        (la1, lo1), (la2, lo2) = a, b
        p1, p2 = math.radians(la1), math.radians(la2)
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
        return 2 * 6_371_000 * math.asin(math.sqrt(h))

    @staticmethod
    def _tmap_leg(a: dict, b: dict) -> dict:
        body = {"startX": str(a["lon"]), "startY": str(a["lat"]), "endX": str(b["lon"]), "endY": str(b["lat"]),
                "startName": a["name"], "endName": b["name"], "reqCoordType": "WGS84GEO",
                "resCoordType": "WGS84GEO", "searchOption": "0"}
        req = urllib.request.Request(TMAP_URL, data=json.dumps(body).encode(), method="POST",
                                     headers={"appKey": os.environ["TMAP_APP_KEY"], "Accept": "application/json",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            props = json.loads(r.read())["features"][0]["properties"]
        return {"meters": int(props.get("totalDistance", 0)), "minutes": round(int(props.get("totalTime", 0)) / 60),
                "method": "TMAP 보행자 경로"}

    def route(self, places: list[str] | str, keep_order: bool = False) -> dict:
        names = [p.strip() for p in (places.split(",") if isinstance(places, str) else places) if str(p).strip()][:8]
        pts, missing = [], []
        for n in names:
            c = self._coords(n)
            (pts.append({"name": n, "lat": c[0], "lon": c[1], "coord_source": c[2]}) if c else missing.append(n))
        if len(pts) < 2:
            return {"status": "empty", "places": names, "missing_coords": missing,
                    "caveats": ["좌표를 찾은 장소가 2곳 미만이라 동선을 계산하지 못함 (등록되지 않은 장소일 수 있음)"]}
        order = [pts[0]]
        rest = pts[1:]
        while rest:  # nearest neighbour from the first place, unless the caller fixed the order
            nxt = rest[0] if keep_order else min(rest, key=lambda p: self._haversine(
                (order[-1]["lat"], order[-1]["lon"]), (p["lat"], p["lon"])))
            order.append(nxt)
            rest.remove(nxt)
        legs = []
        for a, b in zip(order, order[1:]):
            leg = {"from": a["name"], "to": b["name"]}
            try:
                if not os.environ.get("TMAP_APP_KEY"):
                    raise RuntimeError("no TMAP key")
                leg.update(self._tmap_leg(a, b))
            except Exception as e:  # noqa: BLE001  fall back to a straight-line walking estimate
                m = self._haversine((a["lat"], a["lon"]), (b["lat"], b["lon"])) * 1.3
                leg.update({"meters": int(m), "minutes": max(1, round(m / 70)), "method": "직선거리×1.3 추정 (도보 70m/분)",
                            **({"tmap_error": type(e).__name__} if os.environ.get("TMAP_APP_KEY") else {})})
            legs.append(leg)
        return {"status": "ok", "order": [p["name"] for p in order], "legs": legs,
                "total_walk_minutes": sum(l["minutes"] for l in legs), "missing_coords": missing,
                "caveats": ["도보 기준. 계단·경사·공사 등 당일 상황과 운영시간 순서는 별도로 확인",
                            *(["좌표 미확인 장소는 동선에서 제외: " + ", ".join(missing)] if missing else [])]}
