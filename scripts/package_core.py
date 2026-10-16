"""Build a small, credential-free runtime release; never changes the live database."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FOLDER='施工安全管理工作台'

README='''# 施工安全管理工作台 · 核心运行包

本包包含六页前端、FastAPI后端、干净种子库与检索索引、安全帽YOLO权重、4路回放视频、知识资料原文。无需旧工程源码。

## 安装启动（Windows，Python 3.11）

解压后，在此 README 所在目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010
```

浏览器打开 http://127.0.0.1:8010 。已安装依赖后，也可运行 `start.bat` 或 `start.ps1`。请勿与同端口的其他实例同时启动。

账号：AQ20260001 / AQ20260002（安全员）、AQ20260003（总监）；初始密码均为123456。

## 大模型与离线

出于密钥保护，本包不含 `.env` 或任何真实API密钥。在 `.env` 填写自己的 `OPENAI_API_KEY`；OpenAI兼容地址和DeepSeek/豆包Seed模型名见 `.env.example`。无密钥时自动使用有标识的离线原文检索/模板/规则兜底。

## 数据与能力边界

- `backend/data/app.db` 为干净种子库：6条历史隐患、4条独立待确认演示线索；无验收会话、文书、登录令牌或个人长期记忆。已解析内容保存在数据库，保留对应检索索引和原文，请勿删除数据库。
- 精简包保留75份知识来源，包括已解包的两项福建标准。排除约84MB、仅供重建原料用的RAR及对应未解析待核验归档记录；原项目文件与数据库未修改。不是75份都可引用，人工审核与有效性限制照常执行。
- 模型位置保留为 `construction-safety-inspection/models/helmet_yolo11n/weights/best.pt`，此目录仅包含运行必需权重，不包含旧工程。
- 权重、视频和知识资料均包含；Python与依赖环境需按上文安装。没有虚拟环境、开发历史、测试截图、训练数据、OCR图片缓存或API密钥。
- 模型只检测安全帽的两个头部类别；门禁人数与反光衣明确为演示数据，未接入RTSP/短信。抓拍必须人工核实后才能进入台账，文书必须人工确认签发。
- 原文问答与参考草稿不能替代现场安全判断。项目资料/案例不能作为正式法规依据，废止版本不允许新引用。

`MANIFEST.sha256` 提供所有打包文件的SHA256值。本包用于运行；完整开发测试证据与重建材料保留在原工作目录。
'''

VERIFY=r'''
import json,os,shutil,sqlite3,tempfile
from pathlib import Path
root=Path.cwd()
qa=Path(tempfile.mkdtemp(prefix='core-check-'))/'verify.db'
shutil.copy2(root/'backend/data/app.db',qa)
os.environ['APP_DB']=str(qa);os.environ['LLM_ENABLED']='0'
from backend.app.main import app
from backend.app import db
from backend.rag.knowledge import search
from fastapi.testclient import TestClient
with TestClient(app) as c:
    assert c.get('/').status_code==200
    for p in ['/static/app.js','/static/app.css']:assert c.get(p).status_code==200
    assert c.get('/api/hazards').status_code==401
    login=c.post('/api/auth/login',json={'username':'AQ20260001','password':'123456'});assert login.status_code==200
    c.headers['Authorization']='Bearer '+login.json()['data']['token']
    assert c.get('/api/hazards').json()['data']['counts']['all']==6
    sources=c.get('/api/kb/sources').json()['data'];assert sources['stats']['total']==75
    for s in sources['items']:
        assert (root/s['file_path']).is_file(),s['file_path']
        assert c.get('/api/kb/sources/'+str(s['id'])+'/file').status_code==200
    assert search('临边防护',for_document=True)[0]['doc_no']=='JGJ80-2016'
    assert search('临时用电接地',for_document=True)[0]['doc_no']=='JGJ/T46-2024'
    assert not search('火星量子计算机维修')
    response=c.post('/api/chat/stream',json={'message':'临边防护要求'});assert response.status_code==200
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['type']=='done' and events[-1]['mode']=='offline'
    assert '当前为离线兜底结果' in ''.join(e.get('content','') for e in events)
    cams=c.get('/api/monitor/overview').json()['data']['cameras'];assert len(cams)==4 and all(cam['available'] for cam in cams)
import cv2
from backend.vision.detector import model
cap=cv2.VideoCapture(str(root/'videos/cam03_workers.mp4'));ok,frame=cap.read();cap.release();assert ok
det=model().predict(frame,imgsz=1280,conf=.35,device='cpu',verbose=False)[0]
assert len(det.boxes)>0
print(json.dumps({'passed':True,'sources':75,'source_files_checked':75,'hazards':6,'camera_files':4,'offline_chat':True,'actual_yolo_frame_detections':len(det.boxes)}))
'''

def main():
    output=ROOT/'施工安全管理工作台_核心版_20261016.zip'
    if output.exists():raise FileExistsError(f'拒绝覆盖已有文件：{output.name}')
    seed=ROOT/'backend/data/delivery-20261016.db'
    if not seed.is_file():raise FileNotFoundError('缺少干净种子库，停止打包')
    key=next((s.split('=',1)[1].strip() for s in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines() if s.startswith('OPENAI_API_KEY=')),'')
    with tempfile.TemporaryDirectory(prefix='safety-core-package-') as temp:
        stage=Path(temp)/FOLDER;stage.mkdir()
        def copy(relative):
            relative=Path(relative);source=ROOT/relative;target=stage/relative
            if not source.is_file():raise FileNotFoundError(str(relative))
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        for base in ['backend/app','backend/agents','backend/rag','backend/vision']:
            for p in (ROOT/base).glob('*.py'):copy(p.relative_to(ROOT))
        copy('backend/__init__.py')
        for p in (ROOT/'frontend').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:copy(p.relative_to(ROOT))
        for name in ['requirements.txt','requirements-tested.txt','.env.example','start.ps1','start.bat']:copy(name)
        copy('construction-safety-inspection/models/helmet_yolo11n/weights/best.pt')
        for filename in ['cam01_building.mp4','cam02_gate.mp4','cam03_workers.mp4','cam04_aerial.mp4']:copy(Path('videos')/filename)
        destination=stage/'backend/data/app.db';destination.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(seed) as src,sqlite3.connect(destination) as target:src.backup(target)
        src.close();target.close()
        with sqlite3.connect(destination) as c:
            c.execute('PRAGMA foreign_keys=ON')
            omitted=[]
            for sid,path,parsed,count in c.execute('SELECT id,file_path,parsed,cite_count FROM kb_sources').fetchall():
                if Path(path).suffix.lower()=='.rar':
                    assert not parsed and not count and c.execute('SELECT count(*) FROM kb_chunks WHERE source_id=?',(sid,)).fetchone()[0]==0
                    c.execute('DELETE FROM kb_changes WHERE source_id=?',(sid,));c.execute('DELETE FROM kb_sources WHERE id=?',(sid,));omitted.append(path)
                else:copy(path)
            assert len(omitted)==1
            assert c.execute('SELECT count(*) FROM kb_sources').fetchone()[0]==75
            for table in ['tokens','chat_sessions','documents','user_memories','attachments']:
                assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
        c.close()  # sqlite3's context manager commits but does not close/checkpoint WAL.
        # Keep the small initialization manifest required by db.init_db, without the raw RAR row.
        manifest=Path('施工安全RAG知识源/清单/施工安全RAG知识源_来源总清单_20261015.csv')
        src=(ROOT/manifest).open(encoding='utf-8-sig',newline='');reader=csv.DictReader(src);rows=list(reader);fields=reader.fieldnames;src.close()
        target=stage/manifest;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(r for r in rows if not r['文件名'].lower().endswith('.rar'))
        (stage/'README.md').write_text(README,encoding='utf-8')
        env={**os.environ,'APP_DB':str(destination),'LLM_ENABLED':'0','PYTHONUTF8':'1'}
        subprocess.run([sys.executable,'-c','from backend.rag.knowledge import Knowledge; Knowledge().save()'],cwd=stage,env=env,check=True,capture_output=True)
        files=[p for p in stage.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.log'}]
        for p in files:
            assert p.name!='.env' and '.venv' not in p.parts and '.git' not in p.parts
            if key:assert key.encode() not in p.read_bytes(),str(p.relative_to(stage))
        manifest_text='\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(stage).as_posix() for p in sorted(files))+'\n'
        (stage/'MANIFEST.sha256').write_text(manifest_text,encoding='utf-8');files.append(stage/'MANIFEST.sha256')
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(files):z.write(p,FOLDER+'/'+p.relative_to(stage).as_posix())
        # Validate the actual ZIP contents after extraction, using a separate QA database.
        extracted=Path(temp)/'verify';extracted.mkdir()
        with zipfile.ZipFile(output) as z:
            assert z.testzip() is None;z.extractall(extracted)
        runtime=extracted/FOLDER
        for line in (runtime/'MANIFEST.sha256').read_text(encoding='utf-8').splitlines():
            digest,name=line.split('  ',1);assert hashlib.sha256((runtime/name).read_bytes()).hexdigest()==digest,name
        childenv={**os.environ,'PYTHONUTF8':'1','LLM_ENABLED':'0'};childenv.pop('PYTHONPATH',None)
        result=subprocess.run([sys.executable,'-c',VERIFY],cwd=runtime,env=childenv,capture_output=True,text=True,encoding='utf-8',timeout=180)
        if result.returncode:
            print(result.stdout);print(result.stderr);raise RuntimeError('打包后的实际运行验证失败')
        checks=json.loads(result.stdout.strip().splitlines()[-1]);assert checks['passed']
    print(json.dumps({'zip':str(output),'size_mb':round(output.stat().st_size/1048576,2),'files':len(files),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'checks':checks},ensure_ascii=False))

if __name__=='__main__':main()
