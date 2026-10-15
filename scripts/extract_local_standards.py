import json
from pathlib import Path
import fitz
root=Path(__file__).resolve().parents[1]
out={}
for p in (root/'backend/data/extracted').glob('*.pdf'):
    if '脚手架' not in p.name and '风险' not in p.name:continue
    d=fitz.open(p)
    out[str(p.relative_to(root))]=[page.get_text() for page in d]
(root/'backend/data/extracted_text.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
print({Path(k).name:sum(map(len,v)) for k,v in out.items()})
