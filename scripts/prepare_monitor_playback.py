import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def build(camera,force=False):
    import cv2
    import imageio_ffmpeg
    from backend.app import db
    from backend.vision.detector import model,map_head_classes
    from backend.vision.playback import digest,playback
    if not force and playback(camera['id'])['available']:
        print(camera['id']+' 已有有效缓存',flush=True);return
    cv2.setNumThreads(1)
    path=ROOT/'videos'/camera['file'];cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():raise RuntimeError('录像不可读取：'+camera['id'])
    directory=ROOT/'videos/ai_playback';directory.mkdir(exist_ok=True)
    source_fps=cap.get(cv2.CAP_PROP_FPS);total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));width=int(cap.get(3));height=int(cap.get(4))
    fps=10 if camera['id']=='CAM-03' else 5
    threshold=max(.5,camera['confidence_floor'])
    weights=ROOT/'construction-safety-inspection/models/helmet_yolo11n/weights/best.pt'
    video_hash=digest(path);weight_hash=digest(weights)
    filename=f"{camera['id']}-{video_hash[:10]}-{weight_hash[:8]}.mp4"
    target=directory/filename;temporary=directory/(target.stem+'.building.mp4')
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-y','-loglevel','error','-threads','1','-f','rawvideo','-vcodec','rawvideo','-s',f'{width}x{height}','-pix_fmt','bgr24','-r',str(fps),'-i','-','-an','-c:v','libx264','-threads','1','-preset','fast','-crf','20','-bf','0','-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)]
    encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    frames=[];network=model();count=math.ceil(total/source_fps*fps)
    try:
        for sample in range(count):
            index=min(total-1,round(sample*source_fps/fps));cap.set(cv2.CAP_PROP_POS_FRAMES,index);valid,image=cap.read()
            if not valid:raise RuntimeError('时间轴帧读取失败：'+str(index))
            prediction=network.predict(image,conf=threshold,imgsz=1280,verbose=False,device='cpu')[0]
            detections=map_head_classes([(int(b.cls[0]),float(b.conf[0]),b.xyxy[0].tolist()) for b in prediction.boxes],threshold)
            encoder.stdin.write(image.tobytes())
            frames.append({'index':sample,'media_time':sample/fps,'source_time':index/source_fps,'source_frame':index,'detections':detections})
            if sample%25==0:print(f"{camera['id']} {sample+1}/{count}",flush=True)
        encoder.stdin.close();error=encoder.stderr.read().decode('utf-8',errors='replace');encoder.wait()
        if encoder.returncode:raise RuntimeError(error)
        temporary.replace(target)
        result={'camera_id':camera['id'],'mode':'yolo_cached','sampling':'真实 YOLO 逐帧离线检测；采样录像与检测框共用同一帧时间轴，非实时监控','fps':fps,'width':width,'height':height,'duration':len(frames)/fps,'source_duration':total/source_fps,'source_sha256':video_hash,'weights_sha256':weight_hash,'video_file':filename,'video_bytes':target.stat().st_size,'threshold':threshold,'model':'本地 YOLO11n 安全帽权重','created_at':db.now(),'frames':frames}
        manifest=directory/(camera['id']+'.json');pending=manifest.with_suffix('.building.json');pending.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');pending.replace(manifest)
        print(json.dumps({'camera_id':camera['id'],'frames':len(frames),'frames_with_heads':sum(bool(f['detections']) for f in frames),'threshold':threshold},ensure_ascii=False),flush=True)
    finally:
        cap.release()
        if encoder.poll() is None:encoder.kill();encoder.wait()

def main():
    from backend.vision.detector import CAMERAS
    parser=argparse.ArgumentParser();parser.add_argument('--camera',choices=[c['id'] for c in CAMERAS]);parser.add_argument('--force',action='store_true');args=parser.parse_args()
    ordered=sorted(CAMERAS,key=lambda c:c['id']!='CAM-03')
    for camera in ordered:
        if not args.camera or camera['id']==args.camera:build(camera,args.force)

if __name__=='__main__':main()
