"""端到端验收：模拟界面四页签核心操作 + 视频检测 + GPU 测速 + 启动文件自检。

运行：.venv\\Scripts\\python.exe scripts\\e2e_verify.py
全部通过时最后打印 ALL_E2E_OK。
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from app import config  # noqa: E402
from app.detection import ledger  # noqa: E402
from app.ui import app as ui  # noqa: E402


def test_image_detection():
    print("== 1. 图片检测页签 ==", flush=True)
    imgs = sorted((ROOT / "demo_images").glob("*.jpg"))
    assert imgs, "demo_images 为空"
    # 找一张能检出目标的图
    p, frame = imgs[0], cv2.imread(str(imgs[0]))
    for cand in imgs:
        f = cv2.imread(str(cand))
        if f is None:
            continue
        out, summary = ui.detect_image(f, f"验收_{cand.name[:20]}", 0.35)
        if "佩戴安全帽 **0**" not in summary or "未佩戴安全帽 **0**" not in summary:
            p, frame = cand, f
            break
    out_img, summary = ui.detect_image(frame, f"验收_{p.name[:20]}", 0.35)
    print(summary, flush=True)
    assert out_img is not None, "检测输出图像为空"
    return True


def test_video_detection():
    print("\n== 2. 视频检测页签 ==", flush=True)
    # 用演示图合成一段 9 秒测试视频（3 图 × 30 帧 @ 10fps）
    imgs = [cv2.imread(str(p)) for p in sorted((ROOT / "demo_images").glob("*.jpg"))[:3]]
    imgs = [cv2.resize(im, (640, 480)) for im in imgs if im is not None]
    assert imgs, "无可用演示图"
    tmp_video = ROOT / "exports" / "_e2e_test_input.mp4"
    tmp_video.parent.mkdir(exist_ok=True)
    vw = cv2.VideoWriter(str(tmp_video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 480))
    for im in imgs:
        for _ in range(30):
            vw.write(im)
    vw.release()

    out_path, summary, previews = ui.detect_video(str(tmp_video), 0.35, 2.0)
    print(summary[:200], flush=True)
    assert Path(out_path).exists(), "结果视频未生成"
    assert "视频分析完成" in summary, "分析摘要异常"
    # 浏览器可播校验：转码产物存在且为 H.264(avc1) 编码
    assert out_path.endswith("_web.mp4"), f"结果视频未转码为可播格式: {out_path}"
    assert b"avc1" in Path(out_path).read_bytes()[:4096], "结果视频不含 H.264(avc1) 标记"
    # 抽帧标注预览校验
    assert len(previews) >= 1, "抽帧标注预览为空"
    assert all(Path(p).exists() for p in previews), "存在缺失的抽帧预览图"
    print(f"抽帧标注预览 {len(previews)} 张，可播视频: {out_path}", flush=True)
    for p in previews:
        Path(p).unlink(missing_ok=True)
    if out_path != str(tmp_video):
        Path(out_path.replace("_web.mp4", ".mp4")).unlink(missing_ok=True)
    tmp_video.unlink(missing_ok=True)
    return True


def test_ledger_and_csv():
    print("\n== 3. 台账页签 + CSV 导出 ==", flush=True)
    rows, stat_md = ui.ledger_view()
    print(stat_md, flush=True)
    assert len(rows) >= 1, "台账为空"
    csv_path = ui.export_csv()
    assert Path(csv_path).exists(), "CSV 未生成"
    print(f"CSV: {csv_path}", flush=True)
    return True


def test_agent_report():
    print("\n== 4. 智能报告页签（双 Agent）==", flush=True)
    analysis_md, report_md, report_file = ui.generate_report()
    print(analysis_md[:300], flush=True)
    print(f"\n报告文件: {report_file}", flush=True)
    assert "巡检报告" in report_md, "报告标题缺失"
    assert "第四十五条" in report_md or "安全生产法" in report_md, "法规引用缺失"
    return True


def test_gpu_speed():
    print("\n== 5. GPU 推理测速 ==", flush=True)
    from app.detection.detector import HelmetDetector
    det = HelmetDetector.get_instance()
    frame = cv2.imread(str(next((ROOT / "demo_images").glob("*.jpg"))))
    det.detect_frame(frame)  # 预热
    t0 = time.perf_counter()
    n = 20
    for _ in range(n):
        det.detect_frame(frame)
    cost = (time.perf_counter() - t0) / n * 1000
    print(f"单帧平均耗时: {cost:.1f} ms（约 {1000/cost:.0f} FPS）", flush=True)
    assert cost < 500, f"推理过慢: {cost:.0f}ms"
    return True


def test_launch_files():
    print("\n== 6. 启动文件自检 ==", flush=True)
    run_bat = ROOT / "run.bat"
    assert run_bat.exists(), "run.bat 缺失"
    content = run_bat.read_text(encoding="ascii", errors="strict")
    assert ".venv\\Scripts\\python.exe" in content, "run.bat 启动命令异常"
    print("run.bat 存在且为纯 ASCII（无 cmd 编码风险）✅", flush=True)
    env = ROOT / ".env"
    lines = [l for l in env.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    assert env.exists() and len(lines) >= 5, ".env 配置不完整"
    print(f".env 配置存在（{len(lines)} 项）✅", flush=True)
    return True


if __name__ == "__main__":
    ok = all([
        test_launch_files(),
        test_image_detection(),
        test_video_detection(),
        test_ledger_and_csv(),
        test_agent_report(),
        test_gpu_speed(),
    ])
    print("\nALL_E2E_OK" if ok else "\nE2E_FAILED", flush=True)
    sys.exit(0 if ok else 1)

