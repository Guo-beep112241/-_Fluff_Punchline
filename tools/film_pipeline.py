#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""film_pipeline — Ep1–Ep8 逐镜生产流水线（静帧驱动）

  ① frames  首帧合成   generate_image（场景图 + 真实照片）→ 20_生成结果/<ep>/frames/shNN.png
  ② videos  图生视频   Hailuo 2.3 first_frame 6s/768P      → 20_生成结果/<ep>/shots/shNN.mp4
  ③ audio   TTS + 程序化环境音/音效 + BGM                  → 20_生成结果/<ep>/audio/
  ④ build   剪辑成片   字幕/片头/彩蛋/片尾                 → 30_成片/<ep>_final_9x16.mp4

子命令之间可反复重跑（幂等：已存在的产物默认跳过）。
规格见 docs/拍摄规格_静帧流水线.md。

用法：
  python3 tools/film_pipeline.py frames --ep ep01
  python3 tools/film_pipeline.py videos --ep ep01 --concurrency 3
  python3 tools/film_pipeline.py audio  --ep ep01
  python3 tools/film_pipeline.py build  --ep ep01
  python3 tools/film_pipeline.py all    --ep ep01
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_lib as A  # noqa: E402
import mx             # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(PROJECT, "20_生成结果")
FINAL_DIR = os.path.join(PROJECT, "30_成片")
TASKS_JSON = os.path.join(PROJECT, "docs", "film_tasks.json")
SCENE_DIR = os.path.join(PROJECT, "10_工作素材", "scenes")
ADULT_DIR = os.path.join(PROJECT, "10_工作素材", "characters", "_curated", "adult")
HABITS_DIR = os.path.join(PROJECT, "10_工作素材", "habits", "_curated")

SCENES = {
    "noticeboard": "scene_campus_noticeboard_01.jpg",
    "corridor": "scene_campus_corridor_01.jpg",
    "dorm": "scene_dorm_floor_01.jpg",
    "rehearsal": "scene_rehearsal_room_01.jpg",
    "lecture": "scene_lecture_hall_01.jpg",
    "theatre": "scene_theatre_stage_01.jpg",
    "home": "scene_livingroom_01.jpg",
    "campus": "scene_campus_path_01.jpg",
    "field": "scene_campus_field_01.jpg",
    "gate": "scene_campus_gate_01.jpg",
    "booth": "scene_club_booth_01.jpg",
    "dormhall": "scene_dorm_hall_01.jpg",
}

VOICES = {
    # who: (edge-tts voice, rate, pitch)
    # 基线语速按「相声抢白」的节奏定：甲乙要能在一镜里把两句说完。
    "xiao": ("zh-CN-YunxiNeural", "+12%", "+10Hz"),
    "jiajia": ("zh-CN-XiaoxiaoNeural", "+14%", "+0Hz"),
    "hengjie": ("zh-CN-XiaoyiNeural", "+0%", "-30Hz"),
    "bingge": ("zh-CN-YunjianNeural", "-6%", "-45Hz"),
    "shezhang": ("zh-CN-YunyangNeural", "+2%", "-10Hz"),
    "roommate": ("zh-CN-YunxiaNeural", "+12%", "+12Hz"),
    "teacher": ("zh-CN-XiaoxiaoNeural", "-2%", "-5Hz"),
    "panel": ("zh-CN-YunjianNeural", "-12%", "-55Hz"),
    "classmate": ("zh-CN-YunxiaNeural", "+8%", "+5Hz"),
    "dougen": ("zh-CN-YunyangNeural", "+26%", "+15Hz"),   # 甲·逗哏
    "penggen": ("zh-CN-YunjianNeural", "+20%", "-25Hz"),   # 乙·捧哏
    "bianmu": ("zh-CN-YunxiaNeural", "+24%", "+18Hz"),    # 边牧（狗友）
    "alaska": ("zh-CN-YunjianNeural", "+8%", "-40Hz"),    # 阿拉斯加（狗友）
    "pup": ("zh-CN-XiaoyiNeural", "+26%", "+55Hz"),       # 小边牧（狗友·幼）
}

EDGE_TTS = os.path.expanduser("~/XiaoliuerVideoGen/venv/bin/edge-tts")

FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

# 全局追加到每条首帧提示词后面：压住"标准赛级萨摩耶"的品种先验
DOG_SUFFIX = (
    "。这只狗的毛量中等、服帖，不要浓密的双层毛、不要狮子鬃毛、不要蓬松的围脖；"
    "头型圆而软、额头宽圆，眼睛大而圆、不要细长杏仁眼；耳朵小三角、贴着头，尖端略向前折，"
    "不要大而立的尖耳；口鼻短而宽；胸窄、两前腿之间有空隙、腿细长、爪子略大；"
    "神态年轻、认真、有点急切，不要威严、高傲、庄严。"
)

FFMPEG = None


def ffmpeg():
    global FFMPEG
    if FFMPEG is None:
        from imageio_ffmpeg import get_ffmpeg_exe
        FFMPEG = get_ffmpeg_exe()
    return FFMPEG


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_duration(path):
    out = run([ffmpeg(), "-hide_banner", "-i", path])
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out.stderr)
    if not m:
        return 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


# ---------------------------------------------------------------- 规格

def load_spec(ep):
    path = os.path.join(PROJECT, "episodes", ep, "shots.json")
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    shots = sorted(spec["shots"], key=lambda s: s["id"])
    ids = [s["id"] for s in shots]
    if ids != list(range(1, len(shots) + 1)):
        raise SystemExit("%s 镜号不连续：%s" % (ep, ids))
    return spec


def ep_dir(ep, sub):
    d = os.path.join(OUT_ROOT, ep, sub)
    os.makedirs(d, exist_ok=True)
    return d


def frame_path(ep, sid):
    return os.path.join(ep_dir(ep, "frames"), "sh%02d.png" % sid)


def video_path(ep, sid):
    """优先 shNN.mp4；否则找 H3 批量提交的 epNN_shNN_v*_*.mp4。

    不做复制——同一段视频在仓库里存两份会让 Git LFS 体积翻倍。
    """
    d = ep_dir(ep, "shots")
    plain = os.path.join(d, "sh%02d.mp4" % sid)
    if os.path.exists(plain):
        return plain
    import glob as _glob
    hits = sorted(_glob.glob(os.path.join(d, "ep%s_sh%02d_v*_*.mp4" % (ep.replace("ep", ""), sid))))
    return hits[-1] if hits else plain


def audio_dir(ep):
    return ep_dir(ep, "audio")


# ---------------------------------------------------------------- ① 首帧

def cover_crop(src, dst, w=768, h=1376):
    """等比放大到覆盖目标画幅后居中裁剪，统一成 9:16。"""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    scale = max(w / sw, h / sh)
    nw, nh = int(math.ceil(sw * scale)), int(math.ceil(sh * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    im = im.crop((left, top, left + w, top + h))
    im.save(dst, "PNG")
    return dst


def make_frame(ep, shot):
    sid = shot["id"]
    dst = frame_path(ep, sid)
    if os.path.exists(dst) and os.path.getsize(dst) > 10000:
        return dst, "skip"
    scene_img = os.path.join(SCENE_DIR, SCENES[shot["scene"]])
    refs = [os.path.join(PROJECT, r) if not os.path.isabs(r) else r for r in shot.get("refs") or []]
    refs = [r for r in refs if os.path.exists(r)]

    if not refs:
        cover_crop(scene_img, dst)
        return dst, "plate"

    prompt = shot["frame_prompt"] + DOG_SUFFIX
    inputs = [mx.upload(scene_img, "image/jpeg")] + [mx.upload(r, "image/jpeg") for r in refs]
    req = {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "resolution": "1K",
        "input_urls": inputs,
        "output_file": "sh%02d.png" % sid,
    }
    r = mx.call("connector__matrix__generate_image", {"requests": [req]})
    if r.get("code") not in (0, None) or not r.get("success_items"):
        raise RuntimeError("首帧失败 %s: %s" % (sid, json.dumps(r, ensure_ascii=False)[:300]))
    item = r["success_items"][0]
    tmp = dst + ".dl"
    mx.download(mx.asset_url(item["node_id"]), tmp)
    cover_crop(tmp, dst)
    os.unlink(tmp)
    return dst, "gen"


def cmd_frames(args):
    spec = load_spec(args.ep)
    wanted = set(int(x) for x in args.shots.split(",")) if args.shots else None
    todo = [s for s in spec["shots"] if wanted is None or s["id"] in wanted]
    ok, fail = 0, []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(make_frame, args.ep, s): s for s in todo}
        for f in as_completed(futs):
            s = futs[f]
            try:
                p, how = f.result()
                ok += 1
                print("  帧 %02d %-5s %s" % (s["id"], how, os.path.basename(p)))
            except Exception as e:  # noqa: BLE001
                fail.append((s["id"], str(e)))
                print("  帧 %02d ❌ %s" % (s["id"], e))
    print("首帧完成 %d/%d，失败 %d" % (ok, len(todo), len(fail)))
    return 0 if not fail else 1


# ---------------------------------------------------------------- ② 视频

def load_tasks():
    if os.path.exists(TASKS_JSON):
        with open(TASKS_JSON, encoding="utf-8") as f:
            doc = json.load(f)
    else:
        doc = {"tasks": {}}
    doc.setdefault("tasks", {})
    return doc


def save_tasks(doc):
    tmp = TASKS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, TASKS_JSON)


def submit_video(ep, shot):
    fpath = frame_path(ep, shot["id"])
    url = mx.upload(fpath, "image/png")
    motion = shot.get("motion") or "Subtle natural movement, static camera."
    prompt = ("%s. Shot on a phone, realistic documentary footage, natural light, "
              "the same dog, same room, no text, no captions, no watermark." % motion.strip())
    args = {
        "model": "MiniMax-Hailuo-2.3",
        "prompt": prompt,
        "duration": 6,
        "resolution": args_resolution(),
        "input_image": {"url": url, "mime_type": "image/png"},
        "reference_type": "first_frame",
    }
    r = mx.call("connector__matrix__submit_video_generation", args)
    if r.get("code") not in (0, None) or not r.get("task_id"):
        raise RuntimeError(json.dumps(r, ensure_ascii=False)[:400])
    return str(r["task_id"])


_RES = "768P"


def args_resolution():
    return _RES


def cmd_videos(args):
    global _RES
    _RES = args.resolution
    spec = load_spec(args.ep)
    wanted = set(int(x) for x in args.shots.split(",")) if args.shots else None
    doc = load_tasks()

    # 每镜一条记录：episode/shot/status/task_id/attempts
    recs = {}
    for tid, t in list(doc["tasks"].items()):
        if t.get("episode") == args.ep and t.get("shot") is not None:
            recs.setdefault(int(t["shot"]), dict(t, task_id=tid))

    queue = []
    for s in spec["shots"]:
        sid = s["id"]
        if wanted is not None and sid not in wanted:
            continue
        vp = video_path(args.ep, sid)
        if os.path.exists(vp) and os.path.getsize(vp) > 50000:
            continue
        rec = recs.get(sid, {})
        if rec.get("status") in ("succeeded",):
            continue  # 已成功但文件丢了：下面重新提交
        queue.append(s)

    def record(sid, **kw):
        rec = recs.setdefault(sid, {})
        rec.update({"episode": args.ep, "shot": sid})
        rec.update(kw)
        key = rec.get("task_id") or "failed_%s_%02d" % (args.ep, sid)
        doc["tasks"][key] = {k: v for k, v in rec.items() if k != "task_id"}
        save_tasks(doc)

    inflight = []   # [(shot, task_id, started_at)]
    slots = max(1, args.slots)
    deadline = time.time() + args.timeout
    done = 0
    last_err = ""
    print("待生成 %d 镜（并发槽 %d）" % (len(queue), slots))

    while (queue or inflight) and time.time() < deadline:
        # 1) 补位提交
        while queue and len(inflight) < slots:
            s = queue[0]
            try:
                tid = submit_video(args.ep, s)
                queue.pop(0)
                inflight.append((s, tid, time.time()))
                rec = recs.get(s["id"], {})
                record(s["id"], task_id=tid, status="submitted",
                       submitted_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                       output=os.path.relpath(video_path(args.ep, s["id"]), PROJECT),
                       attempts=int(rec.get("attempts", 0)) + 1,
                       motion=s.get("motion", ""))
                print("  提交 %02d → %s" % (s["id"], tid))
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                last_err = msg[:300]
                if "429" in msg or "limit reached" in msg:
                    # 槽位没空出来：等一轮再试，不消耗队列
                    time.sleep(8)
                    break
                queue.pop(0)
                n = int(recs.get(s["id"], {}).get("attempts", 0))
                record(s["id"], status="failed", error=msg[:400], attempts=n + 1)
                print("  提交 %02d ❌ %s" % (s["id"], msg[:160]))

        if not inflight and not queue:
            break

        # 2) 轮询
        time.sleep(args.poll)
        still = []
        for s, tid, t0 in inflight:
            vp = video_path(args.ep, s["id"])
            if os.path.exists(vp) and os.path.getsize(vp) > 50000:
                done += 1
                continue
            r = mx.call("connector__matrix__query_video_generation",
                        {"task_id": tid, "model": "MiniMax-Hailuo-2.3"})
            st = r.get("status")
            if st == "succeeded" and r.get("video_url"):
                try:
                    mx.download(r["video_url"], vp)
                    record(s["id"], task_id=tid, status="succeeded",
                           bytes=os.path.getsize(vp),
                           downloaded_at=time.strftime("%Y-%m-%d %H:%M:%S"))
                    print("  ✅ %02d %s（剩 %d）" % (s["id"], os.path.basename(vp), len(queue)))
                except Exception as e:  # noqa: BLE001
                    print("  下载 %02d ❌ %s" % (s["id"], e))
                    still.append((s, tid, t0))
            elif st in ("failed", "cancelled"):
                record(s["id"], task_id=tid, status="failed",
                       error=str(r.get("error") or r.get("message", ""))[:400])
                print("  ❌ %02d 任务%s" % (s["id"], st))
            elif time.time() - t0 > 900:
                record(s["id"], task_id=tid, status="timeout")
                print("  ⌛ %02d 超时" % s["id"])
            else:
                record(s["id"], task_id=tid, status=st or "running")
                still.append((s, tid, t0))
        inflight = still
        if inflight:
            print("  在跑 %d，待提交 %d" % (len(inflight), len(queue)))

    done = sum(1 for s in spec["shots"] if os.path.exists(video_path(args.ep, s["id"])))
    print("视频完成 %d/%d%s" % (done, len(spec["shots"]),
                               ("  最后错误：%s" % last_err) if last_err else ""))
    return 0 if done == len(spec["shots"]) else 1


# ---------------------------------------------------------------- ③ 音频

# edge-tts 每句都自带约 0.12s 前导静音 + 0.35~0.45s 尾部静音。
# 全片 36 句白占十几秒，而且尾部静音会把下一句往后推，造成「说完一句空半拍」。
# 这里统一裁掉首尾静音（各留 30~40ms 余量），语速不变，节奏更紧。
TRIM_AF = (
    "silenceremove=start_periods=1:start_duration=0.03:start_threshold=-50dB:start_silence=0.03,"
    "areverse,"
    "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB:start_silence=0.04,"
    "areverse"
)


def trim_silence(path):
    """就地裁掉 TTS 首尾静音。用 .trimmed 标记保证幂等（已裁过的不再动）。"""
    mk = path + ".trimmed"
    if os.path.exists(mk):
        return path
    tmp = path + ".tmp.mp3"
    r = run([ffmpeg(), "-hide_banner", "-y", "-i", path, "-af", TRIM_AF,
             "-c:a", "libmp3lame", "-q:a", "2", tmp])
    if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 500:
        os.replace(tmp, path)
    elif os.path.exists(tmp):
        os.remove(tmp)
    with open(mk, "w") as f:
        f.write("1")
    return path


def tts_line(ep, text, who, emotion, speed):
    """逐句配音：edge-tts（本地免费、音色稳定、支持中文男少年音）。"""
    voice, rate, pitch = VOICES.get(who, VOICES["xiao"])
    mult = float(speed or 1.0)
    base = int(rate.replace("%", "").replace("+", ""))
    # speed 是真实语速倍率：1.0 = 基准，1.4 = 再快 40%
    rate_pct = int(round(base + (mult - 1.0) * 100))
    rate_pct = max(-30, min(90, rate_pct))
    rate_s = "%+d%%" % rate_pct
    key = "%s_%s" % (who, re.sub(r"[^\w\u4e00-\u9fff]", "", text)[:14])
    path = os.path.join(audio_dir(ep), key + ".mp3")
    if not (os.path.exists(path) and os.path.getsize(path) > 1000):
        cmd = [EDGE_TTS, "--voice", voice, "--rate=%s" % rate_s, "--pitch=%s" % pitch,
               "--text", text, "--write-media", path]
        r = run(cmd)
        if r.returncode != 0 or not os.path.exists(path):
            raise RuntimeError("TTS 失败: %s" % (r.stderr[-300:] or r.stdout[-300:]))
    return trim_silence(path)


def amb_file(ep, scene, seed):
    path = os.path.join(audio_dir(ep), "amb_%s_%d.wav" % (scene, seed % 3))
    if not os.path.exists(path):
        A.write_wav(path, A.ambience(scene, 12.0, seed=seed))
    return path


def sfx_file(ep, name, seed):
    path = os.path.join(audio_dir(ep), "sfx_%s_%d.wav" % (name, seed % 3))
    if not os.path.exists(path):
        A.write_wav(path, A.sfx(name, seed=seed))
    return path


def bgm_for(ep, spec):
    """每集一条程序化配乐（无额度依赖）。"""
    path = os.path.join(audio_dir(ep), "bgm.wav")
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    mood = spec.get("bgm_mood", "light")
    A.write_wav(path, A.bgm(24.0, seed=hash(ep) % 1000, mood=mood))
    return path


def cmd_audio(args):
    spec = load_spec(args.ep)
    n_lines = 0
    for s in spec["shots"]:
        for ln in s.get("lines") or []:
            try:
                p = tts_line(args.ep, ln["text"], ln.get("who", "xiao"),
                             ln.get("emotion", "neutral"), ln.get("speed", 1.0))
                n_lines += 1
                print("  TTS %s %.2fs  %s" % (os.path.basename(p), probe_duration(p), ln["text"]))
            except Exception as e:  # noqa: BLE001
                print("  TTS ❌ %s：%s" % (ln["text"], e))
        for name in s.get("sfx") or []:
            if name:
                sfx_file(args.ep, name, s["id"])
        amb_file(args.ep, s.get("amb", "dorm"), s["id"])
    b = bgm_for(args.ep, spec)
    print("音频完成：%d 句台词，BGM=%s" % (n_lines, b))
    return 0


# ---------------------------------------------------------------- ④ 成片

def _zh_count(s):
    """「字数」只算正文（汉字/字母/数字），不算标点和空格。"""
    return len(re.sub(r"[^\w\u4e00-\u9fff]", "", s or ""))


def wrap_cn(text, per_line=13):
    """按每行最多 per_line 个「字」折行。

    先按标点切成语义段，再贪心装箱 —— 避免出现「真实本 / 人」这种把词劈两半的字幕。
    「字」不计标点，所以「那要是有人不会说相声能来吗？」算 13 字，可以整行放下。
    """
    text = (text or "").strip()
    if not text:
        return ""
    if _zh_count(text) <= per_line:
        return text
    segs, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "，。！？、；：，,!?;:—… ":
            segs.append(cur)
            cur = ""
    if cur:
        segs.append(cur)
    lines, line = [], ""
    for seg in segs:
        if not seg.strip():
            continue
        if _zh_count(line) + _zh_count(seg) <= per_line:
            line += seg
        else:
            if line.strip():
                lines.append(line.rstrip())
            if _zh_count(seg) <= per_line:
                line = seg
            else:
                buf = ""
                for ch in seg:
                    buf += ch
                    if _zh_count(buf) >= per_line:
                        lines.append(buf.rstrip())
                        buf = ""
                line = buf
    if line.strip():
        lines.append(line.rstrip())
    return "\n".join(lines)


def esc_path(p):
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def render_shot(ep, shot, bgm, tmpdir):
    sid = shot["id"]
    dur_spec = float(shot.get("dur") or 5.0)
    lines = shot.get("lines") or []
    vpath = video_path(ep, sid)
    fpath = frame_path(ep, sid)
    have_video = os.path.exists(vpath) and os.path.getsize(vpath) > 50000
    if not have_video and not os.path.exists(fpath):
        raise RuntimeError("镜%d 既没有视频也没有首帧" % sid)

    # --- 时长：先量台词
    line_files, line_durs = [], []
    for ln in lines:
        try:
            p = tts_line(ep, ln["text"], ln.get("who", "xiao"),
                         ln.get("emotion", "neutral"), ln.get("speed", 1.0))
        except Exception:
            continue
        line_files.append(p)
        line_durs.append(probe_duration(p))
    gap = float(shot.get("gap", 0.30))      # 句与句的抢白间隔
    pad = float(shot.get("pad", 0.95))      # 台词尾部留白
    lead = float(shot.get("lead", 0.42))    # 第一句入点
    speech = sum(line_durs) + max(0, len(line_durs) - 1) * gap
    # 台词更长时自动延长镜头（静帧可无损延长；有视频时最多拉到素材长度）
    cap = (probe_duration(vpath) if have_video else 9.5)
    dur = max(4.0, min(cap, max(dur_spec, speech + pad)))
    src_dur = probe_duration(vpath) if have_video else 0.0

    # --- 音轨：环境 + 音效 + 台词
    inputs = []
    filters = []
    amix_labels = []
    idx = 1  # 0 号输入永远是画面（视频或首帧静图）

    amb = amb_file(ep, shot.get("amb", "dorm"), sid)
    inputs += ["-stream_loop", "-1", "-i", amb]
    filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=0.9[amb]" % (idx, dur))
    amix_labels.append("[amb]")
    idx += 1

    for k, name in enumerate([x for x in (shot.get("sfx") or []) if x][:3]):
        sp = sfx_file(ep, name, sid + k)
        at = shot.get("sfx_at") or []
        t0 = float(at[k]) if k < len(at) else [0.30, dur * 0.55, dur * 0.80][k]
        inputs += ["-i", sp]
        filters.append("[%d:a]adelay=%d|%d,apad=pad_dur=%.2f,atrim=0:%.3f,volume=0.85[sfx%d]"
                       % (idx, int(t0 * 1000), int(t0 * 1000), dur, dur, k))
        amix_labels.append("[sfx%d]" % k)
        idx += 1

    t_cursor = lead
    for k, (p, d) in enumerate(zip(line_files, line_durs)):
        if t_cursor + d > dur - 0.15:
            d = max(0.4, dur - 0.15 - t_cursor)
        inputs += ["-i", p]
        filters.append("[%d:a]adelay=%d|%d,atrim=0:%.3f,volume=1.0[v%d]"
                       % (idx, int(t_cursor * 1000), int(t_cursor * 1000), d + 0.05, k))
        amix_labels.append("[v%d]" % k)
        t_cursor += d + gap
        idx += 1

    # 「安静两拍」的镜头必须撤掉 BGM（bible/series.md §7.2 第 4 条）
    use_bgm = bgm and shot.get("amb") != "silence"
    if use_bgm:
        # bgm_until：台词说完就撤掉音乐，只留房间底噪 —— 「安静两拍后反转」
        bgm_end = dur
        bu = shot.get("bgm_until")
        if bu is not None:
            bgm_end = max(0.8, min(dur, float(bu)))
        gain = float(shot.get("bgm_gain", 0.16))
        # bgm_gap：把某个时间窗的音乐挖空 —— 「说完留半秒空，只留房间底噪」
        gate = "1"
        bg = shot.get("bgm_gap")
        if bg:
            gate = "if(between(t,%.3f,%.3f),0,1)" % (float(bg[0]), float(bg[1]))
        inputs += ["-stream_loop", "-1", "-i", bgm]
        if bgm_end < dur - 0.05:
            filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f,afade=t=in:st=0:d=0.6,"
                           "afade=t=out:st=%.2f:d=0.35,volume='%s'[bgm]"
                           % (idx, bgm_end, gain, max(0, bgm_end - 0.4), gate))
        else:
            filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f,afade=t=in:st=0:d=0.6,"
                           "afade=t=out:st=%.2f:d=0.6,volume='%s'[bgm]"
                           % (idx, dur, gain, max(0, dur - 0.7), gate))
        amix_labels.append("[bgm]")
        idx += 1

    filters.append("%samix=inputs=%d:duration=first:normalize=0,"
                   "alimiter=limit=0.92,aresample=48000[mix]"
                   % ("".join(amix_labels), len(amix_labels)))

    # --- 画面
    if have_video:
        inputs = ["-t", "%.3f" % min(dur, src_dur), "-i", vpath] + inputs
        filters.insert(0, "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                          "crop=1080:1920,setsar=1,fps=24,"
                          "tpad=stop_mode=clone:stop_duration=2.0,trim=0:%.3f,setpts=PTS-STARTPTS[v]"
                       % dur)
        vin = "0:v"
    else:
        inputs = ["-loop", "1", "-t", "%.3f" % dur, "-i", fpath] + inputs
        # 推拉交替：偶数镜缓推、奇数镜缓拉，避免每镜都同一个方向
        if sid % 2 == 0:
            zexpr = "if(eq(on,0),1.0,min(zoom+0.00055,1.07))"
        else:
            zexpr = "if(eq(on,0),1.07,max(zoom-0.00055,1.0))"
        xe = "iw/2-(iw/zoom/2)%+d" % (int(18 * (1 if sid % 4 < 2 else -1)))
        filters.insert(0, "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                          "crop=1080:1920,setsar=1,fps=24,"
                          "zoompan=z='%s':d=1:x='%s':y='ih/2-(ih/zoom/2)':"
                          "s=1080x1920:fps=24,trim=0:%.3f,setpts=PTS-STARTPTS[v]" % (zexpr, xe, dur))
        vin = "0:v"

    # --- 字幕
    # 多句台词的镜：逐句时间窗字幕（一句一屏），而不是把整镜台词糊在一起
    sub = shot.get("caption")
    if not sub and lines:
        sub = "".join(x["text"] for x in lines)
    text_path = None
    if sub:
        prev = "[v]"
        if not shot.get("caption") and len(lines) > 1:
            for k, ln in enumerate(lines):
                t0 = lead + sum(line_durs[:k]) + k * gap
                t1 = t0 + line_durs[k] + 0.20
                text_path = os.path.join(tmpdir, "sub%02d_%d.txt" % (sid, k))
                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(wrap_cn(ln["text"], 13))
                filters.append("%sdrawtext=fontfile='%s':textfile='%s':fontcolor=white:fontsize=46:"
                               "line_spacing=10:borderw=3:bordercolor=black@0.75:"
                               "x=(w-text_w)/2:y=h-420:enable='between(t,%.3f,%.3f)'[vsub%d]"
                               % (prev, FONT, esc_path(text_path), max(0.0, t0), t1, k))
                prev = "[vsub%d]" % k
        else:
            text_path = os.path.join(tmpdir, "sub%02d.txt" % sid)
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(wrap_cn(sub, 13))
            filters.append("[v]drawtext=fontfile='%s':textfile='%s':fontcolor=white:fontsize=46:"
                           "line_spacing=10:borderw=3:bordercolor=black@0.75:"
                           "x=(w-text_w)/2:y=h-420[vsub]" % (FONT, esc_path(text_path)))
            prev = "[vsub]"
        vout = prev
    else:
        vout = "[v]"

    out = os.path.join(tmpdir, "shot%02d.mp4" % sid)
    cmd = [ffmpeg(), "-y", "-v", "error"] + inputs + [
        "-filter_complex", ";".join(filters),
        "-map", vout, "-map", "[mix]",
        "-t", "%.3f" % dur, "-r", "24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", out,
    ]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("渲染镜%d失败：%s" % (sid, r.stderr[-700:]))
    return out, dur


def make_card(text_lines, dur, out, bgm=None, sub=None, title_size=64):
    """居中排版的多行卡片（片头/片尾）。行距 = title_size + 24，整体垂直居中。"""
    tmpdir = os.path.dirname(out)
    n = len(text_lines)
    gap = title_size + 24
    filters = ["[0:v]scale=1080:1920,format=yuv420p[v]"]
    parts = []
    for i, line in enumerate(text_lines):
        p = os.path.join(tmpdir, "card_%d_%s.txt" % (i, os.path.basename(out)))
        with open(p, "w", encoding="utf-8") as f:
            f.write(line)
        off = int((i - (n - 1) / 2.0) * gap)
        filters.append("[%s]drawtext=fontfile='%s':textfile='%s':fontcolor=white:fontsize=%d:"
                       "x=(w-text_w)/2:y=(h-text_h)/2%+d:borderw=2:bordercolor=black@0.55[%s]"
                       % ("v" if i == 0 else "c%d" % (i - 1), FONT, esc_path(p), title_size,
                          off, "c%d" % i))
        parts.append("c%d" % i)
    vlabel = "[%s]" % parts[-1] if parts else "[v]"
    inputs = ["-f", "lavfi", "-i", "color=c=0x101010:s=1080x1920:r=24:d=%.2f" % dur]
    if bgm:
        inputs += ["-stream_loop", "-1", "-i", bgm]
        filters.append("[1:a]atrim=0:%.2f,volume=0.18,afade=t=in:st=0:d=0.8,"
                       "afade=t=out:st=%.2f:d=0.8[bgm]" % (dur, dur - 0.9))
        alabel = "[bgm]"
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        alabel = "[1:a]"
    cmd = [ffmpeg(), "-y", "-v", "error"] + inputs + [
        "-filter_complex", ";".join(filters),
        "-map", vlabel, "-map", alabel, "-t", "%.2f" % dur, "-r", "24",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", out]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("卡片失败：%s" % r.stderr[-500:])
    return out


def render_egg(ep, egg, tmpdir):
    """彩蛋：真实素材直用。原片没有音轨，就补一层真实房间底噪，避免死寂。"""
    clip = os.path.join(HABITS_DIR, egg["clip"])
    if not os.path.exists(clip):
        return None, 0
    dur = min(8.0, max(4.0, probe_duration(clip)))
    out = os.path.join(tmpdir, "egg.mp4")
    cap = egg.get("caption") or ""
    tf = os.path.join(tmpdir, "egg.txt")
    with open(tf, "w", encoding="utf-8") as f:
        f.write(wrap_cn(cap, 13))
    amb = os.path.join(audio_dir(ep), "amb_egg.wav")
    if not os.path.exists(amb):
        A.write_wav(amb, A.ambience("home", 12.0, seed=7))
    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
          "fps=24,noise=alls=9:allf=t+u,eq=saturation=0.88:contrast=1.03,"
          "drawtext=fontfile='%s':textfile='%s':fontcolor=white:fontsize=40:borderw=3:"
          "bordercolor=black@0.7:x=(w-text_w)/2:y=h-360[v]" % (FONT, esc_path(tf)))
    cmd = [ffmpeg(), "-y", "-v", "error", "-t", "%.2f" % dur, "-i", clip,
           "-stream_loop", "-1", "-i", amb,
           "-filter_complex", vf + ";[1:a]atrim=0:%.2f,volume=0.55,aresample=48000[a]" % dur,
           "-map", "[v]", "-map", "[a]", "-t", "%.2f" % dur,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", out]
    r = run(cmd)
    if not os.path.exists(out):
        print("   彩蛋渲染失败：%s" % r.stderr[-300:])
        return None, 0
    return out, probe_duration(out)


def cmd_build(args):
    spec = load_spec(args.ep)
    ep = args.ep
    tmpdir = os.path.join(OUT_ROOT, ep, "build")
    os.makedirs(tmpdir, exist_ok=True)
    os.makedirs(FINAL_DIR, exist_ok=True)
    bgm = bgm_for(ep, spec)

    parts = []
    ep_no = str(spec.get("ep") or ep.replace("ep", "")).zfill(2)
    title = make_card([spec["title"], "小六二 · 还没出师  EP%s" % ep_no], 3.0,
                      os.path.join(tmpdir, "title.mp4"),
                      bgm=bgm, title_size=76)
    parts.append(title)

    total = 0.0
    for s in spec["shots"]:
        try:
            out, d = render_shot(ep, s, bgm, tmpdir)
            parts.append(out)
            total += d
            print("  镜%02d %.2fs" % (s["id"], d))
        except Exception as e:  # noqa: BLE001
            print("  镜%02d ❌ %s" % (s["id"], e))

    tbc = spec.get("tbc")
    if tbc:
        parts.append(make_card([tbc.get("title", "TO BE CONTINUED"),
                                tbc.get("subtitle", "")],
                               float(tbc.get("seconds", 3.0)),
                               os.path.join(tmpdir, "tbc.mp4"), bgm=bgm, title_size=58))
        print("  TBC 卡")

    egg = spec.get("egg")
    if egg:
        p, d = render_egg(ep, egg, tmpdir)
        if p:
            parts.append(p)
            total += d
            print("  彩蛋 %.2fs" % d)

    if spec.get("end_card", True):
        end = make_card(["本片画面由 AI 生成", "小六二是一只真实存在的萨摩耶", "《还没出师》S1"],
                        4.0, os.path.join(tmpdir, "end.mp4"), bgm=bgm, title_size=52)
        parts.append(end)

    lst = os.path.join(tmpdir, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % p.replace("'", "'\\''"))
    final = os.path.join(FINAL_DIR, "%s_final_9x16.mp4" % ep)
    cmd = [ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
           "-c", "copy", "-movflags", "+faststart", final]
    r = run(cmd)
    if r.returncode != 0:
        # 参数不一致时重编码兜底
        cmd = [ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
               "-movflags", "+faststart", final]
        r = run(cmd)
    if r.returncode != 0:
        raise SystemExit("合成失败：%s" % r.stderr[-800:])
    # 统一响度（短视频平台目标 -16 LUFS / 真峰 ≤ -1.5 dBTP）
    #
    # 为什么必须先压缩：原始混音是「对白脉冲 + 极轻房间底噪」，
    # 测出来 input_i=-25.2 LUFS 而 input_tp=+2.3 dBFS（波峰因数 27dB）。
    # 直接 loudnorm 会把限制器逼到极限，压完峰平均又掉回 -17 LUFS。
    # 加一级 acompressor 把波峰因数压下来，再 loudnorm + alimiter，才能同时达标。
    #   压缩器+单遍loudnorm+限制器 → 实测 -16.1 LUFS / 真峰 -1.9 dBFS
    #   两遍 loudnorm（linear=true）→ -16.1 LUFS 但真峰 -0.0 dBFS（AAC 过冲顶不住），故用单遍
    tmp_out = final.replace(".mp4", ".loud.mp4")
    COMP = "acompressor=threshold=-30dB:ratio=4:attack=3:release=120:makeup=8"
    af = ("%s,loudnorm=I=-16:TP=-1.5:LRA=11,"
          "alimiter=limit=0.749:level=disabled:attack=1:release=50" % COMP)
    r2 = run([ffmpeg(), "-y", "-v", "error", "-i", final, "-c:v", "copy",
              "-af", af, "-c:a", "aac", "-b:a", "192k",
              "-ar", "48000", "-ac", "2", tmp_out])
    if r2.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 100000:
        os.replace(tmp_out, final)
    else:
        print("   ⚠️ 响度归一失败（rc=%s）：%s" % (r2.returncode, (r2.stderr or "")[-300:]))
    # 回读实测响度，确认达标
    chk = run([ffmpeg(), "-hide_banner", "-nostats", "-i", final,
               "-af", "ebur128=peak=true", "-f", "null", "-"])
    mi = re.search(r"^\s*I:\s+(-?[\d.]+) LUFS", chk.stderr or "", re.M)
    mp = re.search(r"True peak:\s*\n\s*Peak:\s+(-?[\d.]+) dBFS", chk.stderr or "")
    print("   实测响度：%s LUFS  真峰 %s dBFS" % (
        mi.group(1) if mi else "?", mp.group(1) if mp else "?"))
    dur = probe_duration(final)
    print("成片 %s  %.1fs  %.1f MB" % (final, dur, os.path.getsize(final) / 1e6))
    return 0


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["frames", "videos", "audio", "build", "all"])
    ap.add_argument("--ep", required=True)
    ap.add_argument("--shots", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--poll", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--resolution", default="768P", choices=["768P", "1080P"])
    ap.add_argument("--skip-videos", action="store_true")
    a = ap.parse_args()

    if a.cmd in ("frames", "all"):
        cmd_frames(a)
    if a.cmd in ("videos", "all") and not a.skip_videos:
        cmd_videos(a)
    if a.cmd in ("audio", "all"):
        cmd_audio(a)
    if a.cmd in ("build", "all"):
        cmd_build(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
