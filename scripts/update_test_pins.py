"""Update test_pipelines_api.py to reflect new pipeline revisions."""
from pathlib import Path

test_file = Path("tests/test_pipelines_api.py")
content = test_file.read_text()

old_assertion = '''    assert pins == {
        "nf-core/rnaseq": "3.26.0",
        "nf-core/sarek": "3.9.0",
        "nf-core/atacseq": "2.0.0",
        "nf-core/chipseq": "2.0.0",
        "nf-core/scrnaseq": "2.0.0",
        "nf-core/spatial": "1.0.0",
    }'''

new_assertion = '''    # Verify pipeline set (spatial replaced by spatialvi + spatialaxe)
    assert set(pins.keys()) == {
        "nf-core/rnaseq", "nf-core/sarek",
        "nf-core/atacseq", "nf-core/chipseq",
        "nf-core/scrnaseq", "nf-core/spatialvi", "nf-core/spatialaxe",
    }
    assert pins["nf-core/rnaseq"] == "3.26.0"
    assert pins["nf-core/sarek"] == "3.9.0"
    assert pins["nf-core/atacseq"] == "2.1.2"
    assert pins["nf-core/chipseq"] == "2.1.0"
    assert pins["nf-core/scrnaseq"] == "4.2.0"
    assert pins["nf-core/spatialvi"] == "0.1.0"
    assert pins["nf-core/spatialaxe"] == "1.0.1"'''

assert old_assertion in content, "Pattern not found in test file"
content = content.replace(old_assertion, new_assertion)
test_file.write_text(content)
print("Test file updated successfully")
