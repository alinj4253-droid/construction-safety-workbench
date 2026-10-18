import hashlib
import json
from pathlib import Path
from backend.app import db
from backend.vision.playback import playback

def test_playback_rejects_changed_materials_and_wrong_camera(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'ROOT',tmp_path)
    directory=tmp_path/'videos/ai_playback';directory.mkdir(parents=True)
    source=tmp_path/'videos/cam03_workers.mp4';source.write_bytes(b'isolated source fixture')
    weight=tmp_path/'construction-safety-inspection/models/helmet_yolo11n/weights/best.pt';weight.parent.mkdir(parents=True);weight.write_bytes(b'isolated model fixture')
    assert not playback('CAM-03')['available']
    video=directory/'test.mp4';video.write_bytes(b'isolated video fixture')
    data={'camera_id':'CAM-03','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'weights_sha256':hashlib.sha256(weight.read_bytes()).hexdigest(),'video_file':'test.mp4','video_bytes':video.stat().st_size,'frames':[{'index':0,'detections':[]}]}
    manifest=directory/'CAM-03.json';manifest.write_text(json.dumps(data),encoding='utf-8')
    assert playback('CAM-03')['available']
    source.write_bytes(b'changed');assert not playback('CAM-03')['available']
    source.write_bytes(b'isolated source fixture');data['video_file']='../outside.mp4';manifest.write_text(json.dumps(data),encoding='utf-8')
    assert not playback('CAM-03')['available']
