"""Source-aware extraction, deterministic vectors, independent BM25/dense and RRF."""
from __future__ import annotations
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
import numpy as np
from bs4 import BeautifulSoup
from pypdf import PdfReader
from backend.app import db

CORE={
 'JGJ80-2016_att1.pdf':('建筑施工高处作业安全技术规范','JGJ80-2016','2016-11-01','https://www.mohurd.gov.cn/'),
 'GB55034-2022_att1.pdf':('建筑与市政施工现场安全卫生与职业健康通用规范','GB55034-2022','2023-06-01','https://www.mohurd.gov.cn/'),
 '国家_JGJT46-2024_建筑与市政工程施工现场临时用电安全技术标准_住建部.pdf':('建筑与市政工程施工现场临时用电安全技术标准','JGJ/T46-2024','2025-01-01','https://www.mohurd.gov.cn/gongkai/zc/wjk/art/2024/art_17339_780410.html'),
 '国家_建质规〔2024〕5号_房屋市政工程生产安全重大事故隐患判定标准2024版_全文_住建部.docx':('房屋市政工程生产安全重大事故隐患判定标准（2024版）','建质规〔2024〕5号','2024-12-13','https://www.mohurd.gov.cn/gongkai/zc/xzgfxwjk/art/2024/art_1446154772.html'),
 '国家_主席令第88号_安全生产法2021修正_全文.html':('中华人民共和国安全生产法（2021修正）','主席令第88号','2021-09-01','https://www.gov.cn/xinwen/2021-06/11/content_5616914.htm'),
 '国家_国务院令第393号_建设工程安全生产管理条例_全文_中国政府网.html':('建设工程安全生产管理条例','国务院令第393号','2004-02-01','https://www.gov.cn/'),
 '国家_建筑法2019修正_全文_中国人大网.html':('中华人民共和国建筑法（2019修正）','建筑法2019修正','2019-04-23','https://www.npc.gov.cn/'),
}
# These passages were transcribed against the rendered original pages in this build.
# OCR for the rest is searchable for inspection only until a source reviewer confirms it.
VERIFIED={
 'JGJ80-2016':[(13,'4.1.1','坠落高度基准面2m及以上进行临边作业时，应在临空一侧设置防护栏杆，并应采用密目式安全立网或工具式栏板封闭。'),(13,'4.1.2','施工的楼梯口、楼梯平台和梯段边，应安装防护栏杆；外设楼梯口、楼梯平台和梯段边还应采用密目式安全立网封闭。'),(14,'4.3.1','临边作业的防护栏杆应由横杆、立杆及挡脚板组成，防护栏杆应符合下列规定：1 防护栏杆应为两道横杆，上杆距地面高度应为1.2m，下杆应在上杆和挡脚板中间设置；2 当防护栏杆高度大于1.2m时，应增设横杆，横杆间距不应大于600mm；3 防护栏杆立杆间距不应大于2m；4 挡脚板高度不应小于180mm。')],
 'GB55034-2022':[(6,'3.1.3','施工现场应根据安全事故类型采取防护措施。对存在的安全问题和隐患，应定人、定时间、定措施组织整改。'),(6,'3.2.1','在坠落高度基准面上方2m及以上进行高空或高处作业时，应设置安全防护设施并采取防滑措施，高处作业人员应正确佩戴安全帽、安全带等劳动防护用品。'),(6,'3.2.3','在建工程的预留洞口、通道口、楼梯口、电梯井口等孔洞以及无围护设施或围护设施高度低于1.2m的楼层周边、楼梯侧边、平台或阳台边、屋面周边和沟、坑、槽等边沿应采取安全防护措施，并严禁随意拆除。')],
 'JGJ/T46-2024':[(12,'3.1.1','施工现场临时用电工程专用的电源中性点直接接地的220V/380V三相四线制低压电力系统，应符合下列规定：1 应采用三级配电系统；2 应采用TN-S系统；3 应采用二级剩余电流动作保护系统。'),(12,'3.2.1','在施工现场专用变压器供电的TN-S系统中，电气设备的金属外壳应与保护接地导体（PE）连接。保护接地导体（PE）应由工作接地、配电室（总配电箱）电源侧中性导体（N）处引出（图3.2.1）。'),(12,'3.2.3','在TN系统中，通过总剩余电流动作保护器的中性导体（N）与保护接地导体（PE）之间不得再做电气连接。'),(12,'3.2.4','在TN系统中，保护接地导体（PE）应与中性导体（N）分开敷设。PE接地必须与保护接地导体（PE）相连接，严禁与中性导体（N）相连接。')],
}
CLAUSE_WITHDRAWALS={'JGJ80-2016':{'4.1.1','4.2.1','5.2.3','6.4.1','8.1.2'}}
WITHDRAWAL_BASIS='住建部公告2022年第164号，2023-06-01起；GB55034-2022优先。资料包文件名误写118号，按正文更正。'

def compact(text):
    text=text.encode('utf-8','replace').decode('utf-8').replace('\x00','')
    text=re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])','',text)
    text=re.sub(r'(?<=\d)\s*[．·]\s*(?=\d) steps?','.',text)
    return text.strip()

def extract(path:Path):
    """Return (page, text) pairs, preserving PDF page coordinates."""
    data=path.read_bytes()
    if path.suffix.lower()=='.doc':raise ValueError('旧版DOC待人工打开核实，未入索引')
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            root=ElementTree.fromstring(z.read('word/document.xml'))
            return [(1,'\n'.join(''.join(p.itertext()) for p in root.findall('.//{*}p')))]
    if data.startswith(b'%PDF'):
        ocr=db.ROOT/'backend/data/ocr'/hashlib.sha256(data).hexdigest()
        if ocr.exists() and list(ocr.glob('*.txt')):
            return [(int(p.stem),compact(p.read_text(encoding='utf-8'))) for p in sorted(ocr.glob('*.txt'))]
        return [(i+1,compact(p.extract_text() or '')) for i,p in enumerate(PdfReader(path).pages)]
    if path.suffix.lower() in {'.html','.htm'}:
        soup=BeautifulSoup(data,'html.parser')
        for el in soup(['script','style','nav','footer','header','noscript']):el.decompose()
        options=soup.select('.TRS_Editor, .trs_editor, #zoom, #UCAP-CONTENT, .article-content, .view-content, .content-article')
        body=max(options,key=lambda x:len(x.get_text())) if options else (soup.body or soup)
        return [(1,body.get_text('\n',strip=True))]
    if path.suffix.lower() in {'.txt','.md'}:return [(1,data.decode('utf-8-sig'))]
    raise ValueError('不支持的文件类型')

def split_pages(pages):
    for page,text in pages:
        text=compact(text)
        parts=re.split(r'(?=(?:第[一二三四五六七八九十百零〇\d]+条)|(?:\b\d+[.．]\d+[.．]\d+\b))',text)
        for part in parts:
            part=part.strip()
            if len(part)<25:continue
            m=re.match(r'(第[一二三四五六七八九十百零〇\d]+条|\d+[.．]\d+[.．]\d+)',part)
            section=m.group(0) if m else f'第{page}页'
            for start in range(0,len(part),600):
                piece=part[start:start+680].strip()
                if len(piece)>=25:yield page,section,piece

def put_chunks(c,source,pages,verified_only=False):
    # Preserve chunks already cited by issued documents; switch index membership instead.
    c.execute('INSERT OR IGNORE INTO chunk_states(chunk_id,active) SELECT chunk_id,0 FROM kb_chunks WHERE source_id=?',(source['id'],))
    c.execute('UPDATE chunk_states SET active=0 WHERE chunk_id IN (SELECT chunk_id FROM kb_chunks WHERE source_id=?)',(source['id'],))
    chunks=VERIFIED.get(source['doc_no'])
    pieces=chunks if chunks else list(split_pages(pages))
    for page,section,text in pieces:
        key=hashlib.sha256(f"{source['sha256']}|{page}|{section}|{text}".encode()).hexdigest()[:24]
        c.execute('INSERT OR IGNORE INTO kb_chunks VALUES(?,?,?,?,?)',(key,source['id'],section,text,page))
        withdrawn=section in CLAUSE_WITHDRAWALS.get(canonical(source['doc_no']),set())
        c.execute('INSERT INTO chunk_states VALUES(?,?,?,?) ON CONFLICT(chunk_id) DO UPDATE SET active=excluded.active,legal_status=excluded.legal_status,note=excluded.note',(key,1,'旧强制性条文已废止' if withdrawn else '现行',WITHDRAWAL_BASIS if withdrawn else '正文已解析'))
    return len(pieces)

def rebuild():
    db.init_db()
    processed=[]
    local=db.ROOT/'backend/data/extracted_text.json'
    extra=json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    with db.connect() as c:
        for path,pages in extra.items():
            p=db.ROOT/path
            no='DBJ/T13-318-2025' if '脚手架' in p.name else 'DBJ/T13-91-2025'
            c.execute('INSERT OR IGNORE INTO kb_sources(name,category,doc_no,effective_date,region,status,legal_status,source_url,file_path,sha256,created_at,content_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      (p.stem,'法规依据',no,'2025-09-01','福建','待核验','待核验','https://zjt.fujian.gov.cn/',path,hashlib.sha256(p.read_bytes()).hexdigest(),db.now(),'全文/正文'))
        sources=[dict(r) for r in c.execute('SELECT * FROM kb_sources')]
        for source in sources:
            path=db.ROOT/source['file_path']
            name=path.name
            try:
                if source['file_path'] in extra:pages=list(enumerate(extra[source['file_path']],1))
                else:pages=extract(path)
                total=sum(len(t) for _,t in pages)
                if total<80:raise ValueError('正文不足，待人工核验')
                core=CORE.get(name)
                if core:
                    source['name'],source['doc_no'],source['effective_date'],source['source_url']=core
                count=put_chunks(c,source,pages)
                # Explicit core source validation only; original manifest is never treated as approval.
                approved=bool(core or source['file_path'] in extra)
                historical=source['legal_status']=='已废止'
                state='历史版本' if historical else '现行' if approved else '待核验'
                legal='已废止' if historical else '现行' if approved else '待核验'
                ocr=(db.ROOT/'backend/data/ocr'/source['sha256']).exists()
                note=f'{count}条可检索片段；'+('扫描PDF，正文OCR已完成；只启用经原页核对条款' if source['doc_no'] in VERIFIED else '正文已抽取')
                if source['category']=='案例参考':note+='；仅供案例学习'
                c.execute('UPDATE kb_sources SET name=?,doc_no=?,effective_date=?,source_url=?,status=?,legal_status=?,parsed=1,parse_note=?,verified_by=?,verified_at=?,region=? WHERE id=?',
                          (source['name'],source['doc_no'],source['effective_date'],source['source_url'],state,legal,note,'初始资料核验（用户授权）' if approved else None,db.now() if approved else None,'国家' if core else source['region'],source['id']))
                if approved and source['status']!='现行':
                    c.execute('INSERT INTO kb_changes(source_id,action,before_json,after_json,actor,created_at) VALUES(?,?,?,?,?,?)',(source['id'],'initial_source_validation',db.dumps({'status':source['status'],'legal_status':source['legal_status']}),db.dumps({'status':state,'legal_status':legal}),'初始资料核验（用户授权）',db.now()))
                processed.append({'id':source['id'],'file':str(path.relative_to(db.ROOT)),'chunks':count,'status':state,'note':note})
            except Exception as e:
                note=str(e)[:160]
                c.execute('UPDATE kb_sources SET parsed=0,parse_note=? WHERE id=?',(note,source['id']))
                processed.append({'id':source['id'],'file':str(path.relative_to(db.ROOT)),'error':note})
        db.audit(c,'system','rebuild_index','kb','all',{'sources':len(sources)})
    out=db.ROOT/'backend/data/ingest_report.json'
    out.write_text(db.dumps(processed),encoding='utf-8')
    Knowledge().save()
    return processed

STOP={'什么','要求','如何','哪些','是否','施工','现场','安全','规定','标准','规范','请问','相关','一下','可以','应该','资料','建设','工程','核心','查询','依据','多少','问题','的要','有什','么要','是什','怎么','进行','关于','需要','管理'}
def tokens(text):
    latin=re.findall(r'[a-z0-9]+(?:[-/][a-z0-9]+)*',text.lower())
    chinese=[]
    for run in re.findall(r'[\u4e00-\u9fff]+',text):
        chinese.extend(run[i:i+2] for i in range(len(run)-1) if run[i:i+2] not in STOP)
    return latin+chinese

def vector(text,dim=512):
    v=np.zeros(dim,dtype=np.float32)
    for token,n in Counter(tokens(text)).items():
        h=hashlib.sha256(token.encode()).digest()
        v[int.from_bytes(h[:4],'big')%dim]+=math.log1p(n)
    return v/(np.linalg.norm(v) or 1)

def canonical(no):return re.sub(r'\s+','',no or '').upper()

def cite_allowed(source,region='厦门'):
    applicable=source.get('region','') in {'国家','全国','福建','福建省','厦门','厦门市','国家/全国'} or region in source.get('region','')
    withdrawn=source.get('section') in CLAUSE_WITHDRAWALS.get(canonical(source.get('doc_no')),set())
    return not withdrawn and source.get('chunk_legal_status','现行')=='现行' and source.get('chunk_active',1)==1 and source.get('status')=='现行' and source.get('legal_status')=='现行' and source.get('category')=='法规依据' and source.get('parsed')==1 and source.get('content_kind')!='发布公告' and applicable

class Knowledge:
    def __init__(self):
        self.chunks=db.rows('SELECT k.*,s.name,s.doc_no,s.region,s.status,s.legal_status,s.source_url,s.category,s.parsed,s.content_kind,s.file_path,s.effective_date,coalesce(cs.active,1) chunk_active,coalesce(cs.legal_status,\'现行\') chunk_legal_status,cs.note chunk_note FROM kb_chunks k JOIN kb_sources s ON s.id=k.source_id LEFT JOIN chunk_states cs ON cs.chunk_id=k.chunk_id ORDER BY k.chunk_id')
        self.tfs=[Counter(tokens(c['text'])) for c in self.chunks]
        self.df=Counter(t for tf in self.tfs for t in tf)
        self.avg=sum(sum(tf.values()) for tf in self.tfs)/max(1,len(self.tfs))
        self.vectors=np.array([vector(c['text']) for c in self.chunks])

    def save(self):
        p=db.ROOT/'backend/data/index.npz'
        np.savez_compressed(p,vectors=self.vectors,chunk_ids=np.array([c['chunk_id'] for c in self.chunks]))

    def bm25(self,query):
        ts=tokens(query);n=len(self.chunks)
        result=[]
        for i,tf in enumerate(self.tfs):
            length=sum(tf.values())
            score=sum(math.log(1+(n-self.df[t]+.5)/(self.df[t]+.5))*tf[t]*2.2/(tf[t]+1.2*(.25+.75*length/max(1,self.avg))) for t in ts if tf[t])
            result.append((i,score))
        return sorted(result,key=lambda x:(-x[1],self.chunks[x[0]]['chunk_id']))

    def dense(self,query):
        if not len(self.chunks):return []
        scores=self.vectors@vector(query)
        return sorted(enumerate(map(float,scores)),key=lambda x:(-x[1],self.chunks[x[0]]['chunk_id']))

    def search(self,query,limit=5,for_document=False,source_id=None,include_history=False):
        query=query.replace('临电','临时用电').replace('基坑边','基坑临边')
        query=re.sub(r'有什么要求|有哪些要求|是什么|请问|的设置要求|有什么|具体要求|什么要求','',query)
        qt=set(tokens(query));preferred='JGJ80-2016' if any(x in query for x in ['临边','防护栏杆','楼梯口','高处']) else 'JGJ/T46-2024' if any(x in query for x in ['用电','接地','接零','TN-S']) else None
        eligible=set()
        requested=re.search(r'(?:JGJ/?T?|GB/?T?|DBJ/?T?)[\s\d/-]+\d',query,re.I)
        required=canonical(requested.group()) if requested else None
        specific=[t for t in ['临边','楼梯','接地','连墙件','安全帽','有限空间','模板','起重'] if t in query]
        for i,c in enumerate(self.chunks):
            if not c['chunk_active']:continue
            if c['chunk_legal_status']!='现行' and not include_history:continue
            if source_id and c['source_id']!=int(source_id):continue
            if c['status']!='现行' and not (include_history and c['status']=='历史版本'):continue
            if for_document and not cite_allowed(c):continue
            if required and required!=canonical(c['doc_no']):continue
            if specific and not any(t in c['text'] for t in specific):continue
            overlap=qt.intersection(self.tfs[i])
            if len(overlap)<min(2,len(qt)) or len(overlap)/max(1,len(qt))<.35:continue
            eligible.add(i)
        fused=Counter()
        for weight,ranked in [(.55,self.dense(query)),(.45,self.bm25(query))]:
            filtered=[(i,s) for i,s in ranked if i in eligible and s>0]
            for rank,(i,score) in enumerate(filtered,1):fused[i]+=weight/(60+rank)
        ordered=sorted(fused,key=lambda i:(-(fused[i]+(.02 if preferred and canonical(self.chunks[i]['doc_no'])==preferred else 0)),self.chunks[i]['chunk_id']))[:limit]
        if preferred:
            preferred_rows=[i for i in ordered if canonical(self.chunks[i]['doc_no'])==preferred]
            if preferred_rows:ordered=preferred_rows
        return [{**self.chunks[i],'score':round(fused[i],8),'citation_eligible':cite_allowed(self.chunks[i]),'display_status':self.chunks[i]['chunk_legal_status'] if self.chunks[i]['chunk_legal_status']!='现行' else '已废止' if self.chunks[i]['legal_status']=='已废止' else self.chunks[i]['status']} for i in ordered]

def search(*args,**kwargs):return Knowledge().search(*args,**kwargs)

if __name__=='__main__':
    result=rebuild()
    print(db.dumps({'sources':len(result),'parsed':sum('error' not in r for r in result),'chunks':db.one('SELECT count(*) n FROM kb_chunks')['n']}))
