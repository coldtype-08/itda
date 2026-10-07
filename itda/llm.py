"""Minimal OpenAI-compatible chat client using only the standard library.

No third-party dependencies, so the agent runs in a sandbox with package
registries blocked. Works against build.nvidia.com, NemoClaw's inference.local,
or a local NIM on the L40S; only ITDA_LLM_BASE_URL changes.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .config import Config
from .guard import Audit

_THINK = re.compile(r"<think>.*?</think>", re.S)


class LLMError(RuntimeError):
    pass


class LLMAuthError(LLMError):
    """401/403: wrong or missing credentials. Never retried or swallowed."""


class LLM:
    def __init__(self, cfg: Config, audit: Audit) -> None:
        self.cfg = cfg
        self.audit = audit
        self.extra = json.loads(cfg.llm_extra_body) if cfg.llm_extra_body else {}
        # Nemotron 3 models reason before answering by default; that costs 40-70s per call
        # and can eat the whole max_tokens budget. Turn it off unless ITDA_THINKING=1.
        self.no_think = os.environ.get("ITDA_THINKING") != "1"
        self.no_think_supported = True

    def _base(self, model: str) -> str:
        if self.cfg.small_base_url and model == self.cfg.model_small:
            return self.cfg.small_base_url
        if self.cfg.fast_base_url and model == self.cfg.model_fast and model != self.cfg.model_main:
            return self.cfg.fast_base_url
        return self.cfg.llm_base_url

    def _request(self, body: dict) -> dict:
        req = urllib.request.Request(
            self._base(body["model"]).rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.cfg.llm_api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.cfg.llm_timeout) as resp:
            return json.loads(resp.read())

    def chat(self, messages: list[dict], model: str, temperature: float = 0.1,
             max_tokens: int = 8192, label: str = "") -> str:
        last: Exception | None = None
        for attempt in range(3):
            body = {"model": model, "messages": messages, "temperature": temperature,
                    "max_tokens": max_tokens, **self.extra}
            if self.no_think and self.no_think_supported:
                body.setdefault("chat_template_kwargs", {"enable_thinking": False})
            t0 = time.time()
            try:
                payload = self._request(body)
                choice = payload["choices"][0]
                msg = choice["message"]
                text = msg.get("content") or ""
                usage = payload.get("usage", {})
                secs = round(time.time() - t0, 1)
                self.audit.log("llm_call", label=label, model=model, ok=True, seconds=secs,
                               tokens=usage.get("total_tokens"), finish=choice.get("finish_reason"))
                if os.environ.get("ITDA_VERBOSE", "1") == "1":
                    print(f"      · {label} {secs}s tokens={usage.get('total_tokens')} "
                          f"finish={choice.get('finish_reason')}", file=sys.stderr, flush=True)
                if not text.strip() and msg.get("reasoning_content"):
                    raise LLMError("model returned reasoning only (answer truncated)")
                return _THINK.sub("", text).strip()
            except urllib.error.HTTPError as e:
                last = e
                self.audit.log("llm_call", label=label, model=model, ok=False, status=e.code)
                if e.code in (401, 403):
                    raise LLMAuthError(f"{e.code} from {self.cfg.llm_base_url} — API 키/권한을 확인하세요") from e
                if e.code == 400 and self.no_think_supported and "chat_template_kwargs" not in self.extra:
                    self.no_think_supported = False  # endpoint rejects the knob; retry without it
                    continue
                if e.code in (400, 404):
                    break  # not retryable
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, LLMError) as e:
                last = e
                self.audit.log("llm_call", label=label, model=model, ok=False, error=type(e).__name__)
            time.sleep(2 ** attempt)
        raise LLMError(f"LLM call failed ({label}): {last}")

    def chat_json(self, system: str, user: str, model: str, label: str,
                  mock: Callable[[], Any], temperature: float = 0.1) -> Any:
        if self.cfg.mock:
            self.audit.log("llm_call", label=label, model="mock", ok=True)
            return mock()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = self.chat(messages, model=model, label=label, temperature=temperature)
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
