import json
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with sqlite3.connect(ROOT/'backend/data/qa.db') as c:
    c.row_factory=sqlite3.Row
    runs=[dict(r) for r in c.execute("SELECT * FROM monitor_runs WHERE status='done' ORDER BY rowid")]
    for r in runs:r['result']=json.loads(r.pop('result_json'))
    positive=next(r for r in runs if r['result'].get('new_clues',0)>0)
    repeated=next(r for r in runs if r['rowid']>positive['rowid']) if positive.get('rowid') else next(r for r in runs[runs.index(positive)+1:] if r['result'].get('new_clues')==0)
    cached=[dict(r) for r in c.execute('SELECT * FROM monitor_stats_daily')]
    pending=c.execute("SELECT count(*) FROM monitor_snapshots WHERE data_mode='yolo'").fetchone()[0]
report={'real_inference':positive,'repeat_same_clip':repeated,'actual_yolo_clues_stored':pending,'cache':cached,'deduplication_passed':repeated['result']['new_clues']==0,'limitation':'抓拍包含误报可能，10条为局部轨迹线索，不代表10个唯一人员。所有真实抓拍先待核实，未经人工确认不入台账。','sample_image':'artifacts/vision-frame.jpg'}
(ROOT/'artifacts/vision-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'new_clues':positive['result']['new_clues'],'repeat_new_clues':repeated['result']['new_clues'],'frames':len(positive['result']['frames'])}))
