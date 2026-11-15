"""Chat completions on Verda's OpenAI-compatible inference API, with JSON replies and per-call cost."""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://inference.verda.com/v1/chat/completions"
KEY = dict(line.split("=", 1) for line in (Path.home() / ".config/junction/verda-inference.env").read_text().split())
WRITER = "kimi-k3-1-pro"  # restates the change as claims
ADVERSARY = "deepseek-4-1-flash-1017"  # a different model family tries to break the claims
PRICE = {  # USD per 1M tokens: input, cached input, output (verda.com/pricing, Nov 2026)
    WRITER: (2.00, 0.20, 10.00),
    ADVERSARY: (0.15, 0.006, 0.60),
}


class Usage:
    """Token and cost totals over the calls of one review."""

    def __init__(self):
        self.calls, self.tokens, self.usd = [], 0, 0.0

    def add(self, model, usage):
        pin, pcached, pout = PRICE[model]
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        usd = (pin * (usage["prompt_tokens"] - cached) + pcached * cached + pout * usage["completion_tokens"]) / 1e6
        self.calls.append({"model": model, "prompt": usage["prompt_tokens"], "completion": usage["completion_tokens"], "usd": usd})
        self.tokens += usage["total_tokens"]
        self.usd += usd


def ask_json(model, system, user, usage: Usage, effort=None):
    """One chat call whose reply must be a JSON object; returns it parsed."""
    body = {"model": model, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if effort:
        body["reasoning_effort"] = effort
    req = urllib.request.Request(API, json.dumps(body).encode(), {"Authorization": f"Bearer {KEY['VERDA_INFERENCE_KEY']}",
                                                                 "Content-Type": "application/json"})
    for attempt, wait in enumerate((5, 15, 30, None)):  # rate limits, transient errors and the odd unparseable reply
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                reply = json.load(r)
            usage.add(model, reply["usage"])
            return json.loads(reply["choices"][0]["message"]["content"])
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
            if wait is None or (isinstance(e, urllib.error.HTTPError) and e.code not in (429, 500, 502, 503, 504)):
                raise
            time.sleep(wait)
