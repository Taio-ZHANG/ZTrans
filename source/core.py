"""ZTrans: explicit destinations, no telemetry, no persistent translation history."""
from __future__ import annotations

import base64
import json
import sys
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

APP_VERSION = "1.2.3"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
CONFIG_DIR = APP_DIR / "data"
LANGUAGES = ["简体中文", "英语", "繁体中文", "日语", "韩语", "德语", "法语", "西班牙语", "俄语", "意大利语", "葡萄牙语"]


class UserError(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Settings:
    provider: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "hy-mt1.5:7b"
    api_url: str = "https://api.deepseek.com/v1"
    api_model: str = "deepseek-chat"
    api_key: str = ""
    remote_consent: str = ""
    source: str = "自动识别"
    target: str = "简体中文"
    repair_lines: bool = True
    style: str = "忠实翻译"
    glossary: str = ""
    remember_key: bool = True
    startup: bool = True
    font_size: int = 13

    @property
    def base_url(self):
        return normalize_url(self.ollama_url if self.provider == "ollama" else self.api_url)

    @property
    def model(self):
        return self.ollama_model if self.provider == "ollama" else self.api_model

    @property
    def consent_id(self):
        return f"{self.provider}|{self.base_url}"


def normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        p = urlsplit(value)
        _ = p.port
    except ValueError:
        raise UserError("服务地址格式不正确。")
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise UserError("请输入 http:// 或 https:// 服务地址，不要包含密码、查询参数或 #。")
    host = p.hostname.lower()
    if host == "localhost":
        host = "127.0.0.1"
    host = f"[{host}]" if ":" in host else host
    netloc = host + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme.lower(), netloc, p.path.rstrip("/"), "", ""))


def is_loopback(url: str) -> bool:
    return urlsplit(normalize_url(url)).hostname in ("127.0.0.1", "::1")


def validate_destination(cfg: Settings):
    if not cfg.model.strip():
        raise UserError("请先在设置中选择或填写模型名称。")
    if not is_loopback(cfg.base_url):
        if not cfg.base_url.startswith("https://"):
            raise UserError("远程服务请使用 HTTPS，避免明文传输原文和密钥。")
        if cfg.remote_consent != cfg.consent_id:
            raise UserError("这是远程服务。请在设置中确认该地址并启用“允许原文发送到此服务”。")
    if cfg.provider == "ollama" and re.search(r"(?:[:\-]cloud)(?:$|[:\-])", cfg.model, re.I):
        raise UserError("Ollama 云端模型不属于本地翻译。请换成本地模型，或用在线 API 模式明确配置云端服务。")


def save_settings(cfg: Settings, directory: Path = CONFIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    key = data.pop("api_key")
    if key and cfg.remember_key:
        import win32crypt
        payload = json.dumps({"endpoint": normalize_url(cfg.api_url), "key": key}).encode("utf-8")
        data["protected_key"] = base64.b64encode(win32crypt.CryptProtectData(payload, "ZTrans", None, None, None, 0)).decode()
    temporary = directory / "settings.tmp"
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "settings.json")


def load_settings(directory: Path = CONFIG_DIR) -> Settings:
    cfg = Settings()
    try:
        data = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    for name in cfg.__dataclass_fields__:
        if name != "api_key" and name in data and type(data[name]) is type(getattr(cfg, name)):
            setattr(cfg, name, data[name])
    defaults = Settings()
    for name, choices in (("provider", ("ollama", "api")), ("source", ["自动识别"] + LANGUAGES),
                          ("target", LANGUAGES), ("style", ("忠实翻译", "学术论文", "自然流畅"))):
        if getattr(cfg, name) not in choices:
            setattr(cfg, name, getattr(defaults, name))
    cfg.font_size = max(11, min(22, cfg.font_size))
    invalid_api_url = False
    for name in ("ollama_url", "api_url"):
        try:
            normalize_url(getattr(cfg, name))
        except UserError:
            setattr(cfg, name, getattr(defaults, name))
            cfg.remote_consent = ""
            if name == "api_url":
                invalid_api_url = True
    try:
        if data.get("protected_key") and not invalid_api_url:
            import win32crypt
            secret = json.loads(win32crypt.CryptUnprotectData(base64.b64decode(data["protected_key"]), None, None, None, 0)[1])
            if secret["endpoint"] == normalize_url(cfg.api_url):
                cfg.api_key = secret["key"]
    except Exception:
        cfg.api_key = ""
    return cfg


LIST_START = re.compile(r"^(?:[-*•●▪]\s|\d{1,3}[.)、]\s*|[（(]\d+[）)]\s*)")
CJK = r"\u3400-\u9fff"


def repair_linebreaks(text: str) -> str:
    """Join hard wraps while retaining blank paragraphs, bullets, tables and headings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")
    groups = re.split(r"\n[ \t]*\n+", text.strip())
    output = []
    for group in groups:
        lines = [x.strip() for x in group.split("\n") if x.strip()]
        if not lines:
            continue
        result = lines[0]
        for i, line in enumerate(lines[1:], 1):
            prev = lines[i - 1]
            boundary = (LIST_START.match(line) or "\t" in line or "\t" in prev
                        or prev.startswith("#") or line.startswith("#")
                        or (len(prev) < 65 and prev.endswith((":", "：")))
                        or (len(prev) < 45 and prev.isupper() and not prev.endswith((".", ","))))
            if boundary:
                result += "\n" + line
            elif re.search(r"[A-Za-z]{3,}-$", result) and re.match(r"[a-z]", line):
                result = result[:-1] + line
            elif re.search(f"[{CJK}]$", result) and re.match(f"[{CJK}，。！？；：]", line):
                result += line
            elif result.endswith(tuple("，。！？；：）】")) and re.match(f"[{CJK}]", line):
                result += line
            else:
                result += " " + line
        output.append(result)
    return "\n\n".join(output)


def split_text(text: str, limit: int = 1500) -> list[str]:
    """Bound inputs without dropping characters or splitting a UTF-8 codepoint."""
    pieces = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = paragraph.strip()
        while len(paragraph) > limit:
            candidate = paragraph[:limit]
            boundaries = [m.end() for m in re.finditer(r"[。！？!?]\s*|[.;]\s+|\n", candidate)]
            pos = max((x for x in boundaries if x > limit // 3), default=0)
            if not pos:
                pos = candidate.rfind(" ", limit // 2, limit + 1)
            if pos <= 0:
                pos = limit
            pieces.append(paragraph[:pos].strip())
            paragraph = paragraph[pos:].strip()
        if paragraph:
            pieces.append(paragraph)
    return pieces


def translation_prompt(text: str, cfg: Settings) -> str:
    terms = []
    for line in cfg.glossary.splitlines():
        parts = re.split(r"\s*(?:=|→|\t)\s*", line, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[0].lower() in text.lower():
            terms.append(f"{parts[0]} 翻译成 {parts[1]}")
    prefix = "参考下面的翻译：\n" + "\n".join(terms) + "\n\n" if terms else ""
    style = ""
    if cfg.style == "学术论文":
        style = "使用严谨的学术表达，保留数字、单位、引文编号和公式。"
    elif cfg.style == "自然流畅":
        style = "使用自然流畅的表达，完整保留原意。"
    origin = f"（原文语言：{cfg.source}）" if cfg.source != "自动识别" else ""
    return f"{prefix}将以下文本翻译为{cfg.target}{origin}，注意只需要输出翻译后的结果，不要额外解释。{style}\n\n{text}"


def http_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # Never leak local content through ambient proxies or .netrc.
    session.headers["User-Agent"] = f"ZTrans/{APP_VERSION}"
    return session


def check_response(response):
    if 300 <= response.status_code < 400:
        raise UserError("服务返回了重定向，已阻止转发原文或密钥。请填写最终 API 地址。")
    if response.status_code >= 400:
        messages = {401: "密钥无效或未填写", 403: "服务拒绝访问", 404: "接口或模型不存在", 429: "请求过多或额度不足"}
        raise UserError(f"服务返回 HTTP {response.status_code}：{messages.get(response.status_code, '请检查地址、模型或服务状态')}。")


def ollama_root(url: str) -> str:
    return re.sub(r"/api(?:/(?:chat|generate|tags))?$", "", normalize_url(url))


def api_endpoint(url: str, resource: str) -> str:
    base = normalize_url(url)
    base = re.sub(r"/(?:chat/completions|models)$", "", base)
    if not urlsplit(base).path:
        base += "/v1"
    return base + "/" + resource


def get_models(cfg: Settings) -> list[str]:
    validate_destination(cfg)
    with http_session() as session:
        headers = {}
        if cfg.provider == "api" and cfg.api_key:
            headers["Authorization"] = "Bearer " + cfg.api_key
        url = ollama_root(cfg.base_url) + "/api/tags" if cfg.provider == "ollama" else api_endpoint(cfg.base_url, "models")
        try:
            with session.get(url, headers=headers, timeout=(5, 15), allow_redirects=False) as response:
                check_response(response)
                data = response.json()
            if cfg.provider == "ollama":
                return [m["name"] for m in data.get("models", []) if not m.get("remote_host") and "cloud" not in m["name"].lower()]
            return [m["id"] for m in data.get("data", [])]
        except requests.RequestException:
            raise UserError("无法连接服务。请确认 Ollama 已运行，或检查 API 地址和网络。")


class Translator:
    def __init__(self, cfg: Settings, cancel: threading.Event | None = None):
        self.cfg = cfg
        self.cancel = cancel or threading.Event()

    def translate(self, text: str, on_token=lambda token: None) -> str:
        validate_destination(self.cfg)
        if self.cancel.is_set():
            raise Cancelled()
        cfg = self.cfg
        prompt = translation_prompt(text, cfg)
        headers = {}
        payload = {"model": cfg.model, "messages": [{"role": "user", "content": prompt}], "stream": True}
        if cfg.provider == "ollama":
            url = ollama_root(cfg.base_url) + "/api/chat"
            payload.update(options={"temperature": 0.3, "num_ctx": 8192, "num_predict": 4096}, keep_alive="5m")
        else:
            url = api_endpoint(cfg.base_url, "chat/completions")
            payload.update(temperature=0.2, max_tokens=4096)
            if cfg.api_key:
                headers["Authorization"] = "Bearer " + cfg.api_key
        output, finished = [], False
        try:
            with http_session() as session:
                if cfg.provider == "ollama":
                    with session.post(ollama_root(cfg.base_url) + "/api/show", json={"model": cfg.model}, timeout=(5, 15), allow_redirects=False) as meta:
                        check_response(meta)
                        info = meta.json()
                    if info.get("remote_host") or info.get("remote_model"):
                        raise UserError("此 Ollama 模型实际转发到云端，已阻止发送。请选择本地模型。")
                if self.cancel.is_set():
                    raise Cancelled()
                with session.post(url, json=payload, headers=headers, timeout=(10, 90), stream=True, allow_redirects=False) as response:
                    check_response(response)
                    response.encoding = "utf-8"
                    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                        if self.cancel.is_set():
                            raise Cancelled()
                        if not line or line.startswith(":"):
                            continue
                        if cfg.provider == "api":
                            if not line.startswith("data:"):
                                continue
                            line = line[5:].strip()
                            if line == "[DONE]":
                                finished = True
                                break
                        data = json.loads(line)
                        if data.get("error"):
                            raise UserError("模型服务返回错误，请检查模型是否可用。")
                        if cfg.provider == "ollama":
                            token = data.get("message", {}).get("content", "")
                            if data.get("done"):
                                if data.get("done_reason") == "length":
                                    raise UserError("模型输出达到长度限制，当前片段可能不完整。请缩短原文后重试。")
                                finished = True
                        else:
                            choices = data.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            token = choice.get("delta", {}).get("content") or ""
                            reason = choice.get("finish_reason")
                            if reason in ("length", "content_filter", "tool_calls"):
                                raise UserError("模型未完整返回译文，请换模型或缩短原文。")
                            if reason == "stop":
                                finished = True
                        if token:
                            output.append(token)
                            on_token(token)
                    if self.cancel.is_set():
                        raise Cancelled()
        except requests.RequestException:
            if self.cancel.is_set():
                raise Cancelled()
            raise UserError("连接中断或等待超时。已保留当前译文；请检查服务后重试。")
        except (ValueError, KeyError, TypeError):
            raise UserError("API 返回格式不符合流式聊天接口，请检查服务兼容性。")
        result = "".join(output).strip()
        if not finished or not result:
            raise UserError("没有收到完整译文。当前内容保留在右侧，请检查模型后重试。")
        return result
