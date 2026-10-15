import json
import os
import subprocess
import sys
import pytest
from backend.rag.knowledge import Knowledge,cite_allowed

@pytest.fixture(scope='module')
def index():return Knowledge()

@pytest.mark.parametrize('question,expected',[
 ('基坑临边防护有什么要求','JGJ80-2016'),
 ('临边防护栏杆','JGJ80-2016'),('楼梯口防护','JGJ80-2016'),
 ('高处临边作业','JGJ80-2016'),('施工临时用电接地要求','JGJ/T46-2024'),
 ('TN-S系统保护接地导体','JGJ/T46-2024'),('保护接地导体分开敷设','JGJ/T46-2024'),
 ('三级配电系统','JGJ/T46-2024'),('脚手架连墙件设置要求',None),
 ('脚手架重大事故隐患',None),('安全帽佩戴',None),('劳动防护用品佩戴',None),
 ('有限空间作业',None),('起重机械隐患',None),('模板工程隐患',None),
 ('火星量子计算机维修','EMPTY'),('意大利歌剧歌词','EMPTY'),
 ('JGJ130-2011第6.4.1条原文','EMPTY'),('JGJ46-2005接地现行依据','EMPTY'),
 ('北京DB11/945-2012条文','EMPTY'),
])
def test_twenty_questions(index,question,expected):
    result=index.search(question,for_document=True)
    if expected=='EMPTY':assert not result
    else:
        assert result,question
        if expected:assert result[0]['doc_no']==expected
        assert all(r['chunk_id'] and r['section'] and r['citation_eligible'] for r in result)

def test_rank_stable_across_processes(index):
    code="import json;from backend.rag.knowledge import search;print(json.dumps([r['chunk_id'] for r in search('临时用电接地')]))"
    outputs=[subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':seed}) for seed in ['1','91']]
    assert outputs[0]==outputs[1]
    assert index.search('临边防护')==index.search('临边防护')

def test_citation_excludes_case_expired_region(index):
    row={'status':'现行','legal_status':'现行','category':'法规依据','parsed':1,'region':'国家','content_kind':'全文/正文'}
    assert cite_allowed(row)
    for change in [{'region':'北京'},{'legal_status':'已废止'},{'category':'案例参考'},{'status':'待核验'},{'content_kind':'发布公告'}]:
        assert not cite_allowed({**row,**change})
    assert not cite_allowed({**row,'doc_no':'JGJ80-2016','section':'4.1.1'})
    found=index.search('基坑临边防护',for_document=True)
    assert any(r['doc_no']=='JGJ80-2016' and r['section']=='4.3.1' for r in found)
    assert all(not (r['doc_no']=='JGJ80-2016' and r['section']=='4.1.1') for r in found)
