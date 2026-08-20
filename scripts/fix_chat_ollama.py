"""Fix chat.py to replace broken Ollama fallback line with proper implementation."""
import re

path = "src/research_agent/llm/chat.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_block = """        # Fallback to Ollama if primary provider fails
        if response is None or response.provider == ""

        # 记录对话到内存"""

new_block = """        # Fallback to Ollama if primary provider fails
        _fallback_to_ollama = False
        try:
            from .provider import OllamaProvider
            response = await provider.chat(messages, **kwargs)
        except Exception as _fallback_err:
            logger.warning("Primary provider failed: {}, trying Ollama fallback", _fallback_err)
            try:
                ollama = OllamaProvider(model="llama3")
                response = await ollama.chat(messages, **kwargs)
                _fallback_to_ollama = True
            except Exception as _ollama_err:
                logger.error("Ollama fallback also failed: {}", _ollama_err)
                raise RuntimeError(
                    f"All LLM providers failed: primary={_fallback_err}, ollama={_ollama_err}"
                ) from _ollama_err

        # 记录对话到内存"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed chat.py successfully")
else:
    print("ERROR: old_block not found")
    # Debug: show lines around 245
    lines = content.split("\n")
    for i in range(240, min(260, len(lines))):
        print(f"  {i+1}: {repr(lines[i])}")
