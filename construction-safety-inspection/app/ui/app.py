"""Gradio 界面：工地安全智能巡检系统的主入口。

四个页签：
1. 图片检测   —— 上传单张工地照片，检测+判定+入台账
2. 视频检测   —— 上传视频文件，逐帧检测（含抽帧），违规入台账
3. 台账统计   —— 查看历史违规记录和统计
4. 智能报告   —— 一键触发双 Agent 流水线生成巡检报告

启动：python -m app.ui.app  （或 run.bat）
"""

from __future__ import annotations

import csv
import datetime as dt
import shutil
import subprocess
from pathlib import Path

import cv2
import gradio as gr
import numpy as np

from app import config
from app.agents import report_writer, safety_analyst
from app.detection import ledger
from app.detection.detector import FrameResult, HelmetDetector
from app.detection.rules import Violation, judge_frame

_state = {"model_ok": False, "model_msg": ""}

APP_CSS = """
:root {
    --ink: #122033;
    --muted: #667487;
    --navy: #17324d;
    --navy-2: #234f73;
    --orange: #e56a2e;
    --orange-soft: #fff3eb;
    --line: #dce5ed;
    --paper: #f6f8fb;
}
body { background: var(--paper); color: var(--ink); }
.gradio-container { max-width: 1440px !important; padding: 24px 34px 44px !important; }
.hero {
    background: linear-gradient(115deg, #10293f 0%, #1d4b6e 58%, #da642e 150%);
    border-radius: 18px; padding: 28px 34px; margin-bottom: 22px; color: #fff;
    box-shadow: 0 12px 30px rgba(17, 43, 67, .14);
}
.hero h1 { margin: 0 0 8px; font-size: 30px; letter-spacing: .02em; color: #fff; }
.hero p { margin: 0; color: #d9e7f2; font-size: 15px; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.hero-chip { border: 1px solid rgba(255,255,255,.24); border-radius: 999px; padding: 6px 11px; color: #f7fbff; background: rgba(255,255,255,.09); font-size: 12px; }
.section-note { color: var(--muted); font-size: 13px; margin: 2px 0 14px; }
.panel { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: 0 5px 18px rgba(17, 43, 67, .05); }
.panel-title { font-weight: 700; color: var(--navy); margin-bottom: 4px; }
.output-placeholder { color: #8492a3; background: #f8fafc; border: 1px dashed #cbd7e1; border-radius: 10px; padding: 14px; }
.danger-button button { color: #a23d16 !important; border-color: #f1b69b !important; background: var(--orange-soft) !important; }
.gr-button-primary { background: var(--orange) !important; border-color: var(--orange) !important; }
.gr-button-primary:hover { background: #c95322 !important; border-color: #c95322 !important; }
.tab-nav button { font-weight: 650 !important; }
footer { display: none !important; }
@media (max-width: 900px) { .gradio-container { padding: 14px 14px 30px !important; } .hero { padding: 22px; } .hero h1 { font-size: 24px; } }
"""


def _to_bgr(image) -> np.ndarray:
    """将 Gradio 的 RGB/RGBA 图像转换为检测器需要的 BGR。"""
    frame_rgb = image if isinstance(image, np.ndarray) else np.array(image)
    if frame_rgb.ndim != 3:
        raise gr.Error("图片格式无法识别，请重新上传一张 JPG 或 PNG 图片")
    if frame_rgb.shape[-1] == 4:
        frame_rgb = cv2.cvtColor(frame_rgb, cv2.COLOR_RGBA2RGB)
    if frame_rgb.shape[-1] != 3:
        raise gr.Error("图片通道数不正确，请重新上传一张彩色图片")
    return cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)


def _get_detector():
    """加载检测器（首次调用加载权重，之后复用单例）。"""
    return HelmetDetector.get_instance()


def _find_ffmpeg() -> str | None:
    """定位可用的 ffmpeg 可执行文件。

    优先使用系统 PATH 中的 ffmpeg；找不到时回退到 imageio-ffmpeg
    自带的静态二进制（requirements.txt 已声明该依赖）。
    """
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _remux_for_browser(src_path: str, fps: float) -> tuple[str, bool]:
    """把 OpenCV 写出的 mp4v 视频转封装/转码为浏览器可播的 H.264。

    浏览器 <video> 播放器不支持 OpenCV 默认的 mp4v（MPEG-4 Part 2）编码，
    导致结果视频"只能下载、无法在页面内播放"。这里用 ffmpeg 以 libx264
    重编码（失败时依次退回 openh264 / 流拷贝），输出 *_web.mp4。

    :return: (可播视频路径, 是否转码成功)；失败时原样返回源路径。
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return src_path, False
    web_path = str(Path(src_path).with_name(Path(src_path).stem + "_web.mp4"))
    attempts = [
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        ["-c:v", "libopenh264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        ["-c", "copy", "-movflags", "+faststart"],
    ]
    for codec_args in attempts:
        cmd = [ffmpeg, "-y", "-i", src_path, "-r", f"{fps:.3f}", *codec_args, web_path]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=600)
        except Exception:
            continue
        if proc.returncode == 0 and Path(web_path).exists() and Path(web_path).stat().st_size > 0:
            return web_path, True
    return src_path, False


def _save_preview_frame(frame_bgr: np.ndarray, frame_no: int, analyzed_no: int,
                        helmet_on: int, helmet_off: int) -> str:
    """保存一张抽帧标注结果图，返回文件路径（供界面画廊展示）。"""
    config.ensure_dirs()
    stamped = frame_bgr.copy()
    caption = f"Frame {frame_no}  helmet_on={helmet_on}  helmet_off={helmet_off}"
    cv2.putText(stamped, caption, (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (0, 0, 255), 2, cv2.LINE_AA)
    out = config.EXPORTS_DIR / f"frame_{dt.datetime.now().strftime('%H%M%S')}_{analyzed_no:04d}.jpg"
    cv2.imwrite(str(out), stamped, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return str(out)


def _same_person_box(a: tuple, b: tuple) -> bool:
    """判断相邻抽帧中的两个未戴帽框是否仍是同一个人。

    视频页不引入额外跟踪模型，使用检测框的 IoU 和中心位移做轻量关联。
    对演示视频这类连续画面足够稳定，也能避免同一人跨抽帧被重复累计。
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    area_a = max(1.0, ax2 - ax1) * max(1.0, ay2 - ay1)
    area_b = max(1.0, bx2 - bx1) * max(1.0, by2 - by1)
    union = area_a + area_b - inter
    if union > 0 and inter / union >= 0.10:
        return True

    aw, ah = max(1.0, ax2 - ax1), max(1.0, ay2 - ay1)
    bw, bh = max(1.0, bx2 - bx1), max(1.0, by2 - by1)
    acx, acy = (ax1 + ax2) / 2.0, (ay1 + ay2) / 2.0
    bcx, bcy = (bx1 + bx2) / 2.0, (by1 + by2) / 2.0
    # 摄像机连续移动时框可能只有部分重叠，中心位移仍能保持关联。
    return (abs(acx - bcx) / max(aw, bw) <= 0.90 and
            abs(acy - bcy) / max(ah, bh) <= 0.60)


def _update_unhelmeted_tracks(tracks: list[dict], detections: list,
                              sample_no: int, max_gap: int = 3) -> None:
    """将当前抽帧的未戴帽检测合并到轻量人员轨迹中。"""
    used: set[int] = set()
    for detection in detections:
        candidates = []
        for idx, track in enumerate(tracks):
            if idx in used or sample_no - track["last_sample"] > max_gap:
                continue
            if _same_person_box(track["box"], detection.xyxy):
                # 优先选择空间重叠更大的轨迹；没有重叠时按中心距离近似排序。
                tx1, ty1, tx2, ty2 = track["box"]
                dx1, dy1, dx2, dy2 = detection.xyxy
                iw = max(0.0, min(tx2, dx2) - max(tx1, dx1))
                ih = max(0.0, min(ty2, dy2) - max(ty1, dy1))
                inter = iw * ih
                ta = max(1.0, tx2 - tx1) * max(1.0, ty2 - ty1)
                da = max(1.0, dx2 - dx1) * max(1.0, dy2 - dy1)
                iou = inter / max(1.0, ta + da - inter)
                candidates.append((iou, idx))
        if candidates:
            _, idx = max(candidates)
            track = tracks[idx]
            track["box"] = detection.xyxy
            track["last_sample"] = sample_no
            track["min_conf"] = min(track["min_conf"], detection.conf)
            used.add(idx)
        else:
            tracks.append({
                "box": detection.xyxy,
                "last_sample": sample_no,
                "min_conf": detection.conf,
            })


def detect_image(image, source_name, conf_slider):
    """页签1：图片检测。"""
    if image is None:
        raise gr.Error("请先上传或拍摄一张工地照片")
    ledger.init_db()
    detector = _get_detector()
    frame = _to_bgr(image)
    result = detector.detect_frame(
        frame,
        conf=conf_slider,
        imgsz=config.IMAGE_INFER_SIZE,
        augment=config.IMAGE_AUGMENT,
    )
    # 某些大图中模型只给出 person 框而漏掉 hat 框。再用更大尺寸复核一次，
    # 如果找到了佩戴者就采用复核结果，避免把明显戴帽的人记成违规。
    if result.helmet_on == 0:
        retry = detector.detect_frame(
            frame,
            conf=conf_slider,
            imgsz=config.IMAGE_FALLBACK_SIZE,
            augment=True,
        )
        if retry.helmet_on > result.helmet_on or len(retry.detections) > len(result.detections):
            result = retry
    src = source_name.strip() or f"图片_{dt.datetime.now().strftime('%H%M%S')}"
    violation = judge_frame(result, source=src, conf_threshold=conf_slider)
    ledger_msg = "本帧未发现违规（或置信度低于阈值）"
    if violation is not None:
        ledger.insert_violation(violation)
        ledger_msg = (
            f"已记录违规：未戴安全帽 {violation.helmet_off} 人，"
            f"风险等级「{violation.severity}」，已写入台账"
        )
    summary = (
        f"**检测结果**：佩戴安全帽 **{result.helmet_on}** 人 | "
        f"未佩戴安全帽 **{result.helmet_off}** 人（置信度阈值 {conf_slider:.2f}）\n\n"
        f"{ledger_msg}"
    )
    return cv2.cvtColor(result.image, cv2.COLOR_BGR2RGB), summary


def detect_video(video_path, conf_slider, sample_fps):
    """页签2：视频检测（抽帧分析，违规帧入台账）。

    返回：(浏览器可播的结果视频, 分析摘要, 抽帧标注图文件列表)。
    """
    if not video_path:
        raise gr.Error("请先上传一段工地视频")
    ledger.init_db()
    # 画廊只展示本次分析的抽帧标注图，先清理上一轮遗留，避免 exports 膨胀
    for old in config.EXPORTS_DIR.glob("frame_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise gr.Error("视频无法打开，请检查文件格式")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    interval = max(1, int(round(fps / max(sample_fps, 0.5))))
    detector = _get_detector()

    # 输出视频：先写 mp4v 临时文件，结束后转码为浏览器可播的 H.264
    out_path = str(config.EXPORTS_DIR / f"video_result_{dt.datetime.now().strftime('%H%M%S')}.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = None

    total_violation_frames = 0
    unhelmeted_tracks: list[dict] = []
    peak_helmet_on = 0
    frame_idx = 0
    analyzed = 0
    preview_paths: list[str] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % interval == 0:
            result = detector.detect_frame(
                frame,
                conf=conf_slider,
                imgsz=config.VIDEO_INFER_SIZE,
                augment=False,
            )
            analyzed += 1
            # 抽帧标注结果：保存为图片，供页面画廊逐张查看
            preview_paths.append(_save_preview_frame(
                result.image, frame_idx + 1, analyzed,
                result.helmet_on, result.helmet_off))
            v = judge_frame(result, source=Path(video_path).name, conf_threshold=conf_slider)
            if v is not None:
                total_violation_frames += 1
                off_detections = [d for d in result.detections if d.cls_id == 1 and d.conf >= conf_slider]
                _update_unhelmeted_tracks(unhelmeted_tracks, off_detections, analyzed)
                peak_helmet_on = max(peak_helmet_on, result.helmet_on)
        else:
            result = FrameResult(image=frame)
        if writer is None:
            writer = cv2.VideoWriter(out_path, fourcc, fps,
                                     (frame.shape[1], frame.shape[0]))
        writer.write(result.image)
        frame_idx += 1
    cap.release()
    if writer:
        writer.release()

    # 转码为 H.264，解决"结果视频只能下载、无法在页面内播放"的问题
    playable_path, transcoded = _remux_for_browser(out_path, fps)

    # 同一人员在连续抽帧中只记一次；视频结束后写入一条汇总台账记录。
    unique_off = len(unhelmeted_tracks)
    if unique_off:
        min_conf = min(track["min_conf"] for track in unhelmeted_tracks)
        severity = "严重" if unique_off >= 2 else "一般"
        ledger.insert_violation(Violation(
            ts=dt.datetime.now().isoformat(timespec="seconds"),
            source=Path(video_path).name,
            helmet_off=unique_off,
            helmet_on=peak_helmet_on,
            conf_min=round(min_conf, 4),
            severity=severity,
        ))

    summary = (
        f"**视频分析完成**：共 {frame_idx} 帧，抽样分析 {analyzed} 帧\n\n"
        f"- 违规帧：**{total_violation_frames}** 帧\n"
        f"- 去重后未戴安全帽人数：**{unique_off}** 人\n"
        f"- 台账记录：**{1 if unique_off else 0}** 条（按人员轨迹去重）\n"
        f"- 结果视频已保存：`{playable_path}`"
        + ("" if transcoded else
           "\n- ⚠️ 未找到 ffmpeg，结果视频保留 mp4v 编码，页面内可能无法播放，请下载后用本地播放器查看")
    )
    return playable_path, summary, preview_paths


def ledger_view():
    """页签3：台账表 + 统计。"""
    rows = ledger.list_violations(limit=200)
    stat = ledger.stats()
    stat_md = (
        f"### 台账统计\n"
        f"| 指标 | 数值 |\n|---|---|\n"
        f"| 累计违规次数 | {stat['count']} |\n"
        f"| 累计未戴帽人次 | {stat['persons']} |\n"
        f"| 严重违规次数（≥2人同时未戴） | {stat['severe']} |\n"
        f"| 最近违规时间 | {stat['latest'] or '—'} |"
    )
    table = [[r["ts"], r["source"], r["helmet_off"], r["helmet_on"],
              f"{r['conf_min']:.2f}", r["severity"]] for r in rows]
    return table, stat_md


def export_csv():
    """导出台账 CSV。"""
    rows = ledger.list_violations(limit=100000)
    if not rows:
        raise gr.Error("台账为空，无数据可导出")
    out = config.EXPORTS_DIR / f"violations_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["时间", "来源", "未戴帽人数", "戴帽人数", "最低置信度", "严重度"])
        for r in rows:
            w.writerow([r["ts"], r["source"], r["helmet_off"], r["helmet_on"],
                        r["conf_min"], r["severity"]])
    return str(out)


def clear_ledger():
    """清空台账并同步刷新统计与表格（演示重置）。

    返回值顺序与界面绑定一致：(统计, 表格, 提示语)。
    """
    n = ledger.clear()
    table, stat_md = ledger_view()
    msg = f"已清空台账（删除 {n} 条记录），统计与列表已重置。"
    return stat_md, table, msg


def generate_report():
    """页签4：双 Agent 流水线：安全分析 -> 报告撰写。"""
    try:
        analysis = safety_analyst.analyze()
        report_md = report_writer.write_report(analysis)
    except Exception as e:
        raise gr.Error(f"Agent 调用失败：{e}。请检查 .env 中的 API 配置与网络。")
    out = config.EXPORTS_DIR / f"巡检报告_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out.write_text(report_md, encoding="utf-8")
    analysis_md = (
        "### 安全分析 Agent 输出（快模型）\n\n"
        f"- 风险等级：**{analysis.get('risk_level', '未知')}**\n"
        f"- 判定理由：{analysis.get('risk_level_reason', '—')}\n\n"
        + "\n".join(f"- {p}" for p in analysis.get("patterns", []))
    )
    return analysis_md, report_md, str(out)


def build_ui():
    config.ensure_dirs()
    ledger.init_db()
    demo_images = [
        (config.PROJECT_ROOT / "demo_images" / "featured_safety_exception.jpg", "双人对照场景"),
        (config.PROJECT_ROOT / "demo_images" / "test_site_gate_01.jpg", "进场安全帽检查"),
        (config.PROJECT_ROOT / "demo_images" / "test_survey_team_03.jpg", "测量作业团队"),
    ]
    demo_images = [(str(path), label) for path, label in demo_images if path.exists()]
    demo_videos = [
        (config.PROJECT_ROOT / "demo_videos" / "工地实拍_脚手架检查_pexels32244795.mp4",
         "推荐演示视频：脚手架检查"),
    ]
    demo_videos = [(str(path), label) for path, label in demo_videos if path.exists()]
    with gr.Blocks(title="建筑工地安全智能巡检系统", fill_width=True) as demo:
        gr.HTML(
            "<section class='hero'>"
            "<h1>建筑工地安全智能巡检系统</h1>"
            "<p>把现场照片和视频转成可追踪的安全帽检查结果，支持违规台账与智能巡检报告。</p>"
            "<div class='hero-meta'><span class='hero-chip'>YOLO 视觉检测</span>"
            "<span class='hero-chip'>SQLite 违规台账</span><span class='hero-chip'>双 Agent 报告</span>"
            "<span class='hero-chip'>安全生产法第四十五条 · JGJ 59-2011</span></div></section>"
        )
        gr.Markdown("上传一张现场图片或视频开始演示；首次使用建议从图片检测页的施工现场样例开始。", elem_classes="section-note")
        with gr.Tab("📷 图片检测"):
            with gr.Row():
                with gr.Column(elem_classes="panel", scale=5):
                    gr.Markdown("### 现场图片检测\n上传后调整阈值，结果会同步写入违规台账。", elem_classes="panel-title")
                    img_in = gr.Image(label="工地照片（点击上传）", type="numpy", sources=["upload"])
                    source_name = gr.Textbox(label="来源标注（如：3号楼东侧出入口）", value="")
                    conf_slider = gr.Slider(0.1, 0.9, value=config.CONF_THRESHOLD, step=0.05,
                                            label="人员置信度阈值（低于该值不计入统计/违规）")
                    gr.Markdown(
                        "建议：**0.25 召回优先**（小目标更多） · **0.35 平衡** · "
                        "**0.55 严格**（误检更少）。此数值作用于人员框；安全帽框使用内部召回阈值参与佩戴关联。图片页使用高分辨率增强推理。",
                        elem_classes="section-note",
                    )
                    btn_img = gr.Button("开始检测", variant="primary")
                    if demo_images:
                        gr.Examples(
                            examples=[[path, label] for path, label in demo_images],
                            inputs=[img_in, source_name],
                            label="施工现场样例",
                            examples_per_page=4,
                        )
                with gr.Column(elem_classes="panel", scale=6):
                    gr.Markdown("### 检测结果\n框选结果与违规说明会显示在这里。", elem_classes="panel-title")
                    img_out = gr.Image(label="检测结果", interactive=False)
                    img_summary = gr.Markdown("上传图片后显示判定结果。", label="判定结果", elem_classes="output-placeholder")
            btn_img.click(detect_image, [img_in, source_name, conf_slider], [img_out, img_summary])

        with gr.Tab("🎬 视频检测"):
            with gr.Row():
                with gr.Column(elem_classes="panel", scale=5):
                    gr.Markdown("### 现场视频检测\n按设定帧率抽样分析，避免长视频逐帧推理造成等待。", elem_classes="panel-title")
                    vid_in = gr.Video(label="工地视频", sources=["upload"])
                    conf_slider2 = gr.Slider(0.1, 0.9, value=config.CONF_THRESHOLD, step=0.05,
                                             label="人员置信度阈值（低于该值不计入统计/违规）")
                    gr.Markdown(
                        "视频演示建议使用 **0.35**；画面远、小目标多时可降到 **0.25**。此数值筛选人员框，安全帽框只用于佩戴关联。",
                        elem_classes="section-note",
                    )
                    fps_slider = gr.Slider(1, 10, value=2, step=1,
                                           label="分析帧率（每秒抽帧数）")
                    btn_vid = gr.Button("开始分析", variant="primary")
                    if demo_videos:
                        gr.Examples(
                            examples=[[path] for path, _ in demo_videos],
                            inputs=[vid_in],
                            label="工地样例视频",
                            examples_per_page=2,
                            cache_examples=False,
                        )
                with gr.Column(elem_classes="panel", scale=6):
                    gr.Markdown("### 分析结果\n视频输出和违规帧统计会显示在这里。", elem_classes="panel-title")
                    vid_out = gr.Video(label="标注结果视频（页面内可直接播放）", interactive=False)
                    vid_summary = gr.Markdown("上传视频后显示分析结果。", label="分析结果", elem_classes="output-placeholder")
                    gr.Markdown("### 抽帧标注结果\n每次抽帧检测的标注画面逐张展示，点击可放大查看。", elem_classes="panel-title")
                    frame_gallery = gr.Gallery(label="抽帧标注帧", columns=4, height=260,
                                               object_fit="contain", interactive=False)
            btn_vid.click(detect_video, [vid_in, conf_slider2, fps_slider],
                          [vid_out, vid_summary, frame_gallery])

        with gr.Tab("📋 违规台账") as ledger_tab:
            with gr.Row():
                btn_refresh = gr.Button("刷新台账", variant="secondary")
                btn_clear = gr.Button("清空台账", elem_classes="danger-button")
            stat_md = gr.Markdown("正在读取台账统计……", elem_classes="panel")
            table = gr.Dataframe(
                headers=["时间", "来源", "未戴帽人数", "戴帽人数", "最低置信度", "严重度"],
                label="违规记录（最近200条）",
                interactive=False,
            )
            clear_msg = gr.Markdown()
            btn_refresh.click(ledger_view, None, [table, stat_md])
            btn_clear.click(clear_ledger, None, [stat_md, table, clear_msg])
            ledger_tab.select(ledger_view, None, [table, stat_md])
            demo.load(ledger_view, None, [table, stat_md])

        with gr.Tab("🤖 智能报告"):
            gr.Markdown("### 双 Agent 巡检报告\n安全分析 Agent 先整理风险，再由报告撰写 Agent 输出正式 Markdown 报告。生成通常需要 30–60 秒。", elem_classes="panel-title")
            btn_report = gr.Button("🚀 生成巡检报告", variant="primary")
            analysis_md = gr.Markdown("生成后显示风险等级、违规模式与建议措施。", label="安全分析输出", elem_classes="output-placeholder")
            report_md = gr.Markdown("生成后显示正式巡检报告。", label="巡检报告", elem_classes="output-placeholder")
            report_file = gr.File(label="报告文件（Markdown）")
            btn_report.click(generate_report, None, [analysis_md, report_md, report_file])

        # 初始化台账表结构（首次访问时由各页签按钮触发查询）
    return demo


if __name__ == "__main__":
    import os
    config.ensure_dirs()
    ledger.init_db()
    demo = build_ui()
    # 自动化测试时设置 NO_BROWSER=1 可避免弹浏览器窗口
    demo.launch(server_name="127.0.0.1", server_port=7860,
                inbrowser=not os.environ.get("NO_BROWSER"),
                theme=gr.themes.Soft(primary_hue="orange", secondary_hue="slate"),
                css=APP_CSS)
