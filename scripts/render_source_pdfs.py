"""Use the installed PyMuPDF interpreter to prepare scanned sources for Windows OCR."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import fitz

ROOT=Path(__file__).resolve().parents[1]
base=ROOT/'backend/data/ocr'
base.mkdir(parents=True,exist_ok=True)
result=[]
for path in (ROOT/'施工安全RAG知识源').rglob('*.pdf'):
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    out=base/sha
    out.mkdir(exist_ok=True)
    doc=fitz.open(path)
    textual=sum(len(p.get_text().strip()) for p in doc)
    scanned=textual<200*len(doc)
    if scanned:
        for i,p in enumerate(doc):
            target=out/f'{i+1:04d}.png'
            if not target.exists():p.get_pixmap(matrix=fitz.Matrix(2.5,2.5)).save(target)
        subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/ocr_windows.ps1'),str(out)],check=True)
    result.append({'file':str(path.relative_to(ROOT)),'pages':len(doc),'scanned':scanned,'sha256':sha})
    print(path.name,len(doc),'OCR' if scanned else 'text',flush=True)
(base/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
