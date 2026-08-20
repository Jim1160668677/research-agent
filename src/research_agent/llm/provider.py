"""Stable LLM provider adapters used by every agent entry point.

The module keeps provider-specific transport details behind one contract.  In
particular, DeepSeek uses its official OpenAI-compatible API while Agnes is
executed through the version-pinned ``agnes-ai-cli`` as required by the Agnes
integration contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from packaging.version import InvalidVersion, Version
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential


@dataclass
class LLMMessage:
    """A normalized text message."""

    role: str
    content: str


@dataclass
class LLMResponse:
    """A normalized provider response."""

    content: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None
    attempts: int = 1
    latency_ms: int = 0


class LLMProviderError(RuntimeError):
    """Sanitized transport error shared by API, UI and orchestrators."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        code: str = "provider_error",
        retriable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.retriable = retriable
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "code": self.code,
            "message": str(self),
            "retriable": self.retriable,
            "status_code": self.status_code,
        }


def _error_details(error: BaseException, provider: str) -> LLMProviderError:
    """Map SDK/CLI failures without leaking request headers or credentials."""

    if isinstance(error, LLMProviderError):
        return error
    status = getattr(error, "status_code", None)
    name = error.__class__.__name__.lower()
    text = str(error).strip()
    if status in {401, 403} or "authentication" in name or "permission" in name:
        return LLMProviderError(
            "认证失败，请检查 API Key 与账户权限。",
            provider=provider,
            code="authentication_failed",
            status_code=status,
        )
    if status == 429 or "ratelimit" in name or "rate limit" in text.lower():
        return LLMProviderError(
            "模型服务达到速率限制，请稍后重试。",
            provider=provider,
            code="rate_limited",
            retriable=True,
            status_code=status,
        )
    if status in {408, 409} or (isinstance(status, int) and status >= 500):
        return LLMProviderError(
            "模型服务暂时不可用。",
            provider=provider,
            code="upstream_unavailable",
            retriable=True,
            status_code=status,
        )
    if isinstance(error, asyncio.TimeoutError | TimeoutError) or "timeout" in name:
        return LLMProviderError(
            "模型调用超时。",
            provider=provider,
            code="timeout",
            retriable=True,
            status_code=status,
        )
    if any(token in name for token in ("connection", "connect", "network")):
        return LLMProviderError(
            "无法连接模型服务。",
            provider=provider,
            code="connection_failed",
            retriable=True,
            status_code=status,
        )
    # Provider messages can contain endpoints or payload fragments.  Keep a
    # short diagnostic while removing common bearer/key patterns.
    safe = re.sub(r"(?i)(bearer\s+|api[_ -]?key[=: ]+)[^\s,;]+", r"\1***", text)[:300]
    return LLMProviderError(
        safe or "模型调用失败。",
        provider=provider,
        code="invalid_request" if status == 400 else "provider_error",
        status_code=status,
    )


def _retryable(error: BaseException) -> bool:
    return _error_details(error, getattr(error, "provider", "unknown")).retriable


class LLMProvider(ABC):
    """Provider contract with capability metadata and an optional live probe."""

    name: str = "base"
    display_name: str = "Base Provider"
    models: list[str] = []
    execution_mode: str = "sdk"
    capabilities: tuple[str, ...] = ("text",)
    default_base_url: str = ""
    requires_runtime: str = ""

    def __init__(self, api_key: str = "", model: str = "", config: dict[str, Any] = None):
        self.api_key = api_key
        self.model = model or (self.models[0] if self.models else "")
        self.config = config or {}

    @abstractmethod
    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Send a normalized chat request."""

    def check_connection(self) -> bool:
        """Local configuration check retained for backwards compatibility."""

        return bool(self.api_key and len(self.api_key) >= 10)

    async def health_check(self, *, live: bool = False) -> dict[str, Any]:
        """Return configuration health; a live probe is explicit and billable."""

        base = {
            "provider": self.name,
            "model": self.model,
            "configured": self.check_connection(),
            "execution_mode": self.execution_mode,
            "runtime": self.requires_runtime or None,
            "live": live,
        }
        if not base["configured"]:
            return {
                **base,
                "success": False,
                "code": "missing_api_key",
                "message": "API Key 未配置。",
            }
        if not live:
            return {
                **base,
                "success": True,
                "code": "configured",
                "message": "本地配置完整，尚未发起网络请求。",
            }
        started = time.perf_counter()
        try:
            response = await self.chat(
                [LLMMessage(role="user", content="Reply with exactly pong.")],
                temperature=0,
                max_tokens=16,
            )
            return {
                **base,
                "success": bool(response.content.strip()),
                "code": "ok",
                "message": "模型连接与最小生成请求成功。",
                "latency_ms": response.latency_ms or int((time.perf_counter() - started) * 1000),
                "attempts": response.attempts,
            }
        except Exception as error:
            detail = _error_details(error, self.name)
            return {**base, "success": False, **detail.to_dict()}

    def _mask_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return self.api_key[:6] + "..." + self.api_key[-4:]

    @classmethod
    def descriptor(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "display_name": cls.display_name,
            "models": list(cls.models),
            "execution_mode": cls.execution_mode,
            "capabilities": list(cls.capabilities),
            "base_url": cls.default_base_url or None,
            "requires_runtime": cls.requires_runtime or None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.descriptor(),
            "model": self.model,
            "configured": bool(self.api_key),
            "key_masked": self._mask_key(),
        }


class OpenAICompatibleProvider(LLMProvider):
    """Shared, bounded-retry adapter for OpenAI-compatible chat APIs."""

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        from openai import AsyncOpenAI

        if not self.api_key:
            raise LLMProviderError("API Key 未配置。", provider=self.name, code="missing_api_key")

        timeout = min(max(float(self.config.get("timeout_seconds", 45)), 1.0), 300.0)
        retries = min(max(int(self.config.get("max_retries", 2)), 0), 5)
        client_options: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": timeout,
            # Tenacity owns retries so attempt counts and backoff are visible.
            "max_retries": 0,
        }
        base_url = self.config.get("base_url") or self.default_base_url
        if base_url:
            client_options["base_url"] = base_url
        client = AsyncOpenAI(**client_options)
        payload = [{"role": message.role, "content": message.content} for message in messages]
        request: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "temperature": kwargs.get("temperature", 0.1),
            "max_tokens": kwargs.get("max_tokens", 2000),
        }
        request.update(self._provider_request(kwargs))
        attempts = 0
        started = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(retries + 1),
                wait=wait_random_exponential(
                    multiplier=float(self.config.get("retry_min_seconds", 0.25)),
                    max=float(self.config.get("retry_max_seconds", 2.0)),
                ),
                retry=retry_if_exception(_retryable),
                reraise=True,
            ):
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    response = await client.chat.completions.create(**request)
            message = response.choices[0].message
            usage = response.usage
            return LLMResponse(
                content=message.content or "",
                provider=self.name,
                model=getattr(response, "model", None) or self.model,
                usage={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                },
                raw=response,
                attempts=max(attempts, 1),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as error:
            detail = _error_details(error, self.name)
            logger.warning(
                "{} model call failed: code={} attempts={}", self.name, detail.code, attempts
            )
            raise detail from error

    def _provider_request(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {}


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    display_name = "OpenAI"
    models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]
    default_base_url = "https://api.openai.com/v1"


class DeepSeekProvider(OpenAICompatibleProvider):
    """Current DeepSeek V4 adapter using the official OpenAI wire format."""

    name = "deepseek"
    display_name = "DeepSeek"
    models = ["deepseek-v4-pro", "deepseek-v4-flash"]
    default_base_url = "https://api.deepseek.com"
    capabilities = ("text", "reasoning", "tool_calling", "json")

    def _provider_request(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {}
        if kwargs.get("thinking", self.config.get("thinking_enabled", True)):
            request["reasoning_effort"] = kwargs.get(
                "reasoning_effort", self.config.get("reasoning_effort", "high")
            )
            request["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        return request


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    display_name = "Anthropic Claude"
    models = ["claude-sonnet-4-5", "claude-3-5-sonnet", "claude-3-opus", "claude-3-haiku"]

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        import anthropic

        if not self.api_key:
            raise LLMProviderError(
                "Anthropic API Key 未配置。", provider=self.name, code="missing_api_key"
            )
        client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            timeout=min(max(float(self.config.get("timeout_seconds", 45)), 1.0), 300.0),
            max_retries=min(max(int(self.config.get("max_retries", 2)), 0), 5),
        )
        system_parts = [message.content for message in messages if message.role == "system"]
        chat_messages = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role != "system"
        ]
        started = time.perf_counter()
        try:
            response = await client.messages.create(
                model=self.model,
                system="\n".join(system_parts) if system_parts else None,
                messages=chat_messages,
                temperature=kwargs.get("temperature", 0.1),
                max_tokens=kwargs.get("max_tokens", 2000),
            )
        except Exception as error:
            raise _error_details(error, self.name) from error
        content = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            usage={
                "prompt_tokens": getattr(response.usage, "input_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "output_tokens", 0) or 0,
            },
            raw=response,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class GeminiProvider(LLMProvider):
    name = "google"
    display_name = "Google Gemini"
    models = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"]

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        from google import genai
        from google.genai import types

        if not self.api_key:
            raise LLMProviderError(
                "Google API Key 未配置。", provider=self.name, code="missing_api_key"
            )
        client = genai.Client(api_key=self.api_key)
        system_parts = [message.content for message in messages if message.role == "system"]
        chat_parts = [message.content for message in messages if message.role != "system"]
        prompt = "\n".join(chat_parts)
        if system_parts:
            prompt = (
                f"System Instructions:\n{chr(10).join(system_parts)}\n\nUser Request:\n{prompt}"
            )
        started = time.perf_counter()
        try:
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=kwargs.get("temperature", 0.1),
                    max_output_tokens=kwargs.get("max_tokens", 2000),
                ),
            )
        except Exception as error:
            raise _error_details(error, self.name) from error
        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            content=response.text or "",
            provider=self.name,
            model=self.model,
            usage={
                "prompt_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(usage, "total_token_count", 0) or 0,
            },
            raw=response,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class AgnesCLIProvider(LLMProvider):
    """Agnes text adapter that executes the supported CLI without a shell."""

    name = "agnes"
    display_name = "Agnes AI"
    models = ["agnes-2.0-flash"]
    execution_mode = "cli"
    capabilities = ("text", "reasoning", "tool_calling", "multimodal")
    default_base_url = "https://apihub.agnes-ai.com/v1"
    requires_runtime = "Node.js >=20 + agnes-ai-cli >=0.1.0,<0.2.0"
    _minimum_cli = Version("0.1.0")
    _maximum_cli = Version("0.2.0")

    def __init__(self, api_key: str = "", model: str = "", config: dict[str, Any] = None):
        super().__init__(api_key, model, config)
        self._prefix: list[str] | None = None
        self._version: str | None = None

    def _command_prefix(self) -> list[str]:
        configured = self.config.get("cli_command")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured]
        local = shutil.which("agnes")
        if local:
            return [local]
        executable = shutil.which("npx.cmd" if os.name == "nt" else "npx")
        if not executable and os.name == "nt":
            executable = shutil.which("npx")
        if not executable:
            raise LLMProviderError(
                "Agnes 需要 Node.js 20+ 与 npx，当前未找到可执行文件。",
                provider=self.name,
                code="runtime_missing",
            )
        return [executable, "-y", "agnes-ai-cli@^0.1.0"]

    @staticmethod
    def _decode_json(stdout: str) -> dict[str, Any]:
        value = stdout.strip()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise LLMProviderError(
                "Agnes CLI 返回了无法解析的 JSON。",
                provider="agnes",
                code="invalid_cli_output",
            ) from error
        if not isinstance(parsed, dict):
            raise LLMProviderError(
                "Agnes CLI JSON 顶层必须是对象。",
                provider="agnes",
                code="invalid_cli_output",
            )
        return parsed

    async def _process(self, arguments: list[str], *, timeout: float) -> tuple[int, str, str]:
        prefix = self._prefix or self._command_prefix()
        self._prefix = prefix
        env = os.environ.copy()
        if self.api_key:
            env["AGNES_API_KEY"] = self.api_key
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            process = await asyncio.create_subprocess_exec(
                *prefix,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                **options,
            )
        except OSError as error:
            raise LLMProviderError(
                "无法启动 Agnes CLI。",
                provider=self.name,
                code="runtime_missing",
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as error:
            process.kill()
            await process.communicate()
            raise LLMProviderError(
                "Agnes CLI 执行超时。",
                provider=self.name,
                code="timeout",
                retriable=True,
            ) from error
        return (
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _ensure_compatible(self) -> str:
        if self._version:
            return self._version
        code, stdout, _ = await self._process(
            ["--version"], timeout=min(float(self.config.get("startup_timeout_seconds", 45)), 120)
        )
        value = stdout.strip().splitlines()[0] if stdout.strip() else ""
        try:
            version = Version(value)
        except InvalidVersion as error:
            raise LLMProviderError(
                "无法识别 Agnes CLI 版本。",
                provider=self.name,
                code="incompatible_runtime",
            ) from error
        if code != 0 or not (self._minimum_cli <= version < self._maximum_cli):
            raise LLMProviderError(
                f"Agnes CLI {version} 不在支持范围 >=0.1.0,<0.2.0。",
                provider=self.name,
                code="incompatible_runtime",
            )
        self._version = str(version)
        return self._version

    @staticmethod
    def _prompt(messages: list[LLMMessage]) -> str:
        labels = {"system": "System", "user": "User", "assistant": "Assistant"}
        # npx.cmd forwards arguments through cmd.exe on Windows. Literal CR/LF
        # characters can terminate the batch command, silently dropping
        # trailing flags such as --json. Keep the transport prompt one line.
        parts = []
        for message in messages:
            content = " ".join(str(message.content).splitlines()).strip()
            parts.append(f"[{labels.get(message.role, message.role.title())}] {content}")
        return " || ".join(parts)

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        if not self.api_key:
            raise LLMProviderError(
                "Agnes API Key 未配置。", provider=self.name, code="missing_api_key"
            )
        await self._ensure_compatible()
        timeout = min(max(float(self.config.get("timeout_seconds", 90)), 1.0), 600.0)
        retries = min(max(int(self.config.get("max_retries", 1)), 0), 3)
        command = [
            "text",
            "chat",
            "--prompt",
            self._prompt(messages),
            "--model",
            self.model,
            "--json",
        ]
        attempts = 0
        started = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(retries + 1),
                wait=wait_random_exponential(multiplier=0.25, max=2.0),
                retry=retry_if_exception(_retryable),
                reraise=True,
            ):
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    code, stdout, stderr = await self._process(command, timeout=timeout)
                    data = self._decode_json(stdout) if stdout.strip() else {}
                    if code != 0 or data.get("ok") is False:
                        cli_code = str(data.get("code") or "cli_error").lower()
                        retriable = any(
                            token in cli_code
                            for token in ("rate", "timeout", "network", "upstream")
                        )
                        message = str(data.get("message") or stderr or "Agnes CLI 执行失败")[:300]
                        raise LLMProviderError(
                            message,
                            provider=self.name,
                            code=cli_code,
                            retriable=retriable,
                        )
            raw = data.get("raw") if isinstance(data.get("raw"), dict) else data
            usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
            return LLMResponse(
                content=str(data.get("text") or "").strip(),
                provider=self.name,
                model=str(data.get("model") or self.model),
                usage={
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                },
                raw=data,
                attempts=max(attempts, 1),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as error:
            detail = _error_details(error, self.name)
            logger.warning("Agnes CLI call failed: code={} attempts={}", detail.code, attempts)
            raise detail from error

    async def health_check(self, *, live: bool = False) -> dict[str, Any]:
        base = await super().health_check(live=False)
        if not base["configured"]:
            return {**base, "live": live}
        try:
            version = await self._ensure_compatible()
        except Exception as error:
            detail = _error_details(error, self.name)
            return {**base, "success": False, "live": live, **detail.to_dict()}
        if live:
            result = await super().health_check(live=True)
            return {**result, "cli_version": version}
        return {
            **base,
            "success": True,
            "live": False,
            "code": "runtime_ready",
            "message": "API Key 与 Agnes CLI 运行时已就绪，尚未发起生成请求。",
            "cli_version": version,
        }


class OllamaProvider(LLMProvider):
    """Ollama local model provider via OpenAI-compatible API.

    Requires no API key. Falls back to local Ollama when cloud providers
    are unavailable (e.g. offline mode, network outage).
    """

    name = "ollama"
    display_name = "Ollama (Local)"
    models = ["llama3", "llama3.1", "mistral", "phi3", "qwen2.5", "smollm2", "nomic-embed-text"]
    execution_mode = "sdk"
    capabilities = ("text", "tool_calling", "json")
    default_base_url = "http://localhost:11434/v1"

    def __init__(self, api_key: str = "", model: str = "", config: dict[str, Any] = None):
        super().__init__(api_key, model, config)
        self._base_url = self.config.get("base_url") or self.default_base_url

    def check_connection(self) -> bool:
        """Ollama requires no API key – always considered configured."""
        return True

    async def chat(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        from openai import AsyncOpenAI

        timeout = min(max(float(self.config.get("timeout_seconds", 120)), 1.0), 600.0)
        retries = min(max(int(self.config.get("max_retries", 2)), 0), 5)
        client = AsyncOpenAI(
            api_key="ollama",
            base_url=self._base_url,
            timeout=timeout,
            max_retries=0,
        )
        payload = [{"role": message.role, "content": message.content} for message in messages]
        request: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "temperature": kwargs.get("temperature", 0.1),
            "max_tokens": kwargs.get("max_tokens", 2000),
        }
        if kwargs.get("stream", False):
            request["stream"] = True

        attempts = 0
        started = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(retries + 1),
                wait=wait_random_exponential(multiplier=0.5, max=3.0),
                retry=retry_if_exception(_retryable),
                reraise=True,
            ):
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    response = await client.chat.completions.create(**request)
            message = response.choices[0].message
            usage = response.usage
            return LLMResponse(
                content=message.content or "",
                provider=self.name,
                model=getattr(response, "model", None) or self.model,
                usage={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                },
                raw=response,
                attempts=max(attempts, 1),
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as error:
            detail = _error_details(error, self.name)
            logger.warning(
                "{} model call failed: code={} attempts={}", self.name, detail.code, attempts
            )
            raise detail from error

    async def health_check(self, *, live: bool = False) -> dict[str, Any]:
        base = {
            "provider": self.name,
            "model": self.model,
            "configured": True,
            "execution_mode": self.execution_mode,
            "live": live,
            "base_url": self._base_url,
        }
        if not live:
            return {
                **base,
                "success": True,
                "code": "configured",
                "message": "Ollama 本地配置完整，尚未发起网络请求。",
            }
        # Live probe: check if Ollama server is reachable
        started = time.perf_counter()
        try:
            import httpx
            resp = await httpx.AsyncClient(timeout=5).get(
                self._base_url.replace("/v1", ""),
            )
            if resp.status_code == 200:
                return {
                    **base,
                    "success": True,
                    "code": "ok",
                    "message": "Ollama 服务可用。",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            return {**base, "success": False, "code": "unreachable", "message": f"HTTP {resp.status_code}"}
        except Exception as error:
            return {**base, "success": False, "code": "unreachable", "message": str(error)}


PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "agnes": AgnesCLIProvider,
    "anthropic": AnthropicProvider,
    "google": GeminiProvider,
    "ollama": OllamaProvider,
}


def provider_descriptors() -> list[dict[str, Any]]:
    return [provider.descriptor() for provider in PROVIDER_REGISTRY.values()]


def get_provider(
    provider_name: str,
    api_key: str = "",
    model: str = "",
    config: dict[str, Any] = None,
) -> LLMProvider:
    provider_name = provider_name.lower().strip()
    cls = PROVIDER_REGISTRY.get(provider_name)
    if not cls:
        raise ValueError(f"未知Provider: {provider_name}，可用: {list(PROVIDER_REGISTRY.keys())}")
    if model and model not in cls.models:
        raise ValueError(f"{provider_name} 不支持模型 {model}，可用: {cls.models}")
    return cls(api_key=api_key, model=model, config=config)


__all__ = [
    "LLMProvider",
    "LLMMessage",
    "LLMResponse",
    "LLMProviderError",
    "OpenAIProvider",
    "DeepSeekProvider",
    "AgnesCLIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "PROVIDER_REGISTRY",
    "provider_descriptors",
    "get_provider",
]
