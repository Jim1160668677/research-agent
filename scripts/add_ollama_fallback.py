"""Add OllamaProvider with offline fallback support."""
import re

# ============================================================================
# 1. provider.py - Add OllamaProvider class and registry entry
# ============================================================================
provider_path = "src/research_agent/llm/provider.py"
with open(provider_path, "r", encoding="utf-8") as f:
    content = f.read()

# Insert OllamaProvider class before PROVIDER_REGISTRY
ollama_class = '''
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

'''

# Insert OllamaProvider before PROVIDER_REGISTRY
content = content.replace(
    '\nPROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {',
    ollama_class + '\nPROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {',
    1
)

# Add ollama to PROVIDER_REGISTRY
content = content.replace(
    '    "google": GeminiProvider,\n}',
    '    "google": GeminiProvider,\n    "ollama": OllamaProvider,\n}',
    1
)

# Add OllamaProvider to __all__
content = content.replace(
    '    "GeminiProvider",\n    "PROVIDER_REGISTRY",',
    '    "GeminiProvider",\n    "OllamaProvider",\n    "PROVIDER_REGISTRY",',
    1
)

with open(provider_path, "w", encoding="utf-8") as f:
    f.write(content)
print("provider.py updated")

# ============================================================================
# 2. keys.py - Add ollama to ENV_KEY_MAP (empty string, no key needed)
# ============================================================================
keys_path = "src/research_agent/llm/keys.py"
with open(keys_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    '    "google": "GOOGLE_API_KEY",\n}',
    '    "google": "GOOGLE_API_KEY",\n    "ollama": "",  # Ollama requires no API key\n}',
    1
)

with open(keys_path, "w", encoding="utf-8") as f:
    f.write(content)
print("keys.py updated")

# ============================================================================
# 3. __init__.py - Export OllamaProvider
# ============================================================================
init_path = "src/research_agent/llm/__init__.py"
with open(init_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    '    get_provider,\n    provider_descriptors,\n)',
    '    get_provider,\n    provider_descriptors,\n    OllamaProvider,\n)',
    1
)

content = content.replace(
    '    "get_provider",\n    "APIKeyManager",',
    '    "get_provider",\n    "OllamaProvider",\n    "APIKeyManager",',
    1
)

with open(init_path, "w", encoding="utf-8") as f:
    f.write(content)
print("__init__.py updated")

# ============================================================================
# 4. chat.py - Add Ollama probe in _preferred_provider_model and fallback in chat()
# ============================================================================
chat_path = "src/research_agent/llm/chat.py"
with open(chat_path, "r", encoding="utf-8") as f:
    content = f.read()

# Add Ollama import
content = content.replace(
    'from .provider import LLMMessage, LLMProvider, get_provider',
    'from .provider import LLMMessage, LLMProvider, LLMProviderError, get_provider',
    1
)

# Add Ollama fallback probe in _preferred_provider_model (before final return)
old_return = '        return "openai", getattr(settings, "openai_model", "")'
new_return = '''        # Offline fallback: probe local Ollama instance
        try:
            import httpx
            resp = await httpx.AsyncClient(timeout=3).get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                return "ollama", "llama3"
        except Exception:
            pass  # Ollama not available

        return "openai", getattr(settings, "openai_model", "")'''
content = content.replace(old_return, new_return, 1)

# Add Ollama fallback in chat() method
old_chat_call = '''        provider = await self._get_provider()
        operation_id = self.session_id or f"user-{self.user_id or 'anonymous'}"
        async with get_runtime_coordinator().lease("llm", operation_id):
            response = await provider.chat(messages, **kwargs)

        # 记录对话到内存'''

new_chat_call = '''        provider = await self._get_provider()
        operation_id = self.session_id or f"user-{self.user_id or 'anonymous'}"
        response = None
        _used_ollama = False
        try:
            async with get_runtime_coordinator().lease("llm", operation_id):
                response = await provider.chat(messages, **kwargs)
        except LLMProviderError as _err:
            logger.warning("Primary provider failed ({}): {}, trying Ollama fallback", provider.name, _err.code)
            if provider.name != "ollama":
                try:
                    from .provider import OllamaProvider
                    ollama = OllamaProvider(model="llama3")
                    async with get_runtime_coordinator().lease("llm", operation_id):
                        response = await ollama.chat(messages, **kwargs)
                    _used_ollama = True
                    logger.info("Fell back to Ollama successfully")
                except Exception as _ollama_err:
                    logger.error("Ollama fallback also failed: {}", _ollama_err)
                    raise RuntimeError(
                        f"All LLM providers failed: primary={_err}, ollama={_ollama_err}"
                    ) from _ollama_err
            else:
                raise

        if response is None:
            raise RuntimeError("LLM call returned no response from any provider")

        # 记录对话到内存'''
content = content.replace(old_chat_call, new_chat_call, 1)

with open(chat_path, "w", encoding="utf-8") as f:
    f.write(content)
print("chat.py updated")

print("\n=== All files updated successfully ===")
