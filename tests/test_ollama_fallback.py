"""Tests for Ollama offline provider and fallback logic."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "src")

from research_agent.llm.provider import LLMMessage, LLMProviderError, OllamaProvider


class TestOllamaProvider:
    """Test the Ollama local model provider."""

    def test_descriptor(self):
        desc = OllamaProvider.descriptor()
        assert desc["name"] == "ollama"
        assert desc["display_name"] == "Ollama (Local)"
        assert desc["execution_mode"] == "sdk"
        assert "llama3" in desc["models"]
        assert desc["base_url"] == "http://localhost:11434/v1"
        assert desc["requires_runtime"] is None

    def test_check_connection_no_key(self):
        """Ollama should always be considered configured (no key needed)."""
        provider = OllamaProvider()
        assert provider.check_connection() is True

    def test_init_with_custom_base_url(self):
        provider = OllamaProvider(model="mistral", config={"base_url": "http://my-ollama:11434/v1"})
        assert provider.model == "mistral"
        assert provider._base_url == "http://my-ollama:11434/v1"

    def test_init_defaults(self):
        provider = OllamaProvider()
        assert provider.model == "llama3"
        assert provider._base_url == "http://localhost:11434/v1"
        assert provider.api_key == ""

    @pytest.mark.asyncio
    async def test_health_check_not_live(self):
        provider = OllamaProvider()
        result = await provider.health_check(live=False)
        assert result["success"] is True
        assert result["code"] == "configured"
        assert result["provider"] == "ollama"

    @pytest.mark.asyncio
    async def test_health_check_live_success(self):
        provider = OllamaProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.AsyncClient") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_ctx.return_value = mock_client
            result = await provider.health_check(live=True)
        assert result["success"] is True
        assert result["code"] == "ok"
        mock_client.get.assert_called_once_with("http://localhost:11434")

    @pytest.mark.asyncio
    async def test_health_check_live_unreachable(self):
        provider = OllamaProvider()
        with patch("httpx.AsyncClient") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=ConnectionError("Connection refused"))
            mock_ctx.return_value = mock_client
            result = await provider.health_check(live=True)
        assert result["success"] is False
        assert result["code"] == "unreachable"

    @pytest.mark.asyncio
    async def test_chat_success(self):
        provider = OllamaProvider(model="llama3")
        messages = [LLMMessage(role="user", content="Hello")]

        mock_choice = MagicMock()
        mock_choice.message.content = "Hi there!"
        mock_choice.message.tool_calls = None

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 5
        mock_usage.completion_tokens = 10
        mock_usage.total_tokens = 15

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "llama3"

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_async_client):
            result = await provider.chat(messages)

        assert result.content == "Hi there!"
        assert result.provider == "ollama"
        assert result.model == "llama3"
        assert result.usage["prompt_tokens"] == 5
        assert result.usage["completion_tokens"] == 10
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_chat_empty_content(self):
        provider = OllamaProvider(model="llama3")
        messages = [LLMMessage(role="user", content="Test")]

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = None

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 0
        mock_usage.completion_tokens = 0
        mock_usage.total_tokens = 0

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "llama3"

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_async_client):
            result = await provider.chat(messages)

        assert result.content == ""

    @pytest.mark.asyncio
    async def test_chat_connection_error(self):
        provider = OllamaProvider(model="llama3")
        messages = [LLMMessage(role="user", content="Hello")]

        mock_async_client = MagicMock()
        mock_async_client.chat.completions.create = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )

        with patch("openai.AsyncOpenAI", return_value=mock_async_client):
            with pytest.raises(LLMProviderError) as exc_info:
                await provider.chat(messages)
        assert exc_info.value.code == "connection_failed"


class TestOllamaFallback:
    """Test Ollama fallback logic in ChatEngine."""

    @pytest.mark.asyncio
    async def test_preferred_provider_fallback_to_ollama(self, monkeypatch):
        """When no cloud providers configured, should probe Ollama."""
        from research_agent.llm.chat import ChatEngine

        engine = ChatEngine(user_id=1)
        # No DB, no keys configured
        monkeypatch.setattr("research_agent.llm.chat._db_available", False)

        # Mock httpx probe to succeed
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.AsyncClient") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_ctx.return_value = mock_client
            provider_name, model = await engine._preferred_provider_model()

        assert provider_name == "ollama"
        assert model == "llama3"

    @pytest.mark.asyncio
    async def test_preferred_provider_no_ollama(self, monkeypatch):
        """When Ollama not available, should fall back to openai default."""
        from research_agent.llm.chat import ChatEngine

        engine = ChatEngine(user_id=1)
        monkeypatch.setattr("research_agent.llm.chat._db_available", False)

        # Mock httpx probe to fail
        with patch("httpx.AsyncClient") as mock_ctx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("refused"))
            mock_ctx.return_value = mock_client
            provider_name, model = await engine._preferred_provider_model()

        assert provider_name == "openai"
