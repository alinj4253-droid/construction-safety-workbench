"""Helmet/NOHelmet are two head classes. No full-person/hat matching."""
from __future__ import annotations
import hashlib
import os
import threading
from pathlib import Path
from backend.app import db

CAMERAS=[{'id':'CAM-01','location':'3#楼主体结构 · 全景','file':'cam01_building.mp4'},
         {'id':'CAM-02','location':'土方作业区 · 车辆装卸','file':'cam02_gate.mp4'},
         {'id':'CAM-03','location':'3#楼二层作业面','file':'cam03_workers.mp4'},
         {'id':'CAM-04','location':'无人机航拍 · 全场俯瞰','file':'cam04_aerial.mp4'}]
_model=None
_lock=threading.Lock()

def map_head_classes(raw,threshold=.35):
    return [{'class_id':int(cid),'label':'佩戴安全帽' if cid==0 else '未佩戴安全帽','confidence':float(conf),'bbox':list(map(float,box))} for cid,conf,box in raw if cid in (0,1) and conf>=threshold]

def model():
    global _model
    if _model is None:
        os.environ.setdefault('YOLO_CONFIG_DIR',str(db.ROOT/'backend/data/yolo'))
        os.environ.setdefault('YOLO_AUTOINSTALL','false')
        from ultralytics import YOLO
        p=db.ROOT/'construction-safety-inspection/models/helmet_yolo11n/weights/best.pt'
        if not p.exists():raise FileNotFoundError('缺少本地安全帽检测权重')
        _model=YOLO(str(p))
    return _model

def iou(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    inter=x*y
    return inter/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)

def process(run_id,camera_id,max_frames=8):
    import cv2
    import numpy as np
    camera=next(c for c in CAMERAS if c['id']==camera_id)
    path=db.ROOT/'videos'/camera['file'];cap=cv2.VideoCapture(str(path));frames=[];tracks=[];created=[]
    try:
        if not cap.isOpened():raise ValueError('本地演示视频不可读取')
        fps=cap.get(cv2.CAP_PROP_FPS) or 25;total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));step=max(1,int(fps))
        directory=db.ROOT/'backend/data/monitor';directory.mkdir(parents=True,exist_ok=True)
        fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        with _lock:
            yolo=model()
            db.write('UPDATE monitor_runs SET status=? WHERE id=?',('running',run_id))
            for sample,frame_index in enumerate(range(0,min(total,step*max_frames),step)):
                cap.set(cv2.CAP_PROP_POS_FRAMES,frame_index);valid,frame=cap.read()
                if not valid:continue
                result=yolo.predict(frame,conf=.35,imgsz=1280,verbose=False,device='cpu')[0]
                raw=[(int(b.cls[0]),float(b.conf[0]),b.xyxy[0].tolist()) for b in result.boxes]
                detections=map_head_classes(raw)
                image=frame.copy();height,width=image.shape[:2]
                for d in detections:
                    x1,y1,x2,y2=map(int,d['bbox']);color=(40,190,40) if d['class_id']==0 else (20,40,230)
                    cv2.rectangle(image,(x1,y1),(x2,y2),color,2);cv2.putText(image,('HELMET' if d['class_id']==0 else 'NO HELMET')+f" {d['confidence']:.2f}",(x1,max(20,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.55,color,2)
                filename=f'{run_id}-{sample:03d}.jpg';image_path=directory/filename
                ok,payload=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:continue
                image_path.write_bytes(payload.tobytes());relative=str(image_path.relative_to(db.ROOT))
                fid=db.write('INSERT INTO monitor_frames(run_id,camera_id,media_time,image_path,detections_json,created_at) VALUES(?,?,?,?,?,?)',(run_id,camera_id,round(frame_index/fps,3),relative,db.dumps({'width':width,'height':height,'detections':detections}),db.now()))
                frames.append({'id':fid,'media_time':round(frame_index/fps,3),'helmet_on':sum(d['class_id']==0 for d in detections),'helmet_off':sum(d['class_id']==1 for d in detections)})
                used=set()
                for d in [x for x in detections if x['class_id']==1]:
                    match=next((i for i,t in enumerate(tracks) if i not in used and sample-t['sample']<=3 and iou(t['bbox'],d['bbox'])>.2),None)
                    if match is not None:tracks[match].update(bbox=d['bbox'],sample=sample);used.add(match);continue
                    tracks.append({'bbox':d['bbox'],'sample':sample});used.add(len(tracks)-1)
                    key=f'{camera_id}|{fingerprint}|{frame_index}|'+','.join(str(round(x/10)) for x in d['bbox'])
                    with db.connect() as c:
                        cur=c.execute('INSERT OR IGNORE INTO monitor_snapshots(camera_id,captured_at,category,confidence,location,image_path,status,note,data_mode,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?)',(camera_id,db.now(),'未戴安全帽',round(d['confidence'],4),camera['location'],relative,'pending',db.dumps({'run_id':run_id,'media_time':frame_index/fps,'bbox':d['bbox'],'model_class_semantics':'Helmet/NOHelmet，头部目标'}),'yolo',key))
                        if cur.rowcount:created.append(cur.lastrowid)
            result={'camera_id':camera_id,'frames':frames,'snapshot_ids':created,'new_clues':len(created),'semantics':'同一片段局部轨迹去重；不识别人员身份，不推算全场在场人数','model':'本地YOLO11n安全帽权重'}
            db.write('UPDATE monitor_runs SET status=?,result_json=?,finished_at=? WHERE id=?',('done',db.dumps(result),db.now(),run_id))
            from backend.app.dashboard import sync_monitor_stats
            with db.connect() as c:
                sync_monitor_stats(c)
                actor=c.execute('SELECT created_by FROM monitor_runs WHERE id=?',(run_id,)).fetchone()['created_by']
                db.audit(c,actor,'finish_detection','monitor_run',run_id,{'frames':len(frames),'new_clues':len(created)})
    except Exception as e:
        db.write('UPDATE monitor_runs SET status=?,error=?,finished_at=? WHERE id=?',('error','检测未完成：'+type(e).__name__+' '+str(e)[:120],db.now(),run_id))
    finally:cap.release()

# RTSP is intentionally not connected. Future adapter must produce the same unconfirmed
# clue schema; it must never bypass the safety officer's confirmation endpoint.
