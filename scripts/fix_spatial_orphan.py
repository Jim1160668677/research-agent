"""Remove leftover spatial block content from nextflow.py."""
from pathlib import Path

FILE = Path("src/research_agent/execution/nextflow.py")
lines = FILE.read_text().splitlines(keepends=True)

# Find and remove the leftover lines (the old spatial block's parameters section)
# Lines 231-246 are leftover
new_lines = []
skip_mode = False
for i, line in enumerate(lines):
    # Skip the leftover spatial parameters block (lines 231-246 in 1-indexed)
    stripped = line.rstrip()
    if stripped == '        "parameters": {':
        # Check if this is inside the leftover block by looking ahead
        # The pattern is: "parameters": { with visium/xenium/merfish/seqfish values
        look_ahead = ''.join(lines[i:i+10])
        if 'merfish' in look_ahead and 'seqfish' in look_ahead:
            skip_mode = True
            continue
    if skip_mode:
        if stripped == '    },':
            skip_mode = False
            continue
        continue
    new_lines.append(line)

FILE.write_text(''.join(new_lines))
print("Removed leftover spatial block")
