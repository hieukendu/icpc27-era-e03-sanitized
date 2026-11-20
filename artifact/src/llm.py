"""Deterministic, disk-cached LLM access (Ollama local models; optional Anthropic frontier condition).

Every response is cached under results/llm_cache/<sha256(backend|model|seed|system|prompt|json)>.json so
`make all` replays byte-identically without a server. Temperature 0, fixed seed.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from config import CACHE, LLM_SEED

OLLAMA_URL = "http://localhost:11434/api/generate"
_STATS = {"calls": 0, "cache_hits": 0, "anthropic_calls": 0}


def _key(backend, model, system, prompt, json_mode, num_predict):
    raw = f"{backend}|{model}|{LLM_SEED}|{system}|{prompt}|{json_mode}|{num_predict}"
    if backend == "anthropic":
        raw += "|thinking=disabled"     # RUNLOG cycle 7: default adaptive thinking consumed the token budget
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def stats():
    return dict(_STATS)


def cache_digest():
    """Order-independent digest of the cache directory (for summary.json provenance)."""
    names = sorted(os.listdir(CACHE))
    h = hashlib.sha256()
    for n in names:
        h.update(n.encode())
    return f"{len(names)}:{h.hexdigest()[:16]}"


def llm(prompt, backend="ollama", model="qwen2.5-coder:14b", system=None, num_predict=800,
        json_mode=False, retries=5):
    key = _key(backend, model, system, prompt, json_mode, num_predict)
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        _STATS["cache_hits"] += 1
        with open(path) as f:
            return json.load(f)["response"]
    if os.environ.get("ATTEST_OFFLINE") == "1":
        raise RuntimeError(f"Missing cached response {key}; offline mode forbids model calls")
    _STATS["calls"] += 1
    if backend == "ollama":
        body = {"model": model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0, "seed": LLM_SEED, "num_predict": num_predict}}
        if system:
            body["system"] = system
        if json_mode:
            body["format"] = "json"
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                resp = json.loads(urllib.request.urlopen(req, timeout=300).read())
                text = resp["response"]
                rec = {"backend": backend, "model": model, "seed": LLM_SEED, "system": system,
                       "prompt": prompt, "json_mode": json_mode, "num_predict": num_predict,
                       "response": text, "eval_count": resp.get("eval_count"),
                       "total_duration_ns": resp.get("total_duration")}
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:  # transient server hiccup
                last = e
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"ollama failed after {retries} attempts: {last}")
    elif backend == "anthropic":
        import anthropic  # installed in the shared venv
        _STATS["anthropic_calls"] += 1
        client = anthropic.Anthropic()
        # SDK 2.6 / current models expose no temperature parameter: the frontier condition is sampled at the
        # provider default and made reproducible by the cache, not by decoding settings.
        kwargs = {"model": model, "max_tokens": num_predict, "thinking": {"type": "disabled"},
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        text = "".join(getattr(b, "text", "") for b in msg.content)
        rec = {"backend": backend, "model": model, "model_id_returned": msg.model, "seed": None,
               "system": system, "prompt": prompt, "json_mode": json_mode, "num_predict": num_predict,
               "response": text, "thinking": "disabled", "stop_reason": msg.stop_reason,
               "usage": {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}}
    else:
        raise ValueError(backend)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, sort_keys=True)
    os.replace(tmp, path)
    return text


def parse_json(text):
    """Best-effort JSON object extraction from a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find outermost braces
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            return None
    return None
