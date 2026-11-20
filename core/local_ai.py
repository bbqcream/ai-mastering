"""Local Ollama JSON planning. No account or paid inference service is used."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


def _reject_constant(value):
    raise ValueError(f"유한한 JSON 숫자가 필요합니다: {value}")


class LocalAI:
    def __init__(self, model="qwen3:8b", url="http://127.0.0.1:11434", timeout=600):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("로컬 Ollama 주소를 사용하세요 (http://127.0.0.1:11434)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama 주소 형식이 유효하지 않습니다")
        if "cloud" in model.casefold() or "/" in model:
            raise ValueError("로컬에서 실행하는 Ollama 모델을 선택하세요")
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.http = build_opener(ProxyHandler({}))

    def request(self, endpoint, data=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.url + endpoint, data=body, headers={"Content-Type": "application/json"})
        try:
            with self.http.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Ollama HTTP {exc.code}: 모델 설치와 서버 상태를 확인하세요") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError("로컬 Ollama에 연결할 수 없습니다. Ollama 실행 상태를 확인하세요") from exc

    def check(self):
        tags = self.request("/api/tags")
        installed = {entry["name"] for entry in tags.get("models", [])}
        if self.model not in installed and self.model + ":latest" not in installed:
            raise RuntimeError(f"로컬 모델이 없습니다. ollama pull {self.model}")

    def decide(self, instructions, context, schema):
        messages = [
            {"role": "system", "content": instructions + "\nReturn JSON matching this schema:\n" + json.dumps(schema)},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, allow_nan=False)},
        ]
        for attempt in range(3):
            response = self.request("/api/chat", {
                "model": self.model, "messages": messages, "stream": False,
                "format": schema, "think": False,
                "options": {"temperature": 0, "num_ctx": 16384},
            })
            try:
                result = json.loads(response["message"]["content"], parse_constant=_reject_constant)
                from jsonschema import validate
                validate(result, schema)
                return result
            except (ValueError, KeyError, TypeError) as exc:
                error = str(exc)
            except Exception as exc:
                from jsonschema.exceptions import ValidationError
                if not isinstance(exc, ValidationError):
                    raise
                error = str(exc)
            content = response.get("message", {}).get("content") if isinstance(response, dict) and isinstance(response.get("message"), dict) else None
            if isinstance(content, str) and content:
                messages.append({"role": "assistant", "content": content[:6000]})
            messages.append({"role": "user", "content": "Invalid response. Correct the JSON. " + error[:800]})
        raise RuntimeError("로컬 AI가 세 번 연속 유효한 처리안을 만들지 못했습니다")
