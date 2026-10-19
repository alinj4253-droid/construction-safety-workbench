import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TEXT={'.py','.js','.mjs','.cjs','.ts','.tsx','.jsx','.html','.css','.txt','.json','.csv','.yaml','.yml','.toml','.ini','.cfg','.bat','.ps1','.xml','.example','.gitignore','.sql','.sh','.svg'}
PRIVATE_DIRS={'artifacts','26专业综合实践 final','专业综合实践答辩','.git','.venv','node_modules','__pycache__','.pytest_cache','exports','runs','datasets','dataset','数据集'}
PATTERNS=[(re.compile(rb'sk-[A-Za-z0-9_-]{20,}'),b'YOUR_API_KEY'),(re.compile(rb'gh[pousr]_[A-Za-z0-9_]{20,}'),b'YOUR_GITHUB_TOKEN'),(re.compile(rb'github_pat_[A-Za-z0-9_]{20,}'),b'YOUR_GITHUB_TOKEN')]

def git(*args,cwd=ROOT,data=None,env=None):
    result=subprocess.run(['git',*args],cwd=cwd,input=data,capture_output=True,env=env)
    if result.returncode:raise RuntimeError('git '+args[0]+' failed: '+result.stderr.decode('utf-8','replace')[:300])
    return result.stdout

def identifiers():
    values={}
    for p in ROOT.rglob('.env'):
        if any(s in {'.venv','.git','node_modules'} for s in p.relative_to(ROOT).parts):continue
        for line in p.read_text(encoding='utf-8-sig',errors='replace').splitlines():
            if '=' not in line or line.lstrip().startswith('#'):continue
            key,value=line.split('=',1);value=value.strip().strip('\"\'')
            if value and re.search('key|token|secret|password',key,re.I) and len(value)>=8:values[value.encode()] = b'YOUR_SECRET'
    raw=git('log','--all','--format=%an%n%ae%n%cn%n%ce').decode('utf-8','replace')
    for item in set(raw.splitlines()):
        if len(item)>2 and item not in {'Codex','codex','Project Contributor'}:values[item.encode()]=b'PROJECT_CONTRIBUTOR'
    values[Path.home().name.encode()]=b'USER'
    manifest=ROOT/'artifacts/tmp/practice-docs/build-manifest.json'
    if manifest.exists():
        material=json.loads(manifest.read_text(encoding='utf-8'))
        for key in ('author','student_id'):
            if material.get(key):values[str(material[key]).encode()]=b'PRIVATE_PERSON' if key=='author' else b'STUDENT_ID'
    return sorted(values.items(),key=lambda pair:-len(pair[0]))

def allowed(relative):
    p=Path(relative);parts=p.parts
    if not parts or any(x in PRIVATE_DIRS or x.startswith('qa_docx') for x in parts):return False
    if p.suffix.lower() in {'.md','.markdown','.mdown','.log','.db','.sqlite','.sqlite3','.pyc','.part','.pkl','.pickle'}:return False
    if p.name.startswith('~$') or p.name=='.agents':return False
    if p.suffix.lower() in {'.zip','.rar','.7z'} and parts[0]!='施工安全RAG知识源':return False
    if p.suffix.lower() in {'.docx','.doc','.pdf','.pptx','.xlsx'} and parts[0] not in {'施工安全RAG知识源','construction_safety_rag','backend'}:return False
    if parts[:2]==('construction-safety-inspection','data'):return False
    if parts[:2]==('backend','data'):return False
    return True

def sanitize(data,replacements,path=''):
    for old,new in replacements:data=data.replace(old,new)
    for pattern,new in PATTERNS:data=pattern.sub(new,data)
    if Path(path).suffix.lower() in TEXT or Path(path).name.startswith('.env'):
        data=re.sub(rb'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n"\s]+',b'USER_HOME',data)
        data=re.sub(rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',b'contact@example.invalid',data)
    return data

def save(root,path,data):
    target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)

def build(stage,replacements):
    tracked=[p.decode('utf-8') for p in git('ls-files','-z').split(b'\0') if p]
    paths={p for p in tracked if allowed(p) and (ROOT/p).is_file()}
    for folder in ['videos','施工安全RAG知识源','construction-safety-inspection/models','construction-safety-inspection/weights']:
        for p in (ROOT/folder).rglob('*'):
            relative=p.relative_to(ROOT).as_posix()
            if p.is_file() and allowed(relative) and (folder.find('/models')<0 or p.suffix in {'.pt','.yaml','.csv'}):paths.add(relative)
    for name in sorted(paths):
        p=ROOT/name;raw=p.read_bytes()
        if p.suffix.lower() in TEXT or p.name.startswith('.env'):raw=sanitize(raw,replacements,name)
        else:
            if any(old in raw for old,new in replacements) or any(pattern.search(raw) for pattern,new in PATTERNS):
                raise ValueError('Binary requires manual privacy review: '+name)
        save(stage,name,raw)
    for p in (ROOT/'backend/data/extracted').glob('*.pdf'):
        save(stage,p.relative_to(ROOT),p.read_bytes())
    for name in ['index.npz','extracted_text.json','ingest_report.json']:
        p=ROOT/'backend/data'/name
        if p.exists():save(stage,p.relative_to(ROOT),p.read_bytes())
    env=(ROOT/'.env.example').read_bytes()
    env=sanitize(env,replacements,'.env')
    env=re.sub(rb'(?m)^OPENAI_API_KEY=.*$',b'OPENAI_API_KEY=YOUR_API_KEY',env)
    env=re.sub(rb'(?m)^LLM_ENABLED=.*$',b'LLM_ENABLED=0',env)
    save(stage,'.env',env);save(stage,'.env.example',env)
    save(stage,'frontend/monitor-runtime.local.json',b'{"app_port":8010,"api_origin":""}\n')
    save(stage,'START_HERE.txt',('施工安全管理工作台：完整脱敏运行包\n\n需要 Python 3.11。首次解压后在本目录打开 PowerShell：\npy -3.11 -m venv .venv\n.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010\n\n打开 http://127.0.0.1:8010 ，演示账号 AQ20260001，演示密码 123456。以后可双击 start.bat。\n\n.env 中为密钥占位符，默认 LLM_ENABLED=0，使用有标识的离线检索和规则兜底。使用在线模型前填入自己的密钥并将 LLM_ENABLED=1。\n\n包含最新系统与旧工程源码、测试、四路本地录像及真实YOLO检测回放缓存、模型权重、全部知识原文、归档重建原料和索引。录像不是实时监控；缓存检测不是模拟检测。\n\n业务库是脱敏后重新生成的演示种子：4条待办理隐患、2条未确认模拟线索；无历史聊天、签发、整改、复查、登录令牌或长期记忆。王建国等为演示身份。\n\n不包含 Markdown、个人实践材料、原业务数据库、附件、测试备份、重复导出、训练数据和虚拟环境。原项目本地文件均未删除或改写。\n\n后台测试：.venv\\Scripts\\python.exe -m pytest backend/tests -q\n测试须单进程执行。\n').encode())
    ignore='*.md\n*.markdown\n.venv/\n**/__pycache__/\n.pytest_cache/\n*.pyc\n.env\n.env.*\n!.env.example\n*.log\nbackend/data/backups/\nbackend/data/attachments/\nbackend/data/monitor/\nbackend/data/test_archive/\n*.db-wal\n*.db-shm\nartifacts/\n'
    save(stage,'.gitignore',ignore.encode())

def build_history(destination,replacements):
    destination.mkdir(parents=True,exist_ok=False)
    git('init',cwd=destination)
    git('config','user.name','Project Contributor',cwd=destination)
    git('config','user.email','contributor@example.invalid',cwd=destination)
    commits=git('rev-list','--reverse','--topo-order','HEAD').decode().splitlines()
    commit_map={};blob_map={};removed=set()
    for index,commit in enumerate(commits,1):
        records=git('ls-tree','-rz',commit).split(b'\0');entries=[]
        for record in records:
            if not record:continue
            meta,name=record.split(b'\t',1);mode,kind,oid=meta.split();path=name.decode('utf-8')
            if kind!=b'blob' or not allowed(path):removed.add(path);continue
            key=(oid,path if Path(path).name.startswith('.env') else Path(path).suffix.lower())
            if key not in blob_map:
                data=git('cat-file','blob',oid.decode())
                if Path(path).suffix.lower() in TEXT or Path(path).name.startswith('.env'):data=sanitize(data,replacements,path)
                elif any(old in data for old,new in replacements) or any(p.search(data) for p,new in PATTERNS):
                    removed.add(path);continue
                blob_map[key]=git('hash-object','-w','--stdin',cwd=destination,data=data).strip()
            entries.append(mode+b' '+blob_map[key]+b'\t'+name+b'\0')
        git('read-tree','--empty',cwd=destination)
        git('update-index','-z','--index-info',cwd=destination,data=b''.join(entries))
        tree=git('write-tree',cwd=destination).decode().strip()
        raw=git('cat-file','commit',commit);header,message=raw.split(b'\n\n',1)
        parents=[];dates={}
        for line in header.splitlines():
            if line.startswith(b'parent '):parents+=['-p',commit_map[line[7:].decode()]]
            if line.startswith((b'author ',b'committer ')):
                field=line.split(b' ',1)[0].decode();dates[field]=line.rsplit(b'> ',1)[1].decode()
        env={**os.environ,'GIT_AUTHOR_NAME':'Project Contributor','GIT_AUTHOR_EMAIL':'contributor@example.invalid','GIT_COMMITTER_NAME':'Project Contributor','GIT_COMMITTER_EMAIL':'contributor@example.invalid','GIT_AUTHOR_DATE':dates['author'],'GIT_COMMITTER_DATE':dates['committer']}
        mapped=git('commit-tree',tree,*parents,cwd=destination,data=sanitize(message,replacements),env=env).decode().strip();commit_map[commit]=mapped
        print(json.dumps({'history_commit':index,'total':len(commits)}),flush=True)
    git('update-ref','refs/heads/main',commit_map[commits[-1]],cwd=destination)
    git('symbolic-ref','HEAD','refs/heads/main',cwd=destination)
    git('reset','--hard','HEAD',cwd=destination)
    return {'original_commits':len(commits),'published_history_commits':len(commit_map),'removed_history_paths':len(removed),'authors_anonymized':True,'hashes_changed_by_sanitization':True,'map':commit_map}

def audit(stage,replacements):
    paths=[];failures=[]
    for p in stage.rglob('*'):
        if not p.is_file() or '.git' in p.relative_to(stage).parts:continue
        rel=p.relative_to(stage).as_posix();data=p.read_bytes()
        if p.suffix.lower() in {'.md','.markdown','.mdown'}:failures.append(rel)
        if any(old in data for old,new in replacements) or any(pattern.search(data) for pattern,new in PATTERNS):failures.append(rel)
        paths.append((rel,hashlib.sha256(data).hexdigest(),len(data)))
    if failures:raise ValueError('Privacy validation failed: '+', '.join(failures))
    return paths

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--history',action='store_true');args=parser.parse_args()
    output=Path(args.output).resolve()
    if output.exists():raise FileExistsError(str(output))
    if not output.is_relative_to(ROOT/'artifacts/tmp'):raise ValueError('Release staging must stay inside artifacts/tmp')
    output.mkdir(parents=True)
    stage=output/'施工安全管理工作台';stage.mkdir()
    replacements=identifiers();build(stage,replacements)
    report={'stage':str(stage),'filtered_identifiers':len(replacements),'markdown_excluded':True,'source_files_untouched':True}
    if args.history:report['history']=build_history(output/'publish',replacements)
    (output/'build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='history'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
