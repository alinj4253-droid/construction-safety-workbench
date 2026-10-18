import hashlib
import json
from pathlib import Path
from backend.app import db
from backend.vision.detector import CAMERAS

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def playback(camera_id):
    camera=next(c for c in CAMERAS if c['id']==camera_id)
    manifest=db.ROOT/'videos/ai_playback'/f'{camera_id}.json'
    if not manifest.is_file():return {'available':False,'reason':'尚未生成逐帧检测回放，请运行 prepare_monitor_playback.py'}
    try:
        data=json.loads(manifest.read_text(encoding='utf-8'))
        source=db.ROOT/'videos'/camera['file']
        video=db.ROOT/'videos/ai_playback'/data['video_file']
        weight=db.ROOT/'construction-safety-inspection/models/helmet_yolo11n/weights/best.pt'
        if Path(data['video_file']).name!=data['video_file'] or not video.is_file():raise ValueError('检测回放文件缺失')
        if digest(source)!=data['source_sha256'] or digest(weight)!=data['weights_sha256']:raise ValueError('原录像或权重已变化，请重新生成检测回放')
        if video.stat().st_size!=data['video_bytes']:raise ValueError('检测回放文件不完整')
        if data['camera_id']!=camera_id or not data['frames']:raise ValueError('检测时间轴不匹配')
        return {**data,'available':True,'url':'/videos/ai_playback/'+data['video_file']}
    except (ValueError,KeyError,OSError) as e:return {'available':False,'reason':str(e)}
