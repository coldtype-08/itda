# ItDA 에이전트 인터페이스 (UI·발표 담당용)

## 실행

```bash
python3 -m itda --task <TASK.md> --input <input_dir> --output <output_dir> \
  --visitor foreign|korean --interests history,family,kculture [--lang en|ko] [--visit-date YYYY-MM-DD]
```

- `--visitor`: 첫 화면 선택 (외국인 / 한국인). 기본 언어도 여기서 정해짐 (foreign→en, korean→ko)
- `--interests`: 두 번째 선택, 여러 개 가능
- 소요 시간: 문서 약 20개 기준 1~3분 (모델 속도에 따라 다름)

## 출력 (output_dir)

| 파일 | 용도 |
|---|---|
| `course_draft.md` | 사람이 읽는 초안. 그대로 화면에 렌더링 가능 |
| `itda_result.json` | UI용 구조화 데이터 (아래) |
| `audit.json` | 보안 패널용: 읽은 파일, 차단된 접근, 무시한 외부 지시, LLM 호출 기록 (내용·키는 기록 안 함) |

### itda_result.json

```jsonc
{
  "status": "draft",
  "lens": {"visitor_type": "foreign", "interests": ["history"], "language": "en"},
  "visit_date": "2026-10-10",
  "plan": {
    "title": "...", "summary": "...",
    "itinerary": [{"time", "place", "activity", "access_notes", "evidence": ["D05"]}],
    "dietary_plan": [{"person", "needs": [], "guidance", "ask_on_site", "evidence": []}],
    "interpretation": [{"place", "text", "caveats", "evidence": []}],
    "uncertainties": ["..."],
    "approvals_needed": ["..."],      // 하지 않은 행동 (예약·연락 등)
    "not_done": ["..."]
  },
  "resolved": {
    "facts": [{"topic", "subject", "decision", "status": "confirmed|uncertain", "evidence", "overridden": [{"doc", "reason"}]}],
    "people": [...], "rules": [...],
    "excluded_sources": [{"doc", "reason"}],
    "untrusted_instructions": [{"doc", "summary"}],
    "open_questions": [...]
  },
  "sources": [{"id": "D05", "path": "local/market_notice_2026-10-06.txt", "relevant", "source_type", "reliability", "doc_date", "contains_instructions_to_agent"}]
}
```

`evidence`의 `D05` 같은 id는 `sources[].id`로 파일 경로를 찾으면 됩니다.

## UI 아이디어 매핑

- 일정 카드: `plan.itinerary` (근거 뱃지 = evidence → sources.path)
- "왜 이 정보를 골랐나": `resolved.facts[].overridden` (예: 2025 블로그 → 2026 공지로 대체)
- 보안 패널: `resolved.untrusted_instructions` + `audit.json`의 `blocked_read` / `untrusted_instruction`
- 확인 필요 / 승인 필요 배지: `plan.uncertainties`, `plan.approvals_needed`
