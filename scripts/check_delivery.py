"""Read-only checks; never print credential values."""
import hashlib
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
key=next((line.split('=',1)[1].strip().strip('"\'') for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines() if line.startswith('OPENAI_API_KEY=')),'')
leaks=[]
if key:
    revisions=subprocess.check_output(['git','rev-list','--all'],cwd=ROOT).decode().splitlines()
    for rev in revisions:
        p=subprocess.run(['git','grep','-l','-F','-f','-',rev],input=(key+'\n').encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT)
        if p.returncode==0:leaks.extend(p.stdout.decode('utf-8','replace').splitlines())
    for file in files:
        p=ROOT/file
        if p.is_file() and key.encode() in p.read_bytes():leaks.append(file)
original=ROOT/'项目终案_系统原型.html'
same=hashlib.sha256(original.read_bytes()).hexdigest().upper()=='A210CA449F7009CC03D70C5FBAF688F717791AC28E8F4DAB40A1787D20C60371'
env_ignored=subprocess.run(['git','check-ignore','.env'],cwd=ROOT,stdout=subprocess.DEVNULL).returncode==0
gitlinks=[line for line in subprocess.check_output(['git','ls-files','-s'],cwd=ROOT).decode('utf-8').splitlines() if line.startswith('160000')]
report={'credential_in_tracked_files_or_history':bool(leaks),'credential_leak_paths':leaks,'env_ignored':env_ignored,'prototype_unchanged':same,'gitlinks':gitlinks,'tracked_files':len([f for f in files if f])}
assert key and not leaks and env_ignored and same and not gitlinks,report
(ROOT/'artifacts/delivery-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
