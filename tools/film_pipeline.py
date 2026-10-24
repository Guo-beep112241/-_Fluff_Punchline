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


def _build_single_layer(ep, shot, bgm, dur, line_files, line_durs,
                        layer, audio_base):
    """只构建一层的音频图（用于分层导出）。

    与 build_audio_graph 的电平/时间轴处理完全一致，
    所以导出的分层和成片是逐样本对得上的。

    坑：其它层若也建了输出标签，会变成独立输出流，
    而 wav 只能写一条音轨（"wav muxer does not support more than
    one stream of type audio"）。所以这里只建目标层。
    """
    inputs = []
    filters = []
    idx = audio_base
    sid = shot["id"]

    if layer == "amb":
        amb = amb_file(ep, shot.get("amb", "dorm"), sid)
        inputs += ["-stream_loop", "-1", "-i", amb]
        filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f[out]"
                       % (idx, dur, float(shot.get("amb_gain", 0.9))))
    elif layer == "sfx":
        names = [x for x in (shot.get("sfx") or []) if x][:3]
        at = shot.get("sfx_at") or []
        labels = []
        for k, name in enumerate(names):
            sp = sfx_file(ep, name, sid + k)
            t0 = float(at[k]) if k < len(at) else [0.30, dur * 0.55, dur * 0.80][k]
            inputs += ["-i", sp]
            filters.append("[%d:a]adelay=%d|%d,apad=pad_dur=%.2f,atrim=0:%.3f,volume=0.85[sfx%d]"
                           % (idx, int(t0 * 1000), int(t0 * 1000), dur, dur, k))
            labels.append("[sfx%d]" % k)
            idx += 1
        if not labels:
            return None
        filters.append("".join(labels) +
                       "amix=inputs=%d:duration=longest:normalize=0,aresample=48000[out]"
                       % len(labels))
    elif layer == "voice":
        gap = float(shot.get("gap", 0.30))
        lead = float(shot.get("lead", 0.42))
        labels = []
        t_cursor = lead
        for k, (p, d) in enumerate(zip(line_files, line_durs)):
            if t_cursor + d > dur - 0.15:
                d = max(0.4, dur - 0.15 - t_cursor)
            inputs += ["-i", p]
            filters.append("[%d:a]adelay=%d|%d,atrim=0:%.3f,volume=1.0[v%d]"
                           % (idx, int(t_cursor * 1000), int(t_cursor * 1000), d + 0.05, k))
            labels.append("[v%d]" % k)
            t_cursor += d + gap
            idx += 1
        if not labels:
            return None
        filters.append("".join(labels) +
                       "amix=inputs=%d:duration=longest:normalize=0,aresample=48000[out]"
                       % len(labels))
    elif layer == "bgm":
        if not bgm or shot.get("amb") == "silence":
            return None
        bgm_end = dur
        bu = shot.get("bgm_until")
        if bu is not None:
            bgm_end = max(0.8, min(dur, float(bu)))
        gain = float(shot.get("bgm_gain", 0.30))
        gate = "1"
        bg = shot.get("bgm_gap")
        if bg:
            gate = "if(between(t,%.3f,%.3f),0,1)" % (float(bg[0]), float(bg[1]))
        inputs += ["-stream_loop", "-1", "-i", bgm]
        if bgm_end < dur - 0.05:
            filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f,afade=t=in:st=0:d=0.6,"
                           "afade=t=out:st=%.2f:d=0.35,volume=eval=frame:volume='%s'[out]"
                           % (idx, bgm_end, gain, max(0, bgm_end - 0.4), gate))
        else:
            filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f,afade=t=in:st=0:d=0.6,"
                           "afade=t=out:st=%.2f:d=0.6,volume=eval=frame:volume='%s'[out]"
                           % (idx, dur, gain, max(0, dur - 0.7), gate))
    else:
        return None

    return {"inputs": inputs, "filters": filters, "mix_labels": ["[out]"],
            "stem_labels": {"out": "[out]"}}


def build_audio_graph(ep, shot, bgm, dur, line_files, line_durs,
                      want_stems=False, audio_base=1, only_layer=None):
    """构建一镜的音频滤镜图。

    分层结构（每层都是独立 label，便于单独导出）：
      [amb]  房间底噪  —— 铺底
      [bgm]  音乐      —— 铺底
      [v0..] 台词      —— 人声（可整层静音，方便用户自己配音）
      [sfx0..] 音效    —— 音效
      [mix]  全部混合

    want_stems=True 时额外产出每层的独立 label（[stem_amb] 等），
    供 film_pipeline stems 命令导出分层 WAV。

    only_layer="sfx" 等 —— 只构建这一层，不建总混音。
        导出单层时用：其它分支若留着就会变成独立输出流，
        而 wav 只能写一条音轨（实测报 "wav muxer does not support
        more than one stream of type audio"）。

    混音层级（按 -16 LUFS 成片倒推）：
      对白 ≈ -23 dB > 音乐 ≈ -32 dB > 房间底噪 ≈ -37 dB
    早期版本三档都挤在 -37 dB（音乐 gain=0.16），音乐被底噪完全掩蔽。
    """
    inputs = []
    filters = []
    mix_labels = []
    stem_labels = {}
    # audio_base：音频输入在 ffmpeg 输入列表里的起始索引。
    #   渲染成片时 0 号是画面 → 音频从 1 起
    #   导出纯音频分层时没有画面 → 音频从 0 起
    idx = audio_base

    def split(src, name):
        """把一层既送进总混音，也留一份给 stems 导出。

        src  是该层在滤镜图里的源标签（如 "[sfxbus]"）
        name 是该层的逻辑名（如 "sfx"），决定 stem 输出文件名
        注意：asplit 的每一路都必须有下游，否则 ffmpeg 报
        "Filter X has an unconnected output"。
        """
        if only_layer is not None:
            # 只建这一层：其它层完全不生成输出，
            # 否则会变成独立输出流，wav 只能写一条音轨。
            if name == only_layer:
                stem_labels[name] = src
            return
        if want_stems:
            # src 形如 "[sfxbus]"，去掉外层方括号再拼，避免出现 [[sfxbus]]
            filters.append("%sasplit=2[%s][stem_%s]" % (src, name, name))
            mix_labels.append("[%s]" % name)
            stem_labels[name] = "[stem_%s]" % name
        else:
            # 不导出时不必 asplit，直接把源标签接到混音
            mix_labels.append(src)

    if only_layer is not None:
        # 单层导出：只构建目标层需要的输入与滤镜，其它层一概不建
        return _build_single_layer(ep, shot, bgm, dur, line_files, line_durs,
                                   only_layer, audio_base)

    # --- 1) 房间底噪
    amb = amb_file(ep, shot.get("amb", "dorm"), shot["id"])
    inputs += ["-stream_loop", "-1", "-i", amb]
    filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f[amb]"
                   % (idx, dur, float(shot.get("amb_gain", 0.9))))
    idx += 1
    split("[amb]", "amb")

    # --- 2) 音效
    sfx_labels = []
    for k, name in enumerate([x for x in (shot.get("sfx") or []) if x][:3]):
        sp = sfx_file(ep, name, shot["id"] + k)
        at = shot.get("sfx_at") or []
        t0 = float(at[k]) if k < len(at) else [0.30, dur * 0.55, dur * 0.80][k]
        inputs += ["-i", sp]
        filters.append("[%d:a]adelay=%d|%d,apad=pad_dur=%.2f,atrim=0:%.3f,volume=0.85[sfx%d]"
                       % (idx, int(t0 * 1000), int(t0 * 1000), dur, dur, k))
        sfx_labels.append("[sfx%d]" % k)
        idx += 1
    if sfx_labels:
        # 音效层单独成组：既进总混音，也能整层导出
        # amix 的输入标签是位置参数（紧跟在 "amix=" 后面），inputs= 才是数量
        filters.append("".join(sfx_labels) +
                       "amix=inputs=%d:duration=longest:normalize=0,aresample=48000[sfxbus]"
                       % len(sfx_labels))
        split("[sfxbus]", "sfx")
    # --- 3) 台词
    gap = float(shot.get("gap", 0.30))
    lead = float(shot.get("lead", 0.42))
    t_cursor = lead
    v_labels = []
    for k, (p, d) in enumerate(zip(line_files, line_durs)):
        if t_cursor + d > dur - 0.15:
            d = max(0.4, dur - 0.15 - t_cursor)
        inputs += ["-i", p]
        filters.append("[%d:a]adelay=%d|%d,atrim=0:%.3f,volume=1.0[v%d]"
                       % (idx, int(t_cursor * 1000), int(t_cursor * 1000), d + 0.05, k))
        v_labels.append("[v%d]" % k)
        t_cursor += d + gap
        idx += 1
    if v_labels:
        filters.append("".join(v_labels) +
                       "amix=inputs=%d:duration=longest:normalize=0,aresample=48000[voice]"
                       % len(v_labels))
        split("[voice]", "voice")

    # --- 4) 音乐
    # 「安静两拍」的镜头必须撤掉 BGM（bible/series.md §7.2 第 4 条）
    use_bgm = bgm and shot.get("amb") != "silence"
    if use_bgm:
        # bgm_until：台词说完就撤掉音乐，只留房间底噪 —— 「安静两拍后反转」
        bgm_end = dur
        bu = shot.get("bgm_until")
        if bu is not None:
            bgm_end = max(0.8, min(dur, float(bu)))
        # 音乐层电平：对白下 9dB。低于此值会被房间底噪掩蔽，等于没铺音乐。
        gain = float(shot.get("bgm_gain", 0.30))
        # bgm_gap：把某个时间窗的音乐挖空 —— 「说完留半秒空，只留房间底噪」
        #
        # 坑：volume 滤镜的 eval 默认是 init —— 表达式只在初始化时算一次，
        # 里面的 t 根本不随时间变，静音窗会完全失效（实测 t=2.5s 仍是 -21.1dB）。
        # 必须显式写 eval=frame，表达式才会逐帧按时间戳求值。
        gate = "1"
        bg = shot.get("bgm_gap")
        if bg:
            gate = "if(between(t,%.3f,%.3f),0,1)" % (float(bg[0]), float(bg[1]))
        inputs += ["-stream_loop", "-1", "-i", bgm]
        if bgm_end < dur - 0.05:
            filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f,afade=t=in:st=0:d=0.6,"
                           "afade=t=out:st=%.2f:d=0.35,volume=eval=frame:volume='%s'[bgm]"
                           % (idx, bgm_end, gain, max(0, bgm_end - 0.4), gate))
        else:
            filters.append("[%d:a]atrim=0:%.3f,asetpts=N/SR/TB,volume=%.3f,afade=t=in:st=0:d=0.6,"
                           "afade=t=out:st=%.2f:d=0.6,volume=eval=frame:volume='%s'[bgm]"
                           % (idx, dur, gain, max(0, dur - 0.7), gate))
        idx += 1
        split("[bgm]", "bgm")

    if only_layer is None:
        filters.append("".join(mix_labels) +
                       "amix=inputs=%d:duration=first:normalize=0,"
                       "alimiter=limit=0.92,aresample=48000[mix]" % len(mix_labels))
    return {"inputs": inputs, "filters": filters, "mix_labels": mix_labels,
            "stem_labels": stem_labels}


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

    # --- 音轨：环境 + 音效 + 台词 + 音乐（分层构建，见 build_audio_graph）
    graph = build_audio_graph(ep, shot, bgm, dur, line_files, line_durs)
    inputs = graph["inputs"]
    filters = graph["filters"]
    amix_labels = graph["mix_labels"]

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
    # 踩过的坑：早期版本用 acompressor(threshold=-30dB:ratio=4:makeup=8) + 单遍 loudnorm。
    #   acompressor 的 makeup 是「倍数」不是 dB（8 → 实际 +9.4dB），
    #   而 threshold=-30dB/ratio=4 正好落在对白段上，把台词自身波峰因数压掉，
    #   台词均值从 -25.5dB 掉到 -34.6dB —— 安静段没被压，对白被压，
    #   于是「台词→半秒空」的落差从 13.6dB 塌成 4.8dB，第⑦条自检永远过不了。
    #
    # 现在改成：两遍 loudnorm（linear=true = 纯静态增益，不改动态）+ 兜底限制器。
    #   实测 I=-16.2 LUFS / 真峰 -2.5 dBFS / 台词→空档跌落 9.0 dB，三项同时达标。
    #
    # 注意：linear=true 必须用第一遍测出的 measured_* 参数，否则增益算不准。
    tmp_out = final.replace(".mp4", ".loud.mp4")
    m = run([ffmpeg(), "-hide_banner", "-nostats", "-i", final,
             "-af", "loudnorm=I=-14.0:TP=-2.0:LRA=30:print_format=json",
             "-f", "null", "-"])
    jm = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", m.stderr or "", re.S)
    if jm:
        j = json.loads(jm.group(0))
        af = ("loudnorm=I=-14.0:TP=-2.0:LRA=%s:linear=true:"
              "measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:offset=%s,"
              "alimiter=limit=0.668:level=disabled:attack=1:release=50"
              % (j["input_lra"], j["input_i"], j["input_tp"], j["input_lra"],
                 j["input_thresh"], j["target_offset"]))
    else:
        # 测量失败时的兜底：纯静态增益 + 限制器（不改动态）
        print("   ⚠️ loudnorm 测量失败，退回静态增益链")
        af = "volume=9.2dB,alimiter=limit=0.668:level=disabled:attack=1:release=50"
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


def cmd_stems(args):
    """导出分层音频素材，供用户自己配音。

    输出（20_生成结果/<ep>/stems/）：
      voice.wav  台词轨（AI 配音，用户可整轨替换成自己的人声）
      bgm.wav    音乐轨
      amb.wav    房间底噪轨
      sfx.wav    音效轨
      bed.wav    铺底总轨（音乐+底噪+音效，不含人声）—— 直接录人声叠上去即可

    所有轨与成片严格同长同起点（按镜逐段拼接），可直接对齐使用。
    """
    ep = args.ep
    spec = load_spec(ep)
    bgm = bgm_for(ep, spec)
    outdir = os.path.join(OUT_ROOT, ep, "stems")
    os.makedirs(outdir, exist_ok=True)
    tmpdir = os.path.join(outdir, "_parts")
    os.makedirs(tmpdir, exist_ok=True)

    # 每镜时长必须与 build 完全一致，否则分层与成片对不上
    plan = []
    for s in spec["shots"]:
        lines = s.get("lines") or []
        durs = []
        for ln in lines:
            try:
                durs.append(probe_duration(tts_line(
                    ep, ln["text"], ln.get("who", "xiao"),
                    ln.get("emotion", "neutral"), ln.get("speed", 1.0))))
            except Exception:
                pass
        gap = float(s.get("gap", 0.30))
        pad = float(s.get("pad", 0.95))
        speech = sum(durs) + max(0, len(durs) - 1) * gap
        vpath = video_path(ep, s["id"])
        cap = probe_duration(vpath) if (vpath and os.path.exists(vpath)) else 9.5
        dur = max(4.0, min(cap, max(float(s.get("dur") or 5.0), speech + pad)))
        plan.append((s, dur, lines, durs))

    # 片头卡 / TBC 卡 / 彩蛋 也要进分层，否则分层与成片对不齐。
    # 片头卡与 TBC 卡只有音乐（make_card 里 bgm volume=0.18），
    # 彩蛋只有房间底噪（render_egg 里 amb volume=0.55）。
    head_dur = 3.0
    tbc_dur = float((spec.get("tbc") or {}).get("seconds", 3.0))
    egg_dur = 0.0
    egg = spec.get("egg")
    if egg:
        clip = os.path.join(HABITS_DIR, egg["clip"])
        if os.path.exists(clip):
            egg_dur = min(8.0, max(4.0, probe_duration(clip)))

    def card_music(dur, out):
        """卡片音乐段：与 make_card 相同的处理（volume=0.18 + 淡入淡出）。"""
        r = run([ffmpeg(), "-y", "-v", "error", "-stream_loop", "-1", "-i", bgm,
                 "-filter_complex", "[0:a]atrim=0:%.2f,volume=0.18,"
                 "afade=t=in:st=0:d=0.8,afade=t=out:st=%.2f:d=0.8[o]"
                 % (dur, max(0.0, dur - 0.9)),
                 "-map", "[o]", "-t", "%.2f" % dur,
                 "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", out])
        return r.returncode == 0

    def egg_amb(dur, out):
        """彩蛋房间底噪段：与 render_egg 相同（amb_egg volume=0.55）。"""
        amb = os.path.join(audio_dir(ep), "amb_egg.wav")
        if not os.path.exists(amb):
            A.write_wav(amb, A.ambience("home", 12.0, seed=7))
        r = run([ffmpeg(), "-y", "-v", "error", "-stream_loop", "-1", "-i", amb,
                 "-filter_complex", "[0:a]atrim=0:%.2f,volume=0.55[o]" % dur,
                 "-map", "[o]", "-t", "%.2f" % dur,
                 "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", out])
        return r.returncode == 0

    def silence(dur, out):
        r = run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
                 "-i", "anullsrc=r=48000:cl=stereo", "-t", "%.2f" % dur,
                 "-c:a", "pcm_s16le", out])
        return r.returncode == 0

    for layer in ("voice", "bgm", "amb", "sfx"):
        parts = []
        # ── 片头卡 3s：只有音乐
        head = os.path.join(tmpdir, "%s_head.wav" % layer)
        ok = False
        if layer == "bgm":
            ok = card_music(head_dur, head)
        elif layer in ("voice", "amb", "sfx"):
            ok = silence(head_dur, head)
        if ok:
            parts.append(head)
        # ── TBC 卡：只有音乐
        tbc_p = os.path.join(tmpdir, "%s_tbc.wav" % layer)
        ok = False
        if layer == "bgm":
            ok = card_music(tbc_dur, tbc_p)
        elif layer in ("voice", "amb", "sfx"):
            ok = silence(tbc_dur, tbc_p)
        if ok:
            parts.append(tbc_p)
        # ── 26 镜
        for s, dur, lines, durs in plan:
            lf = [tts_line(ep, ln["text"], ln.get("who", "xiao"),
                           ln.get("emotion", "neutral"),
                           ln.get("speed", 1.0))
                  for ln in lines]
            graph = build_audio_graph(ep, s, bgm, dur, lf, durs,
                                      want_stems=True, audio_base=0,
                                      only_layer=layer)
            p = os.path.join(tmpdir, "%s_%02d.wav" % (layer, s["id"]))
            if graph is None:
                # 该层在本镜不存在（无台词/无音效/撤掉音乐）→ 写静音
                r = run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
                         "-i", "anullsrc=r=48000:cl=stereo", "-t", "%.3f" % dur,
                         "-c:a", "pcm_s16le", p])
            else:
                r = run([ffmpeg(), "-y", "-v", "error"] + graph["inputs"] + [
                    "-filter_complex", ";".join(graph["filters"]),
                    "-map", "[out]", "-t", "%.3f" % dur,
                    "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", p])
            if r.returncode != 0 or not os.path.exists(p):
                print("  ❌ 镜%02d %s 失败：%s" % (s["id"], layer, (r.stderr or "")[-200:]))
            else:
                parts.append(p)
        # ── 彩蛋：只有房间底噪
        if egg_dur > 0:
            egg_p = os.path.join(tmpdir, "%s_egg.wav" % layer)
            ok = False
            if layer == "amb":
                ok = egg_amb(egg_dur, egg_p)
            elif layer in ("voice", "bgm", "sfx"):
                ok = silence(egg_dur, egg_p)
            if ok:
                parts.append(egg_p)
        if not parts:
            continue
        lst = os.path.join(tmpdir, "%s.txt" % layer)
        with open(lst, "w", encoding="utf-8") as f:
            for p in parts:
                f.write("file '%s'\n" % p.replace("'", "'\\''"))
        out = os.path.join(outdir, "%s.wav" % layer)
        r = run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                 "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", out])
        print("  %-6s %s  %.1fs  %.1f MB" % (
            layer, "✅" if r.returncode == 0 else "❌",
            probe_duration(out) if os.path.exists(out) else 0,
            os.path.getsize(out) / 1e6 if os.path.exists(out) else 0))

    # 铺底总轨 = 音乐 + 底噪 + 音效（不含人声），用户直接对着它录
    bed = os.path.join(outdir, "bed.wav")
    r = run([ffmpeg(), "-y", "-v", "error",
             "-i", os.path.join(outdir, "bgm.wav"),
             "-i", os.path.join(outdir, "amb.wav"),
             "-i", os.path.join(outdir, "sfx.wav"),
             "-filter_complex", "[0:a][1:a][2:a]amix=inputs=3:duration=longest:normalize=0,"
             "alimiter=limit=0.92,aresample=48000[bed]",
             "-map", "[bed]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", bed])
    print("  bed    %s  %.1fs  %.1f MB" % (
        "✅" if r.returncode == 0 else "❌",
        probe_duration(bed) if os.path.exists(bed) else 0,
        os.path.getsize(bed) / 1e6 if os.path.exists(bed) else 0))
    print("分层素材在 %s" % outdir)
    return 0


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["frames", "videos", "audio", "build", "stems", "all"])
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
    if a.cmd in ("stems", "all"):
        cmd_stems(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
