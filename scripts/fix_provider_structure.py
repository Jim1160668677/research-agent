"""Fix provider.py structure: move OllamaProvider before PROVIDER_REGISTRY."""
path = "src/research_agent/llm/provider.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find key line numbers
registry_start = None
registry_end = None
ollama_class_start = None
ollama_all_start = None
for i, line in enumerate(lines):
    if line.strip() == "PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {":
        registry_start = i
    if registry_start is not None and line.strip() == "}" and i > registry_start:
        registry_end = i
        break
    if 'class OllamaProvider(LLMProvider):' in line:
        ollama_class_start = i
    if '"OllamaProvider",' in line and ollama_class_start and i < ollama_class_start:
        ollama_all_start = i

print(f"registry_start={registry_start}, registry_end={registry_end}")
print(f"ollama_class_start={ollama_class_start}, ollama_all_start={ollama_all_start}")

# Reconstruct: keep everything before registry_start, then OllamaProvider class, then fixed registry, then rest
before_registry = lines[:registry_start]
ollama_class_lines = lines[ollama_class_start:registry_start]  # OllamaProvider class
# Build new PROVIDER_REGISTRY with ollama included
new_registry = (
    lines[registry_start:registry_end + 1]  # original dict minus the stray line
).copy()
# Remove the stray "ollama" line from inside the file
rest_after_registry = lines[registry_end + 1:]

# Filter out the broken line
clean_rest = [l for l in rest_after_registry if '"ollama": OllamaProvider,' not in l]

# Add ollama to registry
registry_line_idx = None
for i, l in enumerate(new_registry):
    if '"google": GeminiProvider,' in l:
        registry_line_idx = i
        break
if registry_line_idx is not None:
    new_registry.insert(registry_line_idx + 1, '    "ollama": OllamaProvider,\n')

# Find where __all__ ends so we can add OllamaProvider there too
all_start = None
all_end = None
for i, line in enumerate(before_registry):
    if line.strip().startswith('__all__'):
        all_start = i
for i, line in enumerate(before_registry):
    if all_start is not None and line.strip() == ']':
        all_end = i
        break

new_all = before_registry[:all_end] + ['    "OllamaProvider",\n'] + before_registry[all_end:]

final = new_all + ollama_class_lines + ['\n\n'] + new_registry + ['\n'] + clean_rest

with open(path, "w", encoding="utf-8") as f:
    f.writelines(final)

print(f"Fixed! Total lines: {len(final)}")
