"""
kculture_apis.py — condition-routed wrappers for the APIs used by the K-Culture OpenShell agent:

  data.go.kr (query param serviceKey, env PUBLIC_DATA_SERVICE_KEY)
    D01 한국관광공사 국문/영문 관광정보 · D20 무장애 여행정보 · D19 TAGO 버스도착/정류소
    D21 기상청 단기예보·초단기실황 · D22 기상특보 · D29 장애인편의시설
  한국민족문화대백과사전 / AKS (header X-API-Key, env AKS_API_KEY)
    articles · articles/search · articles/{eid} · medias · medias/search · medias/{mid}

(Team module, vendored into ItDA as itda/kapi.py. ItDA's planner chooses which call_* to run;
itda/tools.py adapts ApiResult into evidence documents that go through ItDA's trust pipeline.)

Error policy
  data.go.kr call_* raise PublicDataError; execute() turns that into ApiResult(status="error").
  EKC call_* return None on ANY request error (network, 4xx/5xx, non-JSON). execute() drops
  those None results (logged). "No hits" is not an error: it is ApiResult(status="empty").

Flow
----
    user text ──(LLM, structured output)──▶ ParsedRequest
              ──plan()──▶ [PlannedCall, ...]          # "if <condition>: call_<api>(fields)"
              ──execute()──▶ [ApiResult, ...]         # normalized items + summary + caveats

Design notes
------------
* The service key comes from the env var PUBLIC_DATA_SERVICE_KEY (inject it through the
  OpenShell provider / sandbox env). It is never hard-coded and is redacted from every
  log line, error message and result object.
* Every ApiResult carries `freshness` and `caveats`, so the agent can rank it in
  output/source_triage.md (a registered DB lookup is not same-day on-site status).
* Only HTTP GET is used: https://apis.data.go.kr and https://devin.aks.ac.kr:8080
  -> two narrow egress rules in the OpenShell policy.

Dependencies: requests (pydantic>=2 optional)   Python 3.10+
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import math
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Literal
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # ItDA: stdlib fallback so the module runs in a sandbox without package registries
    import ssl as _ssl
    import types as _types
    import urllib.error as _ue
    import urllib.parse as _up
    import urllib.request as _ur

    class _RequestException(Exception):
        pass

    class _HTTPError(_RequestException):
        def __init__(self, msg: str, response: Any = None):
            super().__init__(msg)
            self.response = response

    class _Resp:
        def __init__(self, status: int, content: bytes, url: str):
            self.status_code, self.content, self.url = status, content, url

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise _HTTPError(f"{self.status_code} Error for url", response=self)

        def json(self) -> Any:
            return json.loads(self.content.decode("utf-8"))

    class _Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def mount(self, *_: Any, **__: Any) -> None:
            pass

        def get(self, url: str, params: dict | None = None, timeout: Any = None, verify: Any = True) -> _Resp:
            q = _up.urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
            full = url + ("?" + q if q else "")
            t = timeout[1] if isinstance(timeout, tuple) else timeout
            ctx = None if verify else _ssl._create_unverified_context()
            last: Exception | None = None
            for attempt in range(3):
                try:
                    with _ur.urlopen(_ur.Request(full, headers=dict(self.headers)), timeout=t, context=ctx) as r:
                        return _Resp(r.status, r.read(), full)
                except _ue.HTTPError as e:
                    if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(0.6 * (2 ** attempt))
                        continue
                    return _Resp(e.code, e.read() or b"", full)
                except (_ue.URLError, TimeoutError, OSError) as e:
                    last = e
                    time.sleep(0.6 * (2 ** attempt))
            raise _RequestException(type(last).__name__)

    requests = _types.SimpleNamespace(Session=_Session, HTTPError=_HTTPError, RequestException=_RequestException)

    class HTTPAdapter:  # no-op stand-ins; retries are handled in _Session.get
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

    class Retry:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass
try:  # pydantic is optional: a tiny shim below covers what ParsedRequest needs
    from pydantic import BaseModel, Field
    HAVE_PYDANTIC = True
except ImportError:
    HAVE_PYDANTIC = False


# -------------------------------------------------------------------------------------
# Fallback when pydantic is not installed: same constructor + coercion of LLM-style values
# ("2026-10-08" -> date, ["nearby"] -> {Intent.NEARBY}, [9, 14] -> (9, 14)).
# -------------------------------------------------------------------------------------
if not HAVE_PYDANTIC:
    import types
    import typing

    _MISSING = object()

    class _FieldInfo:
        def __init__(self, default: Any = _MISSING, default_factory: Callable | None = None):
            self.default, self.default_factory = default, default_factory

    def Field(default: Any = _MISSING, *, default_factory: Callable | None = None,  # noqa: N802
              **_: Any) -> Any:
        return _FieldInfo(default, default_factory)

    def _coerce(val: Any, tp: Any) -> Any:
        if val is None:
            return None
        origin, args = typing.get_origin(tp), typing.get_args(tp)
        if origin in (typing.Union, types.UnionType):
            inner = [a for a in args if a is not type(None)]
            return _coerce(val, inner[0]) if len(inner) == 1 else val
        if origin is typing.Literal:
            if val not in args:
                raise ValueError(f"{val!r} not in {args}")
            return val
        if origin in (set, list, tuple):
            seq = list(val) if not isinstance(val, (str, bytes)) else [val]
            if origin is tuple:
                return tuple(seq)
            conv = [_coerce(v, args[0]) for v in seq] if args else seq
            return set(conv) if origin is set else conv
        if tp is date and isinstance(val, str):
            return date.fromisoformat(val[:10])
        if isinstance(tp, type) and issubclass(tp, Enum):
            return tp(val)
        if tp in (int, float, str) and not isinstance(val, tp):
            return tp(val)
        return val

    class BaseModel:  # minimal stand-in
        def __init__(self, **data: Any):
            hints = typing.get_type_hints(type(self))
            for name, tp in hints.items():
                default = type(self).__dict__.get(name, _MISSING)
                if name in data:
                    val = data.pop(name)
                elif isinstance(default, _FieldInfo):
                    if default.default_factory is not None:
                        val = default.default_factory()
                    elif default.default is not _MISSING:
                        val = default.default
                    else:
                        raise TypeError(f"missing field: {name}")
                elif default is _MISSING:
                    raise TypeError(f"missing field: {name}")
                else:
                    val = default
                setattr(self, name, _coerce(val, tp))
            if data:
                raise TypeError(f"unknown fields: {sorted(data)}")

        def __repr__(self) -> str:
            hints = typing.get_type_hints(type(self))
            return f"{type(self).__name__}(" + ", ".join(f"{k}={getattr(self, k)!r}" for k in hints) + ")"

        @classmethod
        def model_json_schema(cls) -> dict[str, Any]:
            hints = typing.get_type_hints(cls)
            return {"title": cls.__name__, "type": "object",
                    "properties": {k: {"description": str(v)} for k, v in hints.items()}}

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger("kculture_apis")

# =====================================================================================
# 1. Service registry
# =====================================================================================


class Freshness(str, Enum):
    REGISTERED_DB = "registered_db"              # latest lookup of a registered database
    REALTIME_PREDICTION = "realtime_prediction"  # live arrival estimate
    OBSERVATION = "observation"                  # measured value (초단기실황)
    FORECAST = "forecast"                        # issued forecast (예보)
    ANNOUNCEMENT = "announcement"                # issued bulletin (특보)
    REFERENCE = "reference"                      # curated scholarly reference (encyclopedia)


@dataclass(frozen=True)
class ServiceSpec:
    source_id: str
    name: str
    base_url: str
    freshness: Freshness
    caveat: str
    format_param: tuple[str, str] | None = ("_type", "json")  # how each API asks for JSON
    base_url_verified: bool = True


SERVICES: dict[str, ServiceSpec] = {
    "kor_tour": ServiceSpec(
        "D01", "한국관광공사 국문 관광정보 (KorService2)",
        "https://apis.data.go.kr/B551011/KorService2", Freshness.REGISTERED_DB,
        "Registered tourism DB lookup; same-day hours/closures must be confirmed separately."),
    "eng_tour": ServiceSpec(
        "D01", "KTO English tourism (EngService2)",
        "https://apis.data.go.kr/B551011/EngService2", Freshness.REGISTERED_DB,
        "Registered tourism DB lookup (English).",
        base_url_verified=False),  # base URL inferred from KorService2 naming
    "barrier_free": ServiceSpec(
        "D20", "한국관광공사 무장애 여행정보 (KorWithService2)",
        "https://apis.data.go.kr/B551011/KorWithService2", Freshness.REGISTERED_DB,
        "Registered accessibility info; does NOT reflect same-day temporary ramps, rental "
        "stock, breakdowns or entrances blocked by construction."),
    "bus_arrival": ServiceSpec(
        "D19", "TAGO 버스도착정보 (ArvlInfoInqireService)",
        "https://apis.data.go.kr/1613000/ArvlInfoInqireService", Freshness.REALTIME_PREDICTION,
        "Real-time arrival estimate; temporary detours / skipped stops must be checked in "
        "operator notices."),
    "kma_fcst": ServiceSpec(
        "D21", "기상청 단기예보·초단기실황 (VilageFcstInfoService_2.0)",
        "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0", Freshness.FORECAST,
        "Latest issued forecast/observation; forecast and observation are kept separate.",
        format_param=("dataType", "JSON")),
    "kma_warning": ServiceSpec(
        "D22", "기상청 기상특보 (WthrWrnInfoService)",
        "https://apis.data.go.kr/1360000/WthrWrnInfoService", Freshness.ANNOUNCEMENT,
        "Issued warning bulletins, managed separately from forecasts. Use to hold outdoor "
        "legs or prepare indoor alternatives.",
        format_param=("dataType", "JSON")),
    "bus_stop": ServiceSpec(
        "D19-stn", "TAGO 버스정류소정보 (BusSttnInfoInqireService)",
        "https://apis.data.go.kr/1613000/BusSttnInfoInqireService", Freshness.REGISTERED_DB,
        "Registered stop list. Needs its own data.go.kr usage approval (not in the original API list)."),
    "disabled_facility": ServiceSpec(
        "D29", "한국사회보장정보원 장애인편의시설 현황",
        "https://apis.data.go.kr/B554287/DisabledPersonConvenientFacility", Freshness.REGISTERED_DB,
        "Installation/registration status, not same-day working status.",
        format_param=None),  # XML only
}
SERVICES["ekc"] = ServiceSpec(
    "EKC", "한국민족문화대백과사전 OpenAPI (한국학중앙연구원)",
    "https://devin.aks.ac.kr:8080/api", Freshness.REFERENCE,
    "Scholarly reference for general/historical context. Not current operating info, and not a "
    "source for unreviewed local claims. Cite title + eid; summarize, don't copy long passages.",
    format_param=None)
TOUR_SERVICES = {"kor_tour", "eng_tour", "barrier_free"}

# content kind -> (KorService2 contentTypeId, EngService2 contentTypeId)
CONTENT_TYPES: dict[str, tuple[str | None, str | None]] = {
    "attraction": ("12", "76"), "culture": ("14", "78"), "festival": ("15", "85"),
    "course": ("25", None), "leisure": ("28", "75"), "lodging": ("32", "80"),
    "shopping": ("38", "79"), "food": ("39", "82"), "transport": (None, "77"),
}
ContentKind = Literal["attraction", "culture", "festival", "course", "leisure",
                      "lodging", "shopping", "food", "transport"]

# Legacy TourAPI areaCode. KorService2 also accepts 법정동 codes (lDongRegnCd); pass those via
# `extra` if your key/version requires them.
AREA_CODES = {"서울": "1", "인천": "2", "대전": "3", "대구": "4", "광주": "5", "부산": "6",
              "울산": "7", "세종": "8", "경기": "31", "강원": "32", "충북": "33", "충남": "34",
              "경북": "35", "경남": "36", "전북": "37", "전남": "38", "제주": "39"}

# 기상특보 issuing office (stnId). 108 = nationwide. Verify against the D22 spec table.
WARNING_STN_IDS = {"서울": 109, "인천": 109, "경기": 109, "강원": 105, "충북": 131,
                   "대전": 133, "세종": 133, "충남": 133, "전북": 146, "광주": 156,
                   "전남": 156, "대구": 143, "경북": 143, "부산": 159, "울산": 159,
                   "경남": 159, "제주": 184}
NATIONWIDE_STN = 108

_SIDO_LONG = {"경상남": "경남", "경상북": "경북", "전라남": "전남", "전라북": "전북",
              "충청남": "충남", "충청북": "충북"}
_SIDO_EN = {"seoul": "서울", "busan": "부산", "incheon": "인천", "daegu": "대구",
            "daejeon": "대전", "gwangju": "광주", "ulsan": "울산", "sejong": "세종",
            "gyeonggi": "경기", "gangwon": "강원", "jeju": "제주"}


def sido_key(sido: str | None) -> str | None:
    """'서울특별시' / 'Seoul' / '경상남도' -> '서울' / '서울' / '경남'."""
    if not sido:
        return None
    s = sido.strip()
    for en, ko in _SIDO_EN.items():
        if s.lower().startswith(en):
            return ko
    for long, short in _SIDO_LONG.items():
        if s.startswith(long):
            return short
    return s[:2]


# =====================================================================================
# 2. Result type, errors, redaction
# =====================================================================================

Status = Literal["ok", "empty", "skipped", "error"]


@dataclass
class ApiResult:
    service: str
    operation: str
    status: Status
    reason: str = ""                                  # why the planner made this call (audit)
    items: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    total_count: int | None = None
    source_id: str = ""
    freshness: str = ""
    caveats: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)   # never contains the key
    fetched_at: str = field(
        default_factory=lambda: datetime.now(KST).isoformat(timespec="seconds"))
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "empty")

    def triage_row(self) -> dict[str, str]:
        """One row for output/source_triage.md."""
        return {"source": f"API {self.service}.{self.operation}", "id": self.source_id,
                "fetched_at": self.fetched_at, "freshness": self.freshness,
                "status": self.status, "items": str(len(self.items)),
                "why": self.reason, "caveats": " / ".join(self.caveats) or "-"}


def _base_result(service: str, operation: str, status: Status, **kw: Any) -> ApiResult:
    spec = SERVICES[service]
    caveats = [spec.caveat, *kw.pop("caveats", [])]
    if not spec.base_url_verified:
        caveats.append("UNVERIFIED base URL: confirm on the data.go.kr spec page")
    freshness = kw.pop("freshness", spec.freshness)
    return ApiResult(service, operation, status, source_id=spec.source_id,
                     freshness=Freshness(freshness).value, caveats=caveats, **kw)


def _result(service: str, operation: str, items: list[dict], **kw: Any) -> ApiResult:
    return _base_result(service, operation, "ok" if items else "empty", items=items, **kw)


class PublicDataError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


_KEY_RE = re.compile(r"(serviceKey=)[^&\s'\"]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _KEY_RE.sub(r"\1***", text)


# =====================================================================================
# 3. Response parsing (JSON or XML; data.go.kr gateway errors are always XML)
# =====================================================================================

_OK_CODES = {"", "0", "00", "0000", "INFO-000"}
_NODATA_CODES = {"03", "NODATA_ERROR"}


def _has_data(code: str, msg: str) -> bool:
    code = (code or "").strip()
    if code in _OK_CODES:
        return True
    if code in _NODATA_CODES:
        return False
    raise PublicDataError(code, msg or "unknown error")


def _to_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_response(text: str) -> tuple[list[dict[str, Any]], int | None]:
    body = text.lstrip("﻿").strip()
    if body.startswith("{"):
        data = json.loads(body)
        resp = data.get("response", data)
        header = resp.get("header") or {}
        if not _has_data(str(header.get("resultCode", "")), header.get("resultMsg", "")):
            return [], 0
        b = resp.get("body") or {}
        items = b.get("items")
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):          # single result comes back as an object
            items = [items]
        if not isinstance(items, list):      # "" when empty
            items = []
        return items, _to_int(b.get("totalCount"))

    root = ET.fromstring(body)
    if root.tag == "OpenAPI_ServiceResponse":   # gateway error: bad key, quota, unregistered...
        h = root.find("cmmMsgHeader")
        h = h if h is not None else root
        raise PublicDataError(h.findtext("returnReasonCode") or "?",
                              h.findtext("returnAuthMsg") or h.findtext("errMsg") or "?")
    if not _has_data(root.findtext(".//resultCode") or "", root.findtext(".//resultMsg") or ""):
        return [], 0
    nodes = root.findall(".//item") or root.findall(".//servList")
    items = [{c.tag: (c.text or "").strip() for c in n} for n in nodes]
    return items, _to_int(root.findtext(".//totalCount"))


# =====================================================================================
# 4. HTTP client (retry, timeout, TTL cache, key redaction)
# =====================================================================================


class PublicDataClient:
    def __init__(self, service_key: str | None = None, *, mobile_app: str = "KCultureAgent",
                 timeout: tuple[float, float] = (3.05, 12.0), retries: int = 3,
                 cache_ttl_s: float = 120.0):
        key = service_key or os.environ.get("PUBLIC_DATA_SERVICE_KEY", "")
        if not key:
            raise RuntimeError("PUBLIC_DATA_SERVICE_KEY is not set")
        # The portal issues an 'Encoding' and a 'Decoding' key. requests URL-encodes params,
        # so always send the decoded form (avoids SERVICE_KEY_IS_NOT_REGISTERED_ERROR).
        self._key = unquote(key)
        self.mobile_app = mobile_app
        self.timeout = timeout
        self._ttl = cache_ttl_s
        self._cache: dict[tuple, tuple[float, tuple[list, int | None]]] = {}
        self._inflight: dict[tuple, threading.Lock] = {}   # single-flight: one HTTP call per key
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=retries, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}), raise_on_status=False)))

    def call(self, service: str, operation: str, params: dict[str, Any], *,
             num_rows: int = 10, page: int = 1) -> tuple[list[dict], int | None]:
        spec = SERVICES[service]
        q = {k: v for k, v in params.items() if v not in (None, "")}
        q.setdefault("numOfRows", num_rows)
        q.setdefault("pageNo", page)
        if spec.format_param:
            q.setdefault(*spec.format_param)
        if service in TOUR_SERVICES:
            q.setdefault("MobileOS", "ETC")
            q.setdefault("MobileApp", self.mobile_app)

        ck = (service, operation, tuple(sorted((k, str(v)) for k, v in q.items())))
        with self._lock:
            key_lock = self._inflight.setdefault(ck, threading.Lock())
        with key_lock:   # parallel callers with the same query wait for the first one
            with self._lock:
                hit = self._cache.get(ck)
                if hit and time.monotonic() - hit[0] < self._ttl:
                    return hit[1]
            try:
                r = self._session.get(f"{spec.base_url}/{operation}",
                                      params={"serviceKey": self._key, **q}, timeout=self.timeout)
                r.raise_for_status()
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (401, 403):
                    raise PublicDataError(str(code), f"key not approved for {spec.name} "
                                          "(apply on data.go.kr; activation can take ~1-2 h)") from None
                raise PublicDataError(f"HTTP{code}", redact(str(e))) from None
            except requests.RequestException as e:
                raise PublicDataError("HTTP", redact(str(e))) from None   # drop URL-with-key chain
            out = parse_response(r.content.decode("utf-8", errors="replace"))
            with self._lock:
                self._cache[ck] = (time.monotonic(), out)
        log.info("GET %s.%s %s -> %d items", service, operation, q, len(out[0]))
        return out

    def call_all(self, service: str, operation: str, params: dict[str, Any], *,
                 page_size: int = 1000, max_pages: int = 3) -> tuple[list[dict], int | None]:
        items, total = self.call(service, operation, params, num_rows=page_size, page=1)
        items, page = list(items), 1
        while total and len(items) < total and page < max_pages:
            page += 1
            more, _ = self.call(service, operation, params, num_rows=page_size, page=page)
            if not more:
                break
            items.extend(more)
        return items, total


# =====================================================================================
# 4b. 한국민족문화대백과사전 (EKC) client — header auth (X-API-Key), JSON
# =====================================================================================


class EkcClient:
    """Encyclopedia of Korean Culture OpenAPI (AKS).

    Endpoints (all GET, header X-API-Key):
      /articles?p&ps · /articles/search?q&p&ps · /articles/{eid}
      /medias?p&ps   · /medias/search?q&p&ps   · /medias/{mid}
    """
    DEFAULT_BASE = "https://devin.aks.ac.kr:8080/api"

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None,
                 timeout: tuple[float, float] = (3.05, 15.0), retries: int = 2,
                 cache_ttl_s: float = 600.0, verify: bool | str = True):
        key = api_key or os.environ.get("AKS_API_KEY", "")
        if not key:
            raise RuntimeError("AKS_API_KEY is not set")
        self.base_url = (base_url or os.environ.get("AKS_API_BASE") or self.DEFAULT_BASE).rstrip("/")
        self.timeout, self.verify, self._ttl = timeout, verify, cache_ttl_s
        self._session = requests.Session()
        # The key travels in a header (never in the URL), so it can't leak through error URLs.
        self._session.headers.update({"X-API-Key": key, "Accept": "application/json"})
        self._session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=retries, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}), raise_on_status=False)))
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._inflight: dict[tuple, threading.Lock] = {}
        self._lock = threading.Lock()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        q = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        ck = (path, tuple(sorted((k, str(v)) for k, v in q.items())))
        with self._lock:
            key_lock = self._inflight.setdefault(ck, threading.Lock())
        with key_lock:
            with self._lock:
                hit = self._cache.get(ck)
                if hit and time.monotonic() - hit[0] < self._ttl:
                    return hit[1]
            try:
                r = self._session.get(self.base_url + path, params=q, timeout=self.timeout,
                                      verify=self.verify)
                r.raise_for_status()
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (401, 403):
                    raise PublicDataError(str(code), "AKS rejected the X-API-Key (check AKS_API_KEY)") from None
                if code == 404:
                    raise PublicDataError("404", f"EKC: not found {path}") from None
                raise PublicDataError(f"HTTP{code}", f"EKC {path}: {e}") from None
            except requests.RequestException as e:
                raise PublicDataError("HTTP", f"EKC {path}: {type(e).__name__}: {e}") from None
            try:
                data = r.json()
            except ValueError:
                raise PublicDataError("FORMAT", f"EKC {path}: non-JSON response: "
                                      f"{r.content[:200].decode('utf-8', 'replace')}") from None
            with self._lock:
                self._cache[ck] = (time.monotonic(), data)
        log.info("GET ekc%s %s", path, q)
        return data


# ---- tolerant JSON helpers (exact EKC field names are not documented) ---------------------
_LIST_KEYS = ("articles", "medias", "items", "list", "content", "data", "results", "result",
              "rows", "docs", "records")
_TOTAL_KEYS = ("total", "totalCount", "totalElements", "total_count", "totalItems", "count", "totalHits")
_ONE_KEYS = ("article", "media", "data", "result", "item")


def _find_list(obj: Any, depth: int = 0) -> list[dict]:
    """First list of dicts in a JSON payload (preferring well-known container keys)."""
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict) and depth < 4:
        for k in _LIST_KEYS:
            if k in obj and isinstance(obj[k], (list, dict)):
                found = _find_list(obj[k], depth + 1)
                if found or isinstance(obj[k], list):
                    return found
        for v in obj.values():
            if isinstance(v, (list, dict)):
                found = _find_list(v, depth + 1)
                if found:
                    return found
    return []


def _find_total(obj: Any, depth: int = 0) -> int | None:
    if isinstance(obj, dict) and depth < 3:
        for k in _TOTAL_KEYS:
            v = obj.get(k)
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                return int(v)
        for v in obj.values():
            if isinstance(v, dict):
                t = _find_total(v, depth + 1)
                if t is not None:
                    return t
    return None


def _unwrap_one(obj: Any) -> dict:
    if isinstance(obj, dict):
        for k in _ONE_KEYS:
            if isinstance(obj.get(k), dict):
                return _unwrap_one(obj[k])
        return obj
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj[0]
    return {}


def _pick(d: dict, *keys: str) -> Any:
    """First non-empty value among candidate keys (case-insensitive)."""
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = d.get(k, low.get(k.lower()))
        if v not in (None, "", [], {}):
            return v
    return None


_WS_RE = re.compile(r"\s+")


def _clean(v: Any) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False)
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", v))).strip()


_TITLE_KEYS = ("title", "headword", "name", "subject", "articleTitle", "mediaTitle", "caption")
_SUMMARY_KEYS = ("summary", "definition", "abstract", "description", "desc", "intro")
_BODY_KEYS = ("body", "content", "contents", "text", "html", "articleBody", "fullText")
_META_KEYS = ("field", "category", "type", "era", "period", "region", "classification",
              "genre", "author", "writer", "updated", "updatedAt", "modified", "date")
_MEDIA_URL_KEYS = ("url", "imageUrl", "image", "thumbnail", "thumbnailUrl", "fileUrl", "src", "path")


def _ekc_row(it: dict, id_key: str) -> dict:
    row = {id_key: _pick(it, id_key, "id", f"{id_key}s"),
           "title": _clean(_pick(it, *_TITLE_KEYS)),
           "summary": _clean(_pick(it, *_SUMMARY_KEYS))[:300]}
    if id_key == "mid":
        row["url"] = _pick(it, *_MEDIA_URL_KEYS)
        row["eid"] = _pick(it, "eid", "articleId")
    row.update({k: it[k] for k in _META_KEYS if it.get(k) not in (None, "", [], {})})
    return {k: v for k, v in row.items() if v not in (None, "")}


# =====================================================================================
# 5. call_* wrappers — data.go.kr ones raise (execute() catches); EKC ones return None on error.
# =====================================================================================

TOUR_KEEP = ("contentid", "contenttypeid", "title", "addr1", "addr2", "areacode",
             "sigungucode", "mapx", "mapy", "tel", "modifiedtime", "firstimage")
DETAIL_KEEP = ("contentid", "contenttypeid", "title", "homepage", "tel", "addr1",
               "mapx", "mapy", "overview", "modifiedtime")
_HOURS_RE = re.compile(r"usetime|opentime|restdate|playtime|eventstartdate|eventenddate|infocenter")
_TAG_RE = re.compile(r"<[^>]+>")


def _tour_service(lang: str) -> str:
    return "eng_tour" if lang == "en" else "kor_tour"


def _content_type_id(kind: str | None, lang: str) -> str | None:
    if not kind:
        return None
    ko, en = CONTENT_TYPES[kind]
    return en if lang == "en" else ko


def _slim(item: dict, keep: tuple[str, ...]) -> dict:
    return {k: item[k] for k in keep if item.get(k) not in (None, "")}


def _stale_caveats(items: list[dict], max_age_days: int = 365) -> list[str]:
    today = datetime.now(KST).date()
    old = []
    for i in items:
        m = i.get("modifiedtime", "")
        try:
            if (today - datetime.strptime(m[:8], "%Y%m%d").date()).days > max_age_days:
                old.append(i.get("title", i.get("contentid", "?")))
        except ValueError:
            continue
    return [f"Registry entry not updated in >{max_age_days} days: {', '.join(old[:5])}"] if old else []


def search_place(client: PublicDataClient, service: str, keyword: str, *,
                 area_code: str | None = None, n: int = 5,
                 extra: dict | None = None) -> tuple[list[dict], int | None, str]:
    """searchKeyword2 that retries without spaces ('해담 옛시장' -> '해담옛시장').
    Returns (items, totalCount, keyword_actually_used)."""
    tried = [keyword] + ([keyword.replace(" ", "")] if " " in keyword else [])
    for kw in tried:
        items, total = client.call(service, "searchKeyword2",
                                   {"keyword": kw, "areaCode": area_code, **(extra or {})}, num_rows=n)
        if items:
            return items, total, kw
    return [], 0, keyword


def call_tour_search(client: PublicDataClient, keyword: str, *, lang: str = "ko",
                     area_code: str | None = None, content_kind: str | None = None,
                     n: int = 10, extra: dict | None = None) -> ApiResult:
    """KorService2/EngService2 searchKeyword2: find places by name."""
    svc = _tour_service(lang)
    extra = {"contentTypeId": _content_type_id(content_kind, lang), **(extra or {})}
    items, total, used = search_place(client, svc, keyword, area_code=area_code, n=n, extra=extra)
    params = {"keyword": used, "areaCode": area_code, **extra}
    items = [_slim(i, TOUR_KEEP) for i in items]
    return _result(svc, "searchKeyword2", items, total_count=total, params=params,
                   caveats=_stale_caveats(items))


def call_tour_area_list(client: PublicDataClient, *, area_code: str, content_kind: str,
                        lang: str = "ko", sigungu_code: str | None = None, n: int = 20,
                        extra: dict | None = None) -> ApiResult:
    """areaBasedList2: 'restaurants in Jeonju'-style requests without a place name."""
    svc = _tour_service(lang)
    params = {"areaCode": area_code, "sigunguCode": sigungu_code,
              "contentTypeId": _content_type_id(content_kind, lang), "arrange": "C",
              **(extra or {})}
    items, total = client.call(svc, "areaBasedList2", params, num_rows=n)
    items = [_slim(i, TOUR_KEEP) for i in items]
    return _result(svc, "areaBasedList2", items, total_count=total, params=params,
                   caveats=_stale_caveats(items))


def call_tour_place_profile(client: PublicDataClient, *, content_id: str | None = None,
                            keyword: str | None = None, lang: str = "ko",
                            area_code: str | None = None) -> ApiResult:
    """detailCommon2 + detailIntro2 (resolves contentId via searchKeyword2 if needed)."""
    svc, caveats = _tour_service(lang), []
    content_type_id = None
    if not content_id:
        hits, _, _ = search_place(client, svc, keyword, area_code=area_code)
        if not hits:
            return _result(svc, "detailCommon2", [], params={"keyword": keyword},
                           caveats=[f"No registered entry for '{keyword}'. Do not invent details."])
        content_id, content_type_id = hits[0]["contentid"], hits[0].get("contenttypeid")
        if len(hits) > 1:
            caveats.append("Top search hit used; other candidates: "
                           + ", ".join(h.get("title", "?") for h in hits[1:]))

    common, _ = client.call(svc, "detailCommon2", {"contentId": content_id})
    if not common:
        return _result(svc, "detailCommon2", [], params={"contentId": content_id}, caveats=caveats)
    content_type_id = content_type_id or common[0].get("contenttypeid")
    intro, _ = client.call(svc, "detailIntro2",
                           {"contentId": content_id, "contentTypeId": content_type_id})

    profile = _slim(common[0], DETAIL_KEEP)
    if "overview" in profile:
        profile["overview"] = _TAG_RE.sub("", profile["overview"])[:800]
    if "homepage" in profile:
        m = re.search(r"https?://[^\s\"'<>]+", profile["homepage"])
        profile["homepage"] = m.group(0) if m else _TAG_RE.sub("", profile["homepage"]).strip()
    intro0 = {k: _TAG_RE.sub(" ", v).strip() for k, v in (intro[0] if intro else {}).items() if v}
    hours = {k: v for k, v in intro0.items() if _HOURS_RE.search(k)}
    profile["intro"] = intro0
    caveats.append("Registered hours only: a newer official notice for the visit date overrides them.")
    caveats += _stale_caveats([profile])
    return _result(svc, "detailCommon2+detailIntro2", [profile],
                   params={"contentId": content_id, "contentTypeId": content_type_id},
                   summary={"title": profile.get("title"), "registered_hours": hours,
                            "modifiedtime": profile.get("modifiedtime")},
                   caveats=caveats)


def call_festivals(client: PublicDataClient, start: date, end: date | None = None, *,
                   lang: str = "ko", area_code: str | None = None,
                   place: str | None = None) -> ApiResult:
    """searchFestival2, filtered client-side to events overlapping [start, end].
    With no area_code, the area of `place` is used (avoids a nationwide list)."""
    svc = _tour_service(lang)
    if not area_code and place:
        area_code = place_region(client, place)[1]
    s, e = start.strftime("%Y%m%d"), (end or start).strftime("%Y%m%d")
    params = {"eventStartDate": s, "areaCode": area_code}
    items, total = client.call_all(svc, "searchFestival2", params, page_size=100, max_pages=3)
    keep = [_slim(i, TOUR_KEEP + ("eventstartdate", "eventenddate")) for i in items
            if i.get("eventstartdate", "0") <= e and i.get("eventenddate", "99999999") >= s]
    return _result(svc, "searchFestival2", keep, total_count=total, params={**params, "window": [s, e]},
                   caveats=["Event dates as registered; check organizer notices for cancellations."])


def call_barrier_free(client: PublicDataClient, *, content_id: str | None = None,
                      keyword: str | None = None, area_code: str | None = None) -> ApiResult:
    """KorWithService2 detailWithTour2 (Korean names only)."""
    caveats = []
    if not content_id:
        hits, _, _ = search_place(client, "barrier_free", keyword, area_code=area_code)
        if not hits:
            return _result("barrier_free", "detailWithTour2", [], params={"keyword": keyword},
                           caveats=[f"No barrier-free record for '{keyword}'. Treat accessibility as unknown."])
        content_id = hits[0]["contentid"]
        keyword = hits[0].get("title", keyword)
    items, _ = client.call("barrier_free", "detailWithTour2", {"contentId": content_id})
    features = {k: v for k, v in (items[0] if items else {}).items() if v and k != "contentid"}
    return _result("barrier_free", "detailWithTour2", [features] if features else [],
                   params={"contentId": content_id},
                   summary={"title": keyword, "registered_features": features,
                            "confirm_on_site": ["temporary ramp today", "wheelchair rental stock",
                                                "lift/elevator working",
                                                "entrance closed by construction"]},
                   caveats=caveats)


def resolve_coords(client: PublicDataClient, *, lat: float | None = None, lon: float | None = None,
                   place: str | None = None, area_code: str | None = None) -> tuple[float, float, str]:
    """(lat, lon) as given, else geocode `place` via KorService2 (mapy = lat, mapx = lon)."""
    if lat is not None and lon is not None:
        return float(lat), float(lon), "given lat/lon"
    if not place:
        raise ValueError("need lat/lon or a place name")
    hits, _, _ = search_place(client, "kor_tour", place, area_code=area_code)
    if not hits or not hits[0].get("mapy"):
        raise ValueError(f"could not geocode '{place}' via KorService2 (not in the registry?)")
    return float(hits[0]["mapy"]), float(hits[0]["mapx"]), f"coords of '{hits[0].get('title')}' (KorService2)"


def place_region(client: PublicDataClient, place: str, area_code: str | None = None
                 ) -> tuple[str | None, str | None]:
    """(sido, areaCode) of a registered place, from its addr1 / areacode. (None, None) if unknown."""
    hits, _, _ = search_place(client, "kor_tour", place, area_code=area_code)
    if not hits:
        return None, None
    addr = (hits[0].get("addr1") or "").split()
    return (sido_key(addr[0]) if addr else None), (hits[0].get("areacode") or None)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def call_tour_nearby(client: PublicDataClient, *, radius_m: int = 3000, content_kind: str | None = None,
                     lang: str = "ko", n: int = 20, exclude_content_id: str | None = None,
                     **loc: Any) -> ApiResult:
    """locationBasedList2: registered places within radius_m of a point ('가볼 수 있는 곳')."""
    lat, lon, src = resolve_coords(client, **loc)
    svc = _tour_service(lang)
    params = {"mapX": lon, "mapY": lat, "radius": min(int(radius_m), 20000),
              "contentTypeId": _content_type_id(content_kind, lang), "arrange": "E"}  # E = by distance
    items, total = client.call(svc, "locationBasedList2", params, num_rows=n)
    items = [_slim(i, TOUR_KEEP + ("dist",)) for i in items
             if not exclude_content_id or i.get("contentid") != exclude_content_id]
    return _result(svc, "locationBasedList2", items, total_count=total, params=params,
                   summary={"center_source": src, "kind": content_kind, "count": len(items)},
                   caveats=_stale_caveats(items) + ["Registered places only; check same-day hours."])


def call_bus_stops_nearby(client: PublicDataClient, *, n: int = 10, **loc: Any) -> ApiResult:
    """BusSttnInfoInqireService/getCrdntPrxmtSttnList: stops near a point -> cityCode + nodeId."""
    lat, lon, src = resolve_coords(client, **loc)
    params = {"gpsLati": lat, "gpsLong": lon}
    items, total = client.call("bus_stop", "getCrdntPrxmtSttnList", params, num_rows=n)
    rows = []
    for i in items:
        row = {"citycode": str(i.get("citycode", "")), "nodeid": i.get("nodeid"),
               "nodenm": i.get("nodenm"), "nodeno": i.get("nodeno")}
        try:
            row["dist_m"] = _haversine_m(lat, lon, float(i["gpslati"]), float(i["gpslong"]))
        except (KeyError, TypeError, ValueError):
            row["dist_m"] = None
        rows.append(row)
    rows.sort(key=lambda r: (r["dist_m"] is None, r["dist_m"]))
    return _result("bus_stop", "getCrdntPrxmtSttnList", rows, total_count=total, params=params,
                   summary={"center_source": src},
                   caveats=["TAGO may not cover every city (check getCtyCodeList)."])


def call_bus_near_place(client: PublicDataClient, *, max_stops: int = 2,
                        route_no: str | None = None, **loc: Any) -> ApiResult:
    """Nearest stops -> live arrivals for each (today only)."""
    stops = call_bus_stops_nearby(client, **loc)
    out = []
    for s in stops.items[:max_stops]:
        arr = call_bus_arrivals(client, city_code=s["citycode"], node_id=s["nodeid"], route_no=route_no)
        out.append({**s, "arrivals": arr.items})
    return _result("bus_arrival", "getCrdntPrxmtSttnList+getSttnAcctoArvlPrearngeInfoList", out,
                   params=stops.params, summary=stops.summary,
                   caveats=stops.caveats[1:] + [SERVICES["bus_stop"].caveat])


def call_bus_city_codes(client: PublicDataClient) -> ApiResult:
    items, total = client.call("bus_arrival", "getCtyCodeList", {}, num_rows=300)
    return _result("bus_arrival", "getCtyCodeList", items, total_count=total, params={})


def call_bus_arrivals(client: PublicDataClient, *, city_code: str, node_id: str,
                      route_no: str | None = None) -> ApiResult:
    params = {"cityCode": city_code, "nodeId": node_id}
    items, total = client.call("bus_arrival", "getSttnAcctoArvlPrearngeInfoList", params, num_rows=50)
    rows = [{"route": str(i.get("routeno", "")), "stop": i.get("nodenm"),
             "arrive_min": round(int(i["arrtime"]) / 60) if str(i.get("arrtime", "")).isdigit() else None,
             "stops_left": i.get("arrprevstationcnt"), "vehicle": i.get("vehicletp")} for i in items]
    if route_no:
        rows = [r for r in rows if r["route"] == str(route_no)]
    rows.sort(key=lambda r: (r["arrive_min"] is None, r["arrive_min"]))
    return _result("bus_arrival", "getSttnAcctoArvlPrearngeInfoList", rows,
                   total_count=total, params=params)


# ---- weather ---------------------------------------------------------------------------

def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """KMA DFS Lambert-conformal-conic conversion (5 km grid) -> (nx, ny)."""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    d = math.pi / 180.0
    re_ = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi / 4 + slat2 / 2) / math.tan(math.pi / 4 + slat1 / 2))
    sf = math.tan(math.pi / 4 + slat1 / 2) ** sn * math.cos(slat1) / sn
    ro = re_ * sf / math.tan(math.pi / 4 + olat / 2) ** sn
    ra = re_ * sf / math.tan(math.pi / 4 + lat * d / 2) ** sn
    theta = lon * d - olon
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return (int(math.floor(ra * math.sin(theta) + XO + 0.5)),
            int(math.floor(ro - ra * math.cos(theta) + YO + 0.5)))


def ultra_ncst_base(now: datetime) -> tuple[str, str]:
    """초단기실황: hourly HH00, conservatively available from ~HH:40."""
    t = now - timedelta(minutes=40)
    return t.strftime("%Y%m%d"), t.strftime("%H00")


def ultra_fcst_base(now: datetime) -> tuple[str, str]:
    """초단기예보: HH30 issue, available from ~HH:45."""
    t = now - timedelta(minutes=45)
    return t.strftime("%Y%m%d"), t.strftime("%H30")


_VILAGE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)


def vilage_base(now: datetime) -> tuple[str, str]:
    """단기예보: issued 02/05/.../23h, available ~10 min later."""
    t = now - timedelta(minutes=10)
    for h in reversed(_VILAGE_HOURS):
        if t.hour >= h:
            return t.strftime("%Y%m%d"), f"{h:02d}00"
    return (t - timedelta(days=1)).strftime("%Y%m%d"), "2300"


PTY = {"0": "none", "1": "rain", "2": "rain/snow", "3": "snow", "4": "shower",
       "5": "drizzle", "6": "drizzle/snow flurry", "7": "snow flurry"}
SKY = {"1": "clear", "3": "mostly cloudy", "4": "overcast"}


def resolve_grid(client: PublicDataClient, *, nx: int | None = None, ny: int | None = None,
                 **loc: Any) -> tuple[int, int, str]:
    """Grid from (nx, ny), else from lat/lon or a place name. Never put raw lat/lon into nx/ny."""
    if nx is not None and ny is not None:
        return nx, ny, "given grid"
    lat, lon, src = resolve_coords(client, **loc)
    gx, gy = latlon_to_grid(lat, lon)
    return gx, gy, src


def call_weather_now(client: PublicDataClient, *, now: datetime | None = None, **loc: Any) -> ApiResult:
    now = now or datetime.now(KST)
    nx, ny, src = resolve_grid(client, **loc)
    bd, bt = ultra_ncst_base(now)
    params = {"base_date": bd, "base_time": bt, "nx": nx, "ny": ny}
    items, _ = client.call("kma_fcst", "getUltraSrtNcst", params, num_rows=20)
    obs = {i["category"]: i.get("obsrValue") for i in items}
    return _result("kma_fcst", "getUltraSrtNcst", items, params=params, freshness=Freshness.OBSERVATION,
                   summary={"observed_at": f"{bd} {bt}", "grid_source": src, "temp_c": obs.get("T1H"),
                            "rain_1h_mm": obs.get("RN1"), "precip": PTY.get(str(obs.get("PTY"))),
                            "humidity_pct": obs.get("REH"), "wind_ms": obs.get("WSD")})


def _pivot(rows: list[dict]) -> dict[tuple[str, str], dict[str, str]]:
    slots: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for r in rows:
        slots[(r["fcstDate"], r["fcstTime"])][r["category"]] = r.get("fcstValue")
    return dict(sorted(slots.items()))


def call_weather_ultra_short(client: PublicDataClient, *, now: datetime | None = None,
                             **loc: Any) -> ApiResult:
    now = now or datetime.now(KST)
    nx, ny, src = resolve_grid(client, **loc)
    bd, bt = ultra_fcst_base(now)
    params = {"base_date": bd, "base_time": bt, "nx": nx, "ny": ny}
    items, _ = client.call("kma_fcst", "getUltraSrtFcst", params, num_rows=60)
    next_hours = [{"at": f"{d} {t}", "temp_c": v.get("T1H"), "sky": SKY.get(v.get("SKY", "")),
                   "precip": PTY.get(v.get("PTY", "")), "rain_mm": v.get("RN1")}
                  for (d, t), v in _pivot(items).items()]
    return _result("kma_fcst", "getUltraSrtFcst", items, params=params,
                   summary={"issued": f"{bd} {bt}", "grid_source": src, "next_hours": next_hours})


def summarize_forecast(rows: list[dict], hours: tuple[int, int] | None = None) -> dict[str, Any]:
    """Collapse one day of getVilageFcst rows into an outdoor-planning summary."""
    slots = {t: v for (_, t), v in _pivot(rows).items()}
    window = {t: v for t, v in slots.items() if hours is None or hours[0] <= int(t[:2]) < hours[1]}
    pops = [int(v["POP"]) for v in window.values() if str(v.get("POP", "")).isdigit()]
    temps = [float(v["TMP"]) for v in window.values() if v.get("TMP")]
    wet = [t for t, v in window.items() if v.get("PTY", "0") != "0"]
    sky = Counter(SKY.get(v.get("SKY", ""), "?") for v in window.values()).most_common(1)
    pop_max = max(pops) if pops else None
    risk = ("high" if wet or (pop_max or 0) >= 60 else "medium" if (pop_max or 0) >= 30 else "low")
    return {"window_h": hours, "pop_max_pct": pop_max,
            "temp_range_c": [min(temps), max(temps)] if temps else None,
            "tmn": next((v["TMN"] for v in slots.values() if "TMN" in v), None),
            "tmx": next((v["TMX"] for v in slots.values() if "TMX" in v), None),
            "wet_slots": wet, "sky": sky[0][0] if sky else None, "outdoor_risk": risk}


def call_weather_forecast(client: PublicDataClient, target: date, *,
                          hours: tuple[int, int] | None = None, now: datetime | None = None,
                          **loc: Any) -> ApiResult:
    now = now or datetime.now(KST)
    nx, ny, src = resolve_grid(client, **loc)
    bd, bt = vilage_base(now)
    params = {"base_date": bd, "base_time": bt, "nx": nx, "ny": ny}
    items, _ = client.call_all("kma_fcst", "getVilageFcst", params, page_size=1000, max_pages=2)
    day = target.strftime("%Y%m%d")
    rows = [i for i in items if i.get("fcstDate") == day]
    if not rows:
        return _result("kma_fcst", "getVilageFcst", [], params=params,
                       caveats=[f"{day} is beyond the 단기예보 horizon of the {bd} {bt} issue. "
                                "Use 중기예보 or re-query closer to the date."])
    summary = {"issued": f"{bd} {bt}", "target": day, "grid_source": src,
               **summarize_forecast(rows, hours)}
    return _result("kma_fcst", "getVilageFcst", rows, params=params, summary=summary,
                   caveats=["Forecast, not observation. Re-check on the day."])


def call_weather_warnings(client: PublicDataClient, *, sido: str | None = None,
                          stn_id: int | None = None, days_back: int = 2,
                          today: date | None = None, place: str | None = None) -> ApiResult:
    today = today or datetime.now(KST).date()
    if not sido and not stn_id and place:          # derive the region from the place's address
        sido = place_region(client, place)[0]
    stn = stn_id or WARNING_STN_IDS.get(sido_key(sido) or "", NATIONWIDE_STN)
    params = {"stnId": stn, "fromTmFc": (today - timedelta(days=days_back)).strftime("%Y%m%d"),
              "toTmFc": today.strftime("%Y%m%d")}
    items, total = client.call("kma_warning", "getWthrWrnList", params, num_rows=50)
    titles = [i.get("title") for i in items if i.get("title")]
    return _result("kma_warning", "getWthrWrnList", items, total_count=total, params=params,
                   summary={"stn_id": stn, "count": len(items), "latest": titles[:10]},
                   caveats=["The list holds issue AND lift bulletins; the latest one decides whether "
                            "a warning is active."])


# ---- disabled-person facilities (XML only) ---------------------------------------------

def call_facility_search(client: PublicDataClient, name: str, *, n: int = 10) -> ApiResult:
    """getDisConvFaclList by facility name. Parameter/field names: verify against the D29 spec."""
    items, total = client.call("disabled_facility", "getDisConvFaclList", {"faclNm": name}, num_rows=n)
    rows = [{"wfcltId": i.get("wfcltId"), "name": i.get("faclNm"), "addr": i.get("lcMnad"),
             "lat": i.get("faclLat"), "lon": i.get("faclLng")} for i in items]
    return _result("disabled_facility", "getDisConvFaclList", rows, total_count=total,
                   params={"faclNm": name})


def call_facility_eval(client: PublicDataClient, wfclt_id: str) -> ApiResult:
    items, _ = client.call("disabled_facility", "getFacInfoOpenApiJpEvalInfoList",
                           {"wfcltId": wfclt_id})
    features = sorted({f.strip() for i in items for f in (i.get("evalInfo") or "").split(",")
                       if f.strip()})
    return _result("disabled_facility", "getFacInfoOpenApiJpEvalInfoList", items,
                   params={"wfcltId": wfclt_id}, summary={"registered_features": features})


# ---- 한국민족문화대백과사전 (EKC) ------------------------------------------------------------

def _null_on_error(fn: Callable[..., ApiResult | None]) -> Callable[..., ApiResult | None]:
    """EKC policy: any request error -> None (logged, never raised)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a: Any, **kw: Any) -> ApiResult | None:
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 - by design
            log.warning("EKC %s failed -> None: %s", fn.__name__, e)
            return None
    return wrapper


_EKC_CAVEATS = ["Cite as 한국민족문화대백과사전 + title + eid; paraphrase, don't paste long passages."]


def _ekc_list(ekc: EkcClient, path: str, op: str, id_key: str, params: dict) -> ApiResult:
    data = ekc.get_json(path, params)
    rows = [_ekc_row(i, id_key) for i in _find_list(data)]
    return _result("ekc", op, rows, total_count=_find_total(data), params=params, caveats=_EKC_CAVEATS)


@_null_on_error
def call_ekc_articles(ekc: EkcClient, *, page: int = 1, size: int = 20) -> ApiResult | None:
    """GET /articles?p&ps — full article list (paged)."""
    return _ekc_list(ekc, "/articles", "articles", "eid", {"p": page, "ps": size})


@_null_on_error
def call_ekc_search(ekc: EkcClient, keyword: str, *, page: int = 1, size: int = 10) -> ApiResult | None:
    """GET /articles/search?q&p&ps — article search."""
    return _ekc_list(ekc, "/articles/search", "articles/search", "eid",
                     {"q": keyword, "p": page, "ps": size})


@_null_on_error
def call_ekc_article(ekc: EkcClient, eid: str | int, *, excerpt_chars: int = 1500) -> ApiResult | None:
    """GET /articles/{eid} — one article: title, definition, body excerpt, metadata."""
    path = f"/articles/{quote(str(eid), safe='')}"
    art = _unwrap_one(ekc.get_json(path))
    body = _clean(_pick(art, *_BODY_KEYS))
    summary = {"eid": _pick(art, "eid", "id") or eid,
               "title": _clean(_pick(art, *_TITLE_KEYS)),
               "definition": _clean(_pick(art, *_SUMMARY_KEYS))[:500],
               "body_excerpt": body[:excerpt_chars], "body_chars": len(body),
               "meta": {k: art[k] for k in _META_KEYS if art.get(k) not in (None, "", [], {})},
               "fields": sorted(art)[:40]}         # raw keys, to see the real schema
    return _result("ekc", "articles/{eid}", [art] if art else [], params={"eid": eid},
                   summary=summary, caveats=_EKC_CAVEATS)


@_null_on_error
def call_ekc_lookup(ekc: EkcClient, keyword: str, *, candidates: int = 5) -> ApiResult | None:
    """search -> best eid (exact title match first) -> article. For 'explain X' requests."""
    found = call_ekc_search(ekc, keyword, size=candidates)
    if found is None:                     # request error -> None
        return None
    if not found.items:
        return _result("ekc", "articles/search+articles/{eid}", [], params={"q": keyword},
                       caveats=[f"No EKC article for '{keyword}'. Do not supply history from memory."])
    exact = [r for r in found.items if r.get("title", "").split("(")[0].strip() == keyword]
    best = (exact or found.items)[0]
    res = call_ekc_article(ekc, best["eid"])
    if res is None:
        return None
    others = [r.get("title", "?") for r in found.items if r is not best]
    if others:
        res.caveats.append(("Exact title match" if exact else "Top search hit (no exact match)")
                           + "; same/similar headwords exist — check it is the same subject: "
                           + ", ".join(others[:5]))
    res.operation = "articles/search+articles/{eid}"
    res.params = {"q": keyword, "eid": best["eid"]}
    return res


@_null_on_error
def call_ekc_medias(ekc: EkcClient, *, page: int = 1, size: int = 20) -> ApiResult | None:
    """GET /medias?p&ps — media list."""
    return _ekc_list(ekc, "/medias", "medias", "mid", {"p": page, "ps": size})


@_null_on_error
def call_ekc_media_search(ekc: EkcClient, keyword: str, *, page: int = 1, size: int = 10) -> ApiResult | None:
    """GET /medias/search?q&p&ps — media (images etc.) search."""
    return _ekc_list(ekc, "/medias/search", "medias/search", "mid", {"q": keyword, "p": page, "ps": size})


@_null_on_error
def call_ekc_media(ekc: EkcClient, mid: str | int) -> ApiResult | None:
    """GET /medias/{mid} — one media item."""
    m = _unwrap_one(ekc.get_json(f"/medias/{quote(str(mid), safe='')}"))
    summary = {"mid": _pick(m, "mid", "id") or mid, "title": _clean(_pick(m, *_TITLE_KEYS)),
               "url": _pick(m, *_MEDIA_URL_KEYS), "eid": _pick(m, "eid", "articleId"),
               "fields": sorted(m)[:40]}
    return _result("ekc", "medias/{mid}", [m] if m else [], params={"mid": mid}, summary=summary,
                   caveats=_EKC_CAVEATS + ["Check the media's license/credit before reuse."])
