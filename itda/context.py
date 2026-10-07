"""Situation signals -> unstated needs -> which APIs to consult.

The planner model also infers needs, but this table makes the common Korean travel contexts
(모시고 가는 부모님, 아이, 무릎·휠체어, 외국인 손님, 비건·할랄, 비 소식 ...) reliable and
explainable: every need says why it was assumed and which public data was used to check it.
Needs are preferences, never facts; explicit user conditions always win.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Rule:
    id: str
    label: str
    icon: str
    pattern: str
    needs: list[tuple[str, str, str]]          # (category, need, why)
    tools: list[tuple[str, dict]] = field(default_factory=list)  # (tool, extra args); place filled in later
    confidence: str = "medium"


RULES: list[Rule] = [
    Rule("elder", "부모님·어르신 동행", "👵",
         r"부모님|어르신|할머니|할아버지|어머니|아버지|어머님|아버님|시부모|장인|장모|노부모|[6-9]\d\s*(세|대)|모시고",
         [("식사", "한식 위주, 맵지 않고 부드러운 메뉴 우선", "부모님 세대의 한식 선호 경향"),
          ("식사", "좌식/입식 여부 확인 (무릎 부담)", "한국 식당은 좌식이 많음"),
          ("이동", "걷는 거리·계단 최소화, 긴 구간은 택시 고려", "체력·관절 부담"),
          ("휴식", "60~90분마다 앉아 쉴 곳", "장시간 관람 피로"),
          ("편의", "화장실·엘리베이터 위치 미리 확인", "어르신 동행 시 자주 필요"),
          ("시간", "점심은 11:30 전후로 이르게, 붐비는 시간대 피하기", "대기·혼잡 부담")],
         [("nearby", {"kind": "food"}), ("accessibility", {}), ("route", {})]),
    Rule("kids", "아이 동반", "🧒",
         r"아이|아기|유아|어린이|초등|[0-9]{1,2}\s*살|유모차|자녀|딸|아들|가족여행",
         [("일정", "한 장소 60분 안팎의 짧은 체험 단위", "집중 시간"),
          ("편의", "유모차 동선·수유실·화장실 확인", "영유아 동반"),
          ("식사", "아이가 먹을 수 있는 순한 메뉴, 간식 시간", "매운 음식이 많음"),
          ("체험", "방문일에 열리는 체험·행사 확인", "아이 흥미")],
         [("accessibility", {}), ("festival", {}), ("nearby", {"kind": "food"})]),
    Rule("mobility", "이동 제약 (휠체어·무릎·보행 불편)", "♿",
         r"휠체어|무릎|거동|지팡이|목발|보행\s*불편|계단.{0,4}(어려|힘들|못)|다리.{0,4}(불편|아프)|관절",
         [("이동", "무장애 동선·경사로·엘리베이터 우선", "계단 회피"),
          ("편의", "장애인 화장실·휠체어 대여 여부 확인", "등록 정보 + 당일 확인"),
          ("이동", "구간이 길면 택시, 도보는 짧게", "피로 누적")],
         [("accessibility", {}), ("route", {})], "high"),
    Rule("pregnant", "임산부 동행", "🤰",
         r"임산부|임신|만삭|태교",
         [("휴식", "자주 앉아 쉴 곳, 화장실 가까운 동선", ""),
          ("식사", "날음식·회·덜 익힌 음식 피하기", ""),
          ("날씨", "더위·추위 노출 최소화", "")],
         [("kma_weather", {}), ("accessibility", {})], "high"),
    Rule("foreign", "외국인 방문객", "🌏",
         r"외국인|해외\s*방문|\"visitor_type\"\s*:\s*\"foreign\"|(?<![_\"])foreign|tourist|영어로|일본인|중국인|외국\s*손님|바이어",
         [("소통", "직원에게 보여줄 한국어 문장 카드", "언어 장벽"),
          ("식사", "매운 정도·젓갈·육수 등 숨은 재료 미리 설명", "한식 특유의 재료"),
          ("문화", "신발 벗는 식당·사찰 예절 미리 안내", "문화 차이"),
          ("배경", "왕조·시대를 한 줄로 풀어 설명", "배경지식 부족")],
         [("encyclopedia", {}), ("place_info", {"lang": "en"})]),
    Rule("diet", "식이 제한 (비건·할랄·알레르기)", "🥗",
         r"비건|vegan|채식|할랄|halal|알레르기|allergy|글루텐|gluten|코셔|kosher|땅콩|참깨|갑각류|유당",
         [("식사", "식당을 미리 확인하고, 확인이 안 되면 먹지 않기", "교차오염 위험"),
          ("소통", "재료를 묻는 한국어 문장 카드", "")],
         [("nearby", {"kind": "food"})], "high"),
    Rule("couple", "연인·기념일", "💑",
         r"연인|데이트|여자\s*친구|남자\s*친구|애인|신혼|기념일|프러포즈",
         [("분위기", "노을·야경 시간대와 조용한 장소", ""),
          ("사진", "사진 명소와 붐비지 않는 시간", "")],
         [("festival", {}), ("nearby", {"kind": "culture"})], "low"),
    Rule("weather", "날씨 변수 (비·더위·추위)", "☔",
         r"비\s*(가|오|올|예보|소식|와)|우천|장마|소나기|폭염|더위|더운|한파|추위|추운|눈\s*(이|오|와)|미세먼지",
         [("날씨", "실내 대안 장소 준비", ""), ("날씨", "우산·양산·보온 준비 안내", "")],
         [("kma_weather", {}), ("weather_warning", {}), ("nearby", {"kind": "culture"})], "high"),
    Rule("history", "역사·문화 관심", "📜",
         r"역사|문화재|유적|유산|왕조|조선|고려|삼국|해설|공부|교과서",
         [("해설", "권위 있는 출처 기반의 해설, 불확실한 연대는 표시", "")],
         [("encyclopedia", {})]),
    Rule("hanbok", "한복 체험", "👘",
         r"한복",
         [("문화", "고궁 한복 착용 시 무료입장 여부 확인, 대여점 위치", "제도 변경 가능 → 확인 필요")],
         [("nearby", {"kind": "shopping"}), ("place_info", {})]),
    Rule("photo", "사진·SNS", "📷",
         r"사진|인스타|포토|감성|뷰\s*맛집",
         [("사진", "사진 명소와 빛이 좋은 시간대", "")],
         [("place_info", {})], "low"),
    Rule("short", "짧은 일정", "⏱",
         r"반나절|[1-3]\s*시간|짧게|잠깐|시간이?\s*없|당일치기|오전만|오후만",
         [("일정", "동선을 압축하고 이동 시간을 계산", "")],
         [("route", {})]),
    Rule("pet", "반려동물 동반", "🐶",
         r"반려견|강아지|반려동물|애견|고양이",
         [("편의", "반려동물 동반 가능 여부는 공식 정보로 확인 필요 (방문 전 확인)", "장소마다 규정이 다름")],
         [], "high"),
    Rule("group", "단체", "👥",
         r"단체|인원|명\s*이상|[1-9]\d\s*명|버스\s*대절|워크숍",
         [("예약", "단체 예약·주차 필요 여부 (승인 필요)", "인원 규모")],
         [("place_info", {})]),
    Rule("budget", "가성비", "💰",
         r"저렴|가성비|무료|돈\s*(없|아끼)|저예산",
         [("비용", "무료 입장·할인 정보 확인", "")],
         [("place_info", {})], "low"),
]


def detect(text: str) -> list[Rule]:
    return [r for r in RULES if re.search(r.pattern, text, re.I)]


def suggested_calls(rules: list[Rule], places: list[str], visit_date: str | None,
                    available: set[str], existing: list[dict], limit: int = 6) -> list[dict]:
    """Tool calls implied by the detected situation that the planner did not already make."""
    have = {(c.get("tool"), str((c.get("args") or {}).get("place") or (c.get("args") or {}).get("topic") or ""))
            for c in existing if isinstance(c, dict)}
    out: list[dict] = []

    def add(tool: str, args: dict, why: str) -> None:
        key = (tool, str(args.get("place") or args.get("topic") or ""))
        if tool in available and key not in have and len(out) < limit:
            have.add(key)
            out.append({"tool": tool, "args": args, "why": why, "auto": True})

    for r in rules:
        for tool, extra in r.tools:
            if tool == "route":
                if len(places) >= 2 and not any(c.get("tool") == "route" for c in existing + out):
                    add("route", {"places": places[:6]}, f"상황 신호: {r.label} → 동선·도보 시간 확인")
                continue
            if not places:
                continue
            targets = places[:2] if tool == "accessibility" else places[:1]
            for p in targets:
                args = {"place": p, **extra}
                if tool in ("kma_weather", "festival") and visit_date:
                    args["date"] = visit_date
                if tool == "encyclopedia":
                    args = {"topic": p}
                add(tool, args, f"상황 신호: {r.label} → {tool} 확인")
    return out


def needs_for(rules: list[Rule], tool_log: list[dict]) -> list[dict]:
    """Rule-based needs, each annotated with the public data actually consulted for it."""
    ok_tools = {x["call"].get("tool") for x in tool_log if x.get("result", {}).get("ok")}
    out = []
    for r in rules:
        checked = sorted({t for t, _ in r.tools} & ok_tools)
        for cat, need, why in r.needs:
            out.append({"signal": r.label, "icon": r.icon, "category": cat, "need": need,
                        "why": why or r.label, "confidence": r.confidence, "checked_with": checked,
                        "source": "rule"})
    return out


_ABROAD = (r"스페인|바르셀로나|마드리드|프랑스|파리|이탈리아|로마|베네치아|영국|런던|독일|베를린|스위스|미국|뉴욕|하와이|"
           r"일본|도쿄|오사카|교토|후쿠오카|삿포로|중국|베이징|상하이|대만|타이베이|태국|방콕|베트남|다낭|하노이|필리핀|세부|"
           r"싱가포르|호주|시드니|캐나다|유럽|동남아|괌|사이판|발리|몰디브|두바이|튀르키예|터키|이집트")
_KOREA = (r"한국|서울|부산|인천|대구|대전|광주|울산|세종|경기|강원|충청|전라|경상|제주|경주|전주|수원|안동|여수|강릉|속초|"
          r"고궁|궁|사찰|절|한옥|시장|해담|성진정|국내")
_TRAVEL = r"여행|여행지|추천|가볼|일정|코스|관광|투어|명소"
_OFFTOPIC = r"주식|코인|비트코인|투자|코드|코딩|프로그램\s*짜|숙제|과제\s*대신|레포트\s*대신|로또"


def scope_hint(task: str) -> str:
    """Cheap pre-check for obviously out-of-scope requests. The planner makes the final call."""
    abroad = re.findall(_ABROAD, task)
    if abroad and re.search(_TRAVEL, task) and not re.search(_KOREA, task):
        return f"해외 지명({', '.join(sorted(set(abroad)))}) 여행 요청으로 보이며 한국 장소가 없음 → 범위 밖일 가능성 높음"
    if re.search(_OFFTOPIC, task) and not re.search(_KOREA + "|문화|역사|관광|여행지", task):
        return "문화·역사·여행과 무관한 요청으로 보임 → 범위 밖일 가능성 높음"
    return "특이사항 없음"
