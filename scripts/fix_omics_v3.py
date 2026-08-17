path = r'tests\test_execution_nextflow.py'
with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

# Fix the CSV content to have data rows
c = c.replace(
    "(tmp_path / 'proteomics.csv').write_text('protein,id,count\\n', encoding='utf-8')",
    "(tmp_path / 'proteomics.csv').write_text('protein,id,count\\nP1,XYZ,100\\n', encoding='utf-8')"
)
c = c.replace(
    "(tmp_path / 'metabolites.csv').write_text('metabolite,intensity\\n', encoding='utf-8')",
    "(tmp_path / 'metabolites.csv').write_text('metabolite,intensity\\nM1,200\\n', encoding='utf-8')"
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)
print('Done')
