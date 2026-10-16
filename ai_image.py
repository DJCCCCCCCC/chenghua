from __future__ import annotations

import base64
import re
from urllib.parse import quote, urlsplit


GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"


def normalize_base_url(value: str, provider: str) -> str:
    base = value.strip().rstrip("/")
    if not base:
        base = GEMINI_DEFAULT_BASE if provider == "Gemini" else OPENAI_DEFAULT_BASE
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头。")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Base URL 不应包含查询参数、片段或登录凭据。")
    return base


def detect_provider(base_url: str, requested: str = "自动") -> str:
    if requested in ("OpenAI", "Gemini"):
        return requested
    host = (urlsplit(base_url).hostname or "").lower()
    return "Gemini" if host == "generativelanguage.googleapis.com" else "OpenAI"


def _endpoint(base: str, suffix: str, provider: str) -> str:
    root = base
    if not urlsplit(base).path.strip("/"):
        root += "/v1beta" if provider == "Gemini" else "/v1"
    return root + suffix


def _headers(key: str, provider: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if provider == "Gemini":
        headers["x-goog-api-key"] = key
    else:
        headers["Authorization"] = "Bearer " + key
    return headers


def _model_id(value) -> str:
    return str(value or "").removeprefix("models/")


def list_models(base_url: str, key: str, requested: str = "自动", session=None):
    import requests

    if not key.strip():
        raise ValueError("请先填写 API Key。")
    provider = detect_provider(base_url, requested)
    base = normalize_base_url(base_url, provider)
    url = _endpoint(base, "/models", provider)
    session = session or requests
    models = []
    while url:
        response = session.get(url, headers=_headers(key.strip(), provider), timeout=30)
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("data", payload.get("models", [])):
            model_id = _model_id(item.get("id") or item.get("name"))
            methods = item.get("supportedGenerationMethods", [])
            if provider == "Gemini":
                if methods and "generateContent" not in methods:
                    continue
            if model_id:
                models.append(model_id)
        next_page = payload.get("nextPageToken")
        url = (_endpoint(base, "/models?pageToken=" + quote(next_page, safe=""), provider)
               if provider == "Gemini" and next_page else None)
    if not models:
        raise RuntimeError("接口没有返回可用模型，请检查 Base URL、密钥和接口兼容性。")
    models = set(models)
    return provider, sorted(models, key=lambda model: (
        not bool(re.search(r"image|imagen|dall.?e|banana|flux", model, re.I)), model))


def _extract_openai_image(payload, session):
    items = payload.get("data") or []
    if not items:
        raise RuntimeError("OpenAI 格式响应没有 data 图像内容。")
    item = items[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        response = session.get(item["url"], timeout=60)
        response.raise_for_status()
        return response.content
    raise RuntimeError("OpenAI 格式响应中没有 b64_json 或图像 URL。")


def _extract_gemini_image(payload):
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return base64.b64decode(data["data"])
    raise RuntimeError("Gemini 响应未包含图像数据；所选模型可能不支持图像生成。")


def generate_image(base_url: str, key: str, model: str, prompt: str,
                   requested: str = "自动", session=None) -> tuple[str, bytes]:
    import requests

    if not key.strip() or not model.strip() or not prompt.strip():
        raise ValueError("请填写 API Key、模型和提示词。")
    provider = detect_provider(base_url, requested)
    base = normalize_base_url(base_url, provider)
    session = session or requests
    if provider == "Gemini":
        model_id = _model_id(model)
        url = _endpoint(base, "/models/" + model_id + ":generateContent", provider)
        payload = {
            "contents": [{"parts": [{"text": prompt.strip() + ", simple line art, clean outlines, white background"}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        response = session.post(url, headers=_headers(key.strip(), provider), json=payload, timeout=180)
        response.raise_for_status()
        return provider, _extract_gemini_image(response.json())

    url = _endpoint(base, "/images/generations", provider)
    payload = {"model": model.strip(),
               "prompt": prompt.strip() + ", simple line art, clean outlines, white background",
               "size": "1024x1024", "n": 1}
    response = session.post(url, headers=_headers(key.strip(), provider), json=payload, timeout=180)
    response.raise_for_status()
    return provider, _extract_openai_image(response.json(), session)
