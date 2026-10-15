import json
from pathlib import Path
import cv2
from backend.vision.detector import model,map_head_classes
from backend.app import db
yolo=model();results=[]
paths=[db.ROOT/'artifacts/vision-frame.jpg']+list((db.ROOT/'construction-safety-inspection/demo_images').glob('test_site_crew*'))+list((db.ROOT/'construction-safety-inspection/demo_images').glob('61o*'))
for p in paths:
    image=cv2.imdecode(__import__('numpy').frombuffer(p.read_bytes(),dtype='uint8'),1)
    prediction=yolo.predict(image,conf=.1,imgsz=1280,verbose=False,device='cpu')[0]
    raw=[(int(b.cls[0]),round(float(b.conf[0]),4),b.xyxy[0].tolist()) for b in prediction.boxes]
    ds=map_head_classes(raw,.35)
    results.append({'file':str(p.relative_to(db.ROOT)),'raw_at_0_1':[(c,cf) for c,cf,_ in raw],'accepted_at_0_35':len(ds)})
    if ds:
        for d in ds:
            x1,y1,x2,y2=map(int,d['bbox']);color=(0,200,0) if d['class_id']==0 else (0,0,255)
            cv2.rectangle(image,(x1,y1),(x2,y2),color,2);cv2.putText(image,str(d['class_id'])+f" {d['confidence']:.2f}",(x1,max(20,y1-3)),cv2.FONT_HERSHEY_SIMPLEX,.6,color,2)
        ok,data=cv2.imencode('.jpg',image);(db.ROOT/'artifacts'/('vision-check-'+p.stem[:15]+'.jpg')).write_bytes(data.tobytes())
(db.ROOT/'artifacts/vision-diagnostic.json').write_text(db.dumps(results),encoding='utf-8');print(db.dumps(results))
