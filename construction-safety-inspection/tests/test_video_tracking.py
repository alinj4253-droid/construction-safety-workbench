"""视频抽帧去重逻辑测试。"""

from app.detection.detector import Detection
from app.ui.app import _same_person_box, _update_unhelmeted_tracks


def _off(box, conf=0.5):
    return Detection(cls_id=1, conf=conf, xyxy=box)


def test_moving_person_is_one_track():
    tracks = []
    _update_unhelmeted_tracks(tracks, [_off((1243, 1157, 1442, 1340))], 1)
    _update_unhelmeted_tracks(tracks, [_off((1396, 1151, 1572, 1394))], 2)
    _update_unhelmeted_tracks(tracks, [_off((1491, 1189, 1681, 1390))], 3)
    assert len(tracks) == 1


def test_different_people_are_two_tracks():
    tracks = []
    _update_unhelmeted_tracks(
        tracks,
        [_off((100, 100, 220, 400)), _off((600, 100, 720, 400))],
        1,
    )
    assert len(tracks) == 2


def test_track_expires_after_long_gap():
    tracks = []
    _update_unhelmeted_tracks(tracks, [_off((100, 100, 220, 400))], 1)
    _update_unhelmeted_tracks(tracks, [_off((105, 105, 225, 405))], 5)
    assert len(tracks) == 2


def test_center_motion_can_match_without_iou():
    assert _same_person_box((100, 100, 220, 400), (190, 105, 310, 405))
