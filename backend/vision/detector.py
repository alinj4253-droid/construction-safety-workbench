"""Helmet/NOHelmet are two head classes. No full-person/hat matching."""
from __future__ import annotations
import hashlib
import os
import threading
from pathlib import Path
from backend.app import db

CAMERAS=[{'id':'CAM-01','location':'3#楼主体结构 · 全景','file':'cam01_building.mp4','confidence_floor':.65,'applicability':'施工远景，头部尺度过小，可能漏检；不适合判定人员佩戴情况'},
         {'id':'CAM-02','location':'土方作业区 · 车辆装卸','file':'cam02_gate.mp4','confidence_floor':.65,'applicability':'车辆俯拍，通常看不到可辨识头部；不能判断车内人员'},
         {'id':'CAM-03','location':'3#楼二层作业面','file':'cam03_workers.mp4','confidence_floor':.25,'applicability':'人员作业面，具备可辨识头部；仍有遮挡、误报和漏检'},
         {'id':'CAM-04','location':'无人机航拍 · 全场俯瞰','file':'cam04_aerial.mp4','confidence_floor':.65,'applicability':'高空航拍，头部像素不足，易将背景误识别；不适合安全帽合规判定'}]
_model=None
_lock=threading.Lock()

def map_head_classes(raw,threshold=.35):
    return [{'class_id':int(cid),'label':'佩戴安全帽' if cid==0 else '未佩戴安全帽','confidence':float(conf),'bbox':list(map(float,box))} for cid,conf,box in raw if cid in (0,1) and conf>=threshold]

def model():
    global _model
    if _model is None:
        os.environ.setdefault('YOLO_CONFIG_DIR',str(db.ROOT/'backend/data/yolo'))
        os.environ.setdefault('YOLO_AUTOINSTALL','false')
        import torch
        torch.set_num_threads(1)
        if torch.get_num_interop_threads()!=1:torch.set_num_interop_threads(1)
        from ultralytics import YOLO
        p=db.ROOT/'construction-safety-inspection/models/helmet_yolo11n/weights/best.pt'
        if not p.exists():raise FileNotFoundError('缺少本地安全帽检测权重')
        _model=YOLO(str(p))
    return _model

def iou(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    inter=x*y
    return inter/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)

def process(run_id,camera_id,max_frames=8,confidence=.5):
    try:return _process(run_id,camera_id,max_frames,confidence)
    except Exception as e:
        db.write('UPDATE monitor_runs SET status=?,error=?,finished_at=? WHERE id=?',('error','检测未完成：'+type(e).__name__+' '+str(e)[:120],db.now(),run_id))

def _process(run_id,camera_id,max_frames=8,confidence=.5):
    import cv2
    cv2.setNumThreads(1)
    camera=next(c for c in CAMERAS if c['id']==camera_id)
    requested_confidence=confidence;confidence=max(confidence,camera['confidence_floor'])
    path=db.ROOT/'videos'/camera['file'];cap=cv2.VideoCapture(str(path));frames=[];tracks=[];created=[]
    try:
        if not cap.isOpened():raise ValueError('本地演示视频不可读取')
        fps=cap.get(cv2.CAP_PROP_FPS) or 25;total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total<=0:raise ValueError('录像没有可读取帧')
        count=min(total,max_frames)
        indexes=sorted({round(i*(total-1)/max(1,count-1)) for i in range(count)})
        directory=db.ROOT/'backend/data/monitor';directory.mkdir(parents=True,exist_ok=True)
        video_hash=hashlib.sha256(path.read_bytes()).hexdigest();fingerprint=video_hash[:16]
        with _lock:
            yolo=model()
            db.write('UPDATE monitor_runs SET status=? WHERE id=?',('running',run_id))
            result={'camera_id':camera_id,'frames':frames,'snapshot_ids':created,'new_clues':0,'semantics':'局部相邻帧轨迹去重；线索条数不代表人数，必须人工核实','model':'本地YOLO11n安全帽权重','model_classes':yolo.names,'sampling':'均匀抽取全片帧，离线检测，不是实时监控','video_sha256':video_hash,'duration':round(total/fps,3),'confidence_threshold':confidence,'requested_frames':len(indexes)}
            result.update(requested_confidence=requested_confidence,applicability=camera['applicability'])
            for sample,frame_index in enumerate(indexes):
                cap.set(cv2.CAP_PROP_POS_FRAMES,frame_index);valid,frame=cap.read()
                if not valid:continue
                prediction=yolo.predict(frame,conf=confidence,imgsz=1280,verbose=False,device='cpu')[0]
                raw=[(int(b.cls[0]),float(b.conf[0]),b.xyxy[0].tolist()) for b in prediction.boxes]
                detections=map_head_classes(raw,confidence)
                image=frame.copy();height,width=image.shape[:2]
                for d in detections:
                    x1,y1,x2,y2=map(int,d['bbox']);color=(40,190,40) if d['class_id']==0 else (20,40,230)
                    cv2.rectangle(image,(x1,y1),(x2,y2),color,2);cv2.putText(image,('HELMET' if d['class_id']==0 else 'NO HELMET')+f" {d['confidence']:.2f}",(x1,max(20,y1-5)),cv2.FONT_HERSHEY_SIMPLEX,.55,color,2)
                filename=f'{run_id}-{sample:03d}.jpg';image_path=directory/filename
                ok,payload=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:continue
                image_path.write_bytes(payload.tobytes());relative=str(image_path.relative_to(db.ROOT))
                fid=db.write('INSERT INTO monitor_frames(run_id,camera_id,media_time,image_path,detections_json,created_at) VALUES(?,?,?,?,?,?)',(run_id,camera_id,round(frame_index/fps,3),relative,db.dumps({'width':width,'height':height,'detections':detections}),db.now()))
                frames.append({'id':fid,'media_time':round(frame_index/fps,3),'helmet_on':sum(d['class_id']==0 for d in detections),'helmet_off':sum(d['class_id']==1 for d in detections),'detections':detections,'width':width,'height':height})
                used=set()
                for d in [x for x in detections if x['class_id']==1]:
                    match=next((i for i,t in enumerate(tracks) if i not in used and frame_index/fps-t['time']<=3 and iou(t['bbox'],d['bbox'])>.2),None)
                    if match is not None:tracks[match].update(bbox=d['bbox'],time=frame_index/fps);used.add(match);continue
                    tracks.append({'bbox':d['bbox'],'time':frame_index/fps});used.add(len(tracks)-1)
                    key=f'{camera_id}|{fingerprint}|{frame_index}|'+','.join(str(round(x/10)) for x in d['bbox'])
                    with db.connect() as c:
                        cur=c.execute('INSERT OR IGNORE INTO monitor_snapshots(camera_id,captured_at,category,confidence,location,image_path,status,note,data_mode,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?)',(camera_id,db.now(),'未戴安全帽',round(d['confidence'],4),camera['location'],relative,'pending',db.dumps({'run_id':run_id,'media_time':frame_index/fps,'bbox':d['bbox'],'model_class_semantics':'Helmet/NOHelmet，头部目标'}),'yolo',key))
                        if cur.rowcount:created.append(cur.lastrowid)
                result['new_clues']=len(created)
                db.write('UPDATE monitor_runs SET result_json=? WHERE id=?',(db.dumps(result),run_id))
            if not frames:raise ValueError('抽帧失败，没有生成检测图片')
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
