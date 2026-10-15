from __future__ import annotations
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends
from backend.app import db
from backend.app.security import current_user
from backend.app.hazards import decorated
router=APIRouter(prefix='/api/dashboard')

def sync_monitor_stats(c):
    from collections import Counter
    day=str(db.today())
    active=[dict(r) for r in c.execute("SELECT * FROM monitor_snapshots WHERE captured_at LIKE ? AND status<>'dismissed'",(day+'%',))]
    hours=Counter(s['captured_at'][11:13] for s in active);places=Counter(s['location'] for s in active)
    peak=hours.most_common(1)[0][0] if hours else None
    c.execute('INSERT OR IGNORE INTO monitor_stats_daily(date,on_site_count,data_mode) VALUES(?,?,?)',(day,0,'unavailable'))
    c.execute('UPDATE monitor_stats_daily SET no_helmet_count=?,no_vest_count=?,peak_hour=?,hot_zone=? WHERE date=?',(sum(s['category']=='未戴安全帽' for s in active),sum(s['category']=='未穿反光衣' for s in active),f'{peak}:00–{int(peak)+1:02d}:00' if peak else '暂无数据',places.most_common(1)[0][0] if places else '暂无数据',day))

def monitor_summary():
    day=str(db.today())
    snaps=db.rows("SELECT * FROM monitor_snapshots WHERE captured_at LIKE ? AND status<>'dismissed'",(day+'%',))
    stat=db.one('SELECT * FROM monitor_stats_daily WHERE date=?',(day,)) or {}
    helmet=sum(s['category']=='未戴安全帽' for s in snaps)
    vest=sum(s['category']=='未穿反光衣' for s in snaps)
    times=__import__('collections').Counter(s['captured_at'][11:13] for s in snaps)
    places=__import__('collections').Counter(s['location'] for s in snaps)
    peak=times.most_common(1)[0][0] if times else None
    return {'on_site':stat.get('on_site_count',0),'violations':len(snaps),'no_helmet':helmet,'no_vest':vest,'pending':db.one("SELECT count(*) n FROM monitor_snapshots WHERE status='pending'")['n'],'peak_hour':f'{peak}:00–{int(peak)+1:02d}:00' if peak else '暂无数据','hot_zone':places.most_common(1)[0][0] if places else '暂无数据','data_mode':stat.get('data_mode','unavailable'),'trend':[{'hour':h,'count':sum(s['category']=='未戴安全帽' and s['captured_at'][11:13]==f'{h:02d}' for s in snaps)} for h in range(24)]}

@router.get('/summary')
def summary(user=Depends(current_user)):
    hazards=[decorated(h) for h in db.rows('SELECT * FROM hazards')]
    day=db.today();month=day.strftime('%Y-%m');prev=(day.replace(day=1)-timedelta(days=1)).strftime('%Y-%m')
    def rate(prefix):
        hs=[h for h in hazards if h['created_at'].startswith(prefix)]
        return round(100*sum(h['status'] in db.TERMINAL for h in hs)/len(hs),1) if hs else 0
    todos=[]
    for h in hazards:
        if h['status'] in db.TERMINAL:continue
        priority=0 if h['overdue'] else 1 if h['status']=='待复查' else 2 if h['status']=='待确认' else 3
        todos.append({'type':'overdue' if priority==0 else 'review' if priority==1 else 'confirm' if priority==2 else 'rectify','hazard_id':h['id'],'title':h['title'],'team':h['responsible_team'],'deadline':h['deadline'],'status':h['status'],'overdue_days':h['overdue_days'],'priority':priority})
    if user['role'] in {'专职安全员','安全员'}:
        for s in db.rows("SELECT * FROM monitor_snapshots WHERE status='pending' ORDER BY captured_at"):
            todos.append({'type':'snapshot','snapshot_id':s['id'],'title':s['category']+' · '+s['location'],'status':'待现场确认','priority':2})
    else:
        for t in todos:t['view_action']='urge'
    todos.sort(key=lambda t:(t['priority'],t.get('deadline') or '9999',t.get('hazard_id',99999)))
    week=day-timedelta(days=day.weekday())
    return {'code':0,'message':'ok','data':{'today':str(day),'weekday':'星期'+'一二三四五六日'[day.weekday()],'week_closed':sum(bool(h['closed_at'] and h['closed_at'][:10]>=str(week)) for h in hazards),'pending_review':sum(h['status']=='待复查' for h in hazards),'overdue':sum(h['overdue'] for h in hazards),'today_new':sum(h['created_at'][:10]==str(day) for h in hazards),'today_new_ai':sum(h['created_at'][:10]==str(day) and h['source']=='ai_monitor' for h in hazards),'month_rate':rate(month),'month_rate_delta':round(rate(month)-rate(prev),1),'todos':todos,'monitor_today':monitor_summary(),'role':user['role']}}
