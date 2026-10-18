import json
import os
import argparse
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8010');args=parser.parse_args()
    with httpx.Client(base_url=args.url,timeout=20) as c:
        login=c.post('/api/auth/login',json={'username':'AQ20260001','password':os.getenv('SAFETY_DEMO_PASSWORD','123456')});login.raise_for_status()
        c.headers['Authorization']='Bearer '+login.json()['data']['token']
        try:
            response=c.post('/api/hazards/demo-cases',json={'confirmed':True});response.raise_for_status();h=response.json()['data']
            detail=c.get('/api/hazards/'+str(h['id'])).json()['data']
            assert detail['is_demo'] and detail['status']=='待整改' and not detail['feedbacks'] and not detail['demo_feedback']['received']
            report={'hazard_id':h['id'],'code':h['code'],'title':h['title'],'status':h['status'],'is_demo':True,'created_at':h['created_at'],'feedback_content':detail['demo_feedback']['feedback_content'],'feedback_received':False,'evidence_count':len(detail['attachments']),'url':args.url}
            (ROOT/'artifacts/hazard-demo-ready.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
        finally:c.post('/api/auth/logout')

if __name__=='__main__':main()
