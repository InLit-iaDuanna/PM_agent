import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from pm_agent_worker.tools.json_parser import parse_first_json_object
from pm_agent_worker.tools.minimax_settings import is_placeholder_api_key
from pm_agent_worker.tools.openai_compatible_settings import (
    OpenAICompatibleConnectionSettings,
    OpenAICompatibleSettings,
    load_openai_compatible_settings,
)


class OpenAICompatibleChatClient:
    def __init__(self, settings: Optional[OpenAICompatibleSettings] = None) -> None:
        self.settings = settings or load_openai_compatible_settings()
        self._config_error: Optional[str] = None
        self._last_error: Optional[str] = None
        self._preferred_connection_index = 0
        self._last_successful_base_url = self.settings.base_url
        self._connection_backoff_until: Dict[int, float] = {}
        self._failover_cooldown_seconds = self._load_failover_cooldown_seconds()
        if not self._has_usable_connection():
            self._config_error = "OPENAI_COMPAT_API_KEY 未配置，或仍是占位值"

    def _load_failover_cooldown_seconds(self) -> float:
        try:
            return max(15.0, float(os.getenv("PM_AGENT_LLM_FAILOVER_COOLDOWN_SECONDS", "180")))
        except (TypeError, ValueError):
            return 180.0

    def _has_usable_connection(self) -> bool:
        return any(bool(connection.api_key) and not is_placeholder_api_key(connection.api_key) for connection in self.settings.connections)

    def is_enabled(self) -> bool:
        return self._config_error is None

    @property
    def disabled_reason(self) -> Optional[str]:
        return self._config_error

    def status_summary(self) -> Dict[str, Any]:
        validation_message = "兼容 OpenAI 运行时可用"
        validation_status = "valid"
        if self._config_error:
            validation_message = self._config_error
            validation_status = "invalid"
        elif not self._has_usable_connection():
            validation_message = "OPENAI_COMPAT_API_KEY 未配置"
            validation_status = "invalid"

        return {
            "provider": "openai_compatible",
            "model": self.settings.model,
            "llm_enabled": self.is_enabled(),
            "validation_status": validation_status,
            "validation_message": validation_message,
            "connection_count": len(self.settings.connections),
            "active_base_url": self._last_successful_base_url,
        }

    @property
    def active_base_url(self) -> str:
        return self._last_successful_base_url

    def _ordered_connections(self) -> List[tuple[int, OpenAICompatibleConnectionSettings]]:
        indexed_connections = list(enumerate(self.settings.connections))
        if not indexed_connections:
            return []
        preferred_index = min(self._preferred_connection_index, len(indexed_connections) - 1)
        rotated_connections = indexed_connections[preferred_index:] + indexed_connections[:preferred_index]
        now = time.monotonic()
        ready_connections = [item for item in rotated_connections if self._connection_backoff_until.get(item[0], 0) <= now]
        deferred_connections = [item for item in rotated_connections if self._connection_backoff_until.get(item[0], 0) > now]
        return ready_connections + deferred_connections if ready_connections else rotated_connections

    def _extract_content(self, data: Dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(f"兼容 OpenAI 返回结构异常：{json.dumps(data, ensure_ascii=False)[:400]}") from error

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            fragments: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text") or item.get("content") or "").strip()
                    if text:
                        fragments.append(text)
                else:
                    text = str(item or "").strip()
                    if text:
                        fragments.append(text)
            if fragments:
                return "\n".join(fragments)

        raise RuntimeError(f"兼容 OpenAI 内容结构异常：{json.dumps(data, ensure_ascii=False)[:400]}")

    def _extract_responses_content(self, data: Dict[str, Any]) -> str:
        output_text = str(data.get("output_text") or "").strip()
        if output_text:
            return output_text

        fragments: List[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = str(content.get("text") or "").strip()
                if text:
                    fragments.append(text)
        if fragments:
            return "\n".join(fragments)

        raise RuntimeError(f"兼容 OpenAI responses 结构异常：{json.dumps(data, ensure_ascii=False)[:400]}")

    def _flatten_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            fragments: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text") or item.get("content") or "").strip()
                    if text:
                        fragments.append(text)
                else:
                    text = str(item or "").strip()
                    if text:
                        fragments.append(text)
            return "\n".join(fragments).strip()
        return str(content or "").strip()

    def _build_responses_payload(
        self,
        messages: List[Dict[str, str]],
        connection: OpenAICompatibleConnectionSettings,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        input_items: List[Dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user").strip() or "user"
            text = self._flatten_message_content(message.get("content"))
            if not text:
                continue
            input_items.append(
                {
                    "role": role,
                    "content": [
                        {
                            "type": "input_text",
                            "text": text,
                        }
                    ],
                }
            )
        return {
            "model": connection.model,
            "input": input_items,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

    def _error_text(self, error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            body = error.response.text.strip()
            if body:
                return f"{error}; body={body[:400]}"
        return str(error)

    def _should_back_off_connection(self, error: Exception) -> bool:
        if isinstance(error, httpx.RequestError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {408, 409, 425, 429} or error.response.status_code >= 500
        return False

    def _mark_connection_failed(self, connection_index: int, error: Exception) -> None:
        if not self._should_back_off_connection(error):
            return
        self._connection_backoff_until[connection_index] = time.monotonic() + self._failover_cooldown_seconds

    def _mark_connection_succeeded(self, connection_index: int, connection: OpenAICompatibleConnectionSettings) -> None:
        self._preferred_connection_index = connection_index
        self._last_successful_base_url = connection.base_url
        self._last_error = None
        self._connection_backoff_until.pop(connection_index, None)

    def _build_timeout(self, timeout_seconds: float) -> httpx.Timeout:
        safe_timeout = max(5.0, float(timeout_seconds or 45.0))
        return httpx.Timeout(
            timeout=safe_timeout,
            connect=min(10.0, safe_timeout),
            read=safe_timeout,
            write=min(20.0, safe_timeout),
            pool=min(10.0, safe_timeout),
        )

    def complete(self, messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 1800) -> str:
        if not self.is_enabled():
            if self._config_error:
                raise RuntimeError(f"兼容 OpenAI 客户端不可用：{self._config_error}")
            raise RuntimeError("OPENAI_COMPAT_API_KEY 未配置")

        last_error: Optional[Exception] = None
        for connection_index, connection in self._ordered_connections():
            payload = {
                "model": connection.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            headers = {
                "Authorization": f"Bearer {connection.api_key}",
                "Content-Type": "application/json",
            }
            connection_error: Optional[Exception] = None
            for url in connection.chat_completions_urls:
                try:
                    with httpx.Client(timeout=self._build_timeout(connection.timeout_seconds)) as client:
                        response = client.post(url, headers=headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                    self._mark_connection_succeeded(connection_index, connection)
                    return self._extract_content(data)
                except (httpx.HTTPError, ValueError, RuntimeError) as error:
                    last_error = error
                    connection_error = error
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {404, 405}:
                        break

            responses_payload = self._build_responses_payload(messages, connection, temperature=temperature, max_tokens=max_tokens)
            for url in connection.responses_urls:
                try:
                    with httpx.Client(timeout=self._build_timeout(connection.timeout_seconds)) as client:
                        response = client.post(url, headers=headers, json=responses_payload)
                        response.raise_for_status()
                        data = response.json()
                    self._mark_connection_succeeded(connection_index, connection)
                    return self._extract_responses_content(data)
                except (httpx.HTTPError, ValueError, RuntimeError) as error:
                    last_error = error
                    connection_error = error
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {404, 405}:
                        break
            if connection_error is not None:
                self._mark_connection_failed(connection_index, connection_error)

        self._last_error = self._error_text(last_error or RuntimeError("未知请求错误"))
        raise RuntimeError(f"兼容 OpenAI 请求失败：{self._last_error}") from last_error

    def complete_json(self, messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int = 1800) -> Any:
        content = self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        return parse_first_json_object(content)
