"""Minimal OpenAI-compatible chat client using only the standard library.

No third-party dependencies, so the agent runs in a sandbox with package
registries blocked. Works against build.nvidia.com, NemoClaw's inference.local,
or a local NIM on the L40S; only ITDA_LLM_BASE_URL changes.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .config import Config
from .guard import Audit

_THINK = re.compile(r"<think>.*?</think>", re.S)


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: Config, audit: Audit) -> None:
        self.cfg = cfg
        self.audit = audit
        self.extra = json.loads(cfg.llm_extra_body) if cfg.llm_extra_body else {}

    def chat(self, messages: list[dict], model: str, temperature: float = 0.1,
             max_tokens: int = 4096, label: str = "") -> str:
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens, **self.extra}
        req = urllib.request.Request(
            self.cfg.llm_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.cfg.llm_api_key}"},
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(3):
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.llm_timeout) as resp:
                    payload = json.loads(resp.read())
                msg = payload["choices"][0]["message"]
                text = msg.get("content") or ""
                usage = payload.get("usage", {})
                self.audit.log("llm_call", label=label, model=model, ok=True,
                               seconds=round(time.time() - t0, 2),
                               tokens=usage.get("total_tokens"))
                return _THINK.sub("", text).strip()
            except urllib.error.HTTPError as e:
                last = e
                self.audit.log("llm_call", label=label, model=model, ok=False, status=e.code)
                if e.code in (400, 401, 403, 404):
                    break  # not retryable
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last = e
                self.audit.log("llm_call", label=label, model=model, ok=False, error=type(e).__name__)
            time.sleep(2 ** attempt)
        raise LLMError(f"LLM call failed ({label}): {last}")

    def chat_json(self, system: str, user: str, model: str, label: str,
                  mock: Callable[[], Any]) -> Any:
        if self.cfg.mock:
            self.audit.log("llm_call", label=label, model="mock", ok=True)
            return mock()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = self.chat(messages, model=model, label=label)
        try:
            return extract_json(text)
        except ValueError:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "위 응답을 설명 없이 유효한 JSON 하나로만 다시 출력하라."}]
            return extract_json(self.chat(messages, model=model, label=label + ":repair"))


def extract_json(text: str) -> Any:
    """Parse the first complete JSON object/array in text (tolerates ```json fences and preambles)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                c = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
    raise ValueError("no JSON found in model output")
