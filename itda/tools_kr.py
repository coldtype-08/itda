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
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

TMAP_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1"
TMAP_CAR = "https://apis.openapi.sk.com/tmap/routes?version=1"
TMAP_TRANSIT = "https://apis.openapi.sk.com/transit/routes"
TMAP_POI = "https://apis.openapi.sk.com/tmap/pois?version=1&count=8&resCoordType=WGS84GEO&searchKeyword="
_AUX = ("주차장", "주유소", "정류장", "정류소", "출구", "입구역", "화장실", "매표소", "충전소", "ATM", "편의점")


def _pick_poi(pois: list[dict], query: str) -> dict:
    """Prefer the place itself over its parking lot / bus stop / exit: exact name, then a name that
    starts with the query, skipping auxiliary facilities; fall back to the first hit."""
    q = query.replace(" ", "")
    main = [p for p in pois if not any(a in (p.get("name") or "") for a in _AUX)] or pois
    for cond in (lambda n: n == q, lambda n: n.startswith(q), lambda n: q in n):
        hit = next((p for p in main if cond((p.get("name") or "").replace(" ", ""))), None)
        if hit:
            return hit
    return main[0]


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
        if (self._kapi and _public_key()) or os.environ.get("TMAP_APP_KEY") or os.environ.get("NAVER_CLIENT_ID"):
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
        """TMAP POI search first (no data.go.kr approval needed), then the KTO registry, then Naver local."""
        if os.environ.get("TMAP_APP_KEY"):
            try:
                req = urllib.request.Request(TMAP_POI + urllib.parse.quote(place),
                                             headers={"appKey": os.environ["TMAP_APP_KEY"], "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    poi = _pick_poi(json.loads(r.read() or b"{}")["searchPoiInfo"]["pois"]["poi"], place)
                lat = float(poi.get("frontLat") or poi.get("noorLat"))
                lon = float(poi.get("frontLon") or poi.get("noorLon"))
                return lat, lon, f"TMAP POI '{poi.get('name')}'"
            except Exception:  # noqa: BLE001
                pass
        if self._kapi and _public_key():
            try:
                return self._kapi.resolve_coords(self.client, place=place)
            except Exception:  # noqa: BLE001
                pass
        if os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET"):
            try:
                req = urllib.request.Request(
                    "https://openapi.naver.com/v1/search/local.json?display=1&query=" + urllib.parse.quote(place),
                    headers={"X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
                             "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"]})
                with urllib.request.urlopen(req, timeout=10) as r:
                    it = json.loads(r.read())["items"][0]
                return int(it["mapy"]) / 1e7, int(it["mapx"]) / 1e7, "네이버 지역검색"
            except Exception:  # noqa: BLE001
                pass
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
            feats = json.loads(r.read())["features"]
        props = feats[0]["properties"]
        path: list[list[float]] = []
        for f in feats:  # walking path geometry, [lat, lon] for the map
            g = f.get("geometry") or {}
            if g.get("type") == "LineString":
                path += [[c[1], c[0]] for c in g.get("coordinates", [])]
        step = max(1, len(path) // 200)
        return {"meters": int(props.get("totalDistance", 0)), "minutes": round(int(props.get("totalTime", 0)) / 60),
                "method": "TMAP 보행자 경로", "path": path[::step] + path[-1:]}

    @staticmethod
    def _post(url: str, body: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"appKey": os.environ["TMAP_APP_KEY"], "Accept": "application/json",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"{}")

    @staticmethod
    def _lines(feats: list[dict]) -> list[list[float]]:
        path: list[list[float]] = []
        for f in feats:
            g = f.get("geometry") or {}
            if g.get("type") == "LineString":
                path += [[c[1], c[0]] for c in g.get("coordinates", [])]
        step = max(1, len(path) // 200)
        return path[::step] + path[-1:] if path else []

    def _tmap_car(self, a: dict, b: dict) -> dict:
        d = self._post(TMAP_CAR, {"startX": str(a["lon"]), "startY": str(a["lat"]), "endX": str(b["lon"]),
                                  "endY": str(b["lat"]), "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
                                  "searchOption": "0", "trafficInfo": "Y"})
        p = d["features"][0]["properties"]
        return {"mode": "taxi", "minutes": round(int(p.get("totalTime", 0)) / 60) + 3,  # +3: hailing/drop-off
                "meters": int(p.get("totalDistance", 0)), "fare_won": int(p.get("taxiFare") or 0) or None,
                "method": "TMAP 자동차 경로 (실시간 교통 반영)", "path": self._lines(d["features"])}

    def _tmap_transit(self, a: dict, b: dict) -> dict:
        d = self._post(TMAP_TRANSIT, {"startX": str(a["lon"]), "startY": str(a["lat"]), "endX": str(b["lon"]),
                                      "endY": str(b["lat"]), "count": 1, "lang": 0, "format": "json"})
        it = d["metaData"]["plan"]["itineraries"][0]
        legs = it.get("legs", [])
        modes = [l.get("mode") for l in legs if l.get("mode") and l.get("mode") != "WALK"]
        names = [l.get("route") for l in legs if l.get("route")]
        return {"mode": "transit", "minutes": round(int(it.get("totalTime", 0)) / 60),
                "meters": int(it.get("totalDistance", 0)),
                "fare_won": int(((it.get("fare") or {}).get("regular") or {}).get("totalFare") or 0) or None,
                "walk_minutes": round(int(it.get("totalWalkTime", 0)) / 60), "transfers": int(it.get("transferCount", 0)),
                "lines": names[:4], "transit_modes": modes, "method": "TMAP 대중교통 경로"}

    def route(self, places: list[str] | str, keep_order: bool = False, max_walk_min: int = 15,
              mobility: bool = False) -> dict:
        """Visit order + per-leg transport choice: walk if short; otherwise taxi or public transport.
        mobility=True (elders, knees, wheelchair, pregnancy) lowers the walking limit and prefers taxis."""
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
        limit = min(int(max_walk_min or 15), 10) if mobility else int(max_walk_min or 15)
        has_tmap = bool(os.environ.get("TMAP_APP_KEY"))
        legs = []
        for a, b in zip(order, order[1:]):
            leg: dict = {"from": a["name"], "to": b["name"]}
            straight = self._haversine((a["lat"], a["lon"]), (b["lat"], b["lon"]))
            walk = None
            if has_tmap and straight < 4000:  # walking route only worth asking for short hops
                try:
                    walk = {"mode": "walk", **self._tmap_leg(a, b)}
                except Exception as e:  # noqa: BLE001
                    leg["tmap_error"] = type(e).__name__
            if walk is None:
                m = straight * 1.3
                walk = {"mode": "walk", "meters": int(m), "minutes": max(1, round(m / 70)),
                        "method": "직선거리×1.3 추정 (도보 70m/분)"}
            if walk["minutes"] <= limit:
                leg.update(walk)
                leg["why"] = f"도보 {walk['minutes']}분 (기준 {limit}분 이내)"
            else:
                options = []
                if has_tmap:
                    for fn in (self._tmap_car, self._tmap_transit):
                        try:
                            options.append(fn(a, b))
                        except Exception as e:  # noqa: BLE001  transit may not be subscribed
                            leg.setdefault("unavailable", []).append(f"{fn.__name__[6:]}: {type(e).__name__}")
                if not options:  # rough taxi estimate without TMAP: road ≈ 1.4× straight, 25 km/h in town
                    km = straight * 1.4 / 1000
                    options.append({"mode": "taxi", "meters": int(km * 1000), "minutes": round(km / 25 * 60) + 5,
                                    "fare_won": None, "method": "직선거리 기반 택시 추정 (요금 미확인)"})
                taxi = next((o for o in options if o["mode"] == "taxi"), None)
                transit = next((o for o in options if o["mode"] == "transit"), None)
                pick = taxi or transit
                if transit and taxi and not mobility and transit["minutes"] <= taxi["minutes"] * 1.8 \
                        and transit.get("walk_minutes", 0) <= limit:
                    pick = transit
                elif transit and not taxi:
                    pick = transit
                leg.update(pick)
                leg["why"] = (f"도보 {walk['minutes']}분은 기준({limit}분) 초과"
                              + (" · 이동 부담을 줄이려 택시 우선" if mobility and pick["mode"] == "taxi" else ""))
                leg["alternatives"] = {o["mode"]: {k: o.get(k) for k in ("minutes", "fare_won", "transfers", "lines")}
                                       for o in options if o is not pick}
                leg["alternatives"]["walk"] = {"minutes": walk["minutes"]}
            legs.append(leg)
        by_mode: dict[str, int] = {}
        for l in legs:
            by_mode[l.get("mode", "walk")] = by_mode.get(l.get("mode", "walk"), 0) + int(l.get("minutes") or 0)
        return {"status": "ok", "order": [p["name"] for p in order], "legs": legs,
                "minutes_by_mode": by_mode, "total_minutes": sum(by_mode.values()), "mobility": mobility,
                "points": [{"name": p["name"], "lat": p["lat"], "lon": p["lon"], "coord_source": p["coord_source"]} for p in order],
                "total_walk_minutes": by_mode.get("walk", 0), "missing_coords": missing,
                "caveats": ["구간별 수단은 거리와 동행자 조건으로 자동 선택. 택시비·소요시간은 예상치이며 당일 교통에 따라 다름",
                            *(["좌표 미확인 장소는 동선에서 제외: " + ", ".join(missing)] if missing else [])]}
