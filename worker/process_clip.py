#!/usr/bin/env python3
"""
GitHub Actions clip worker — automated equivalent of the agent's manual
scripts/process-clips.sh, but processes a single moment per invocation
(triggered by a repository_dispatch webhook from Convex) and reports the
finished MP4 straight to the app's /ingest-clip HTTP endpoint instead of
going through the Convex CLI.

This file lives here in the app's own repo as the source of truth, and gets
copied into the separate mercadomarcelo5559/magoosuna GitHub repo (which
runs it via .github/workflows/process-clip.yml) — it is not executed as
part of this app itself.
"""
import os
import re
import subprocess
import sys
import urllib.request


def env(name, required=True, default=None):
    v = os.environ.get(name, default)
    if required and not v:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return v


VIDEO_URL = env("VIDEO_URL")
START = float(env("START_SECONDS"))
END = float(env("END_SECONDS"))
TITLE = env("MOMENT_TITLE")
ANALYSIS_ID = env("ANALYSIS_ID")
MOMENT_INDEX = env("MOMENT_INDEX")
INGEST_URL = env("CONVEX_INGEST_URL")
INGEST_SECRET = env("INGEST_SECRET")
WATERMARK_TEXT = env("WATERMARK_TEXT", required=False, default="@tu_canal")

WORKDIR = "/tmp/clip-work"
os.makedirs(WORKDIR, exist_ok=True)
os.chdir(WORKDIR)


def run(cmd, **kwargs):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kwargs)


def extract_video_id(url):
    for p in [r"watch\?v=([\w-]{11})", r"youtu\.be/([\w-]{11})",
              r"shorts/([\w-]{11})", r"live/([\w-]{11})"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError("Could not extract video ID from " + url)


video_id = extract_video_id(VIDEO_URL)
source_file = f"source_{video_id}.mp4"

if not os.path.exists(source_file):
    print("== Downloading source video ==")
    run([
        "yt-dlp", "--cookies", "/tmp/youtube_cookies.txt",
        "--js-runtimes", "node", "--remote-components", "ejs:github",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", source_file,
        f"https://www.youtube.com/watch?v={video_id}",
    ])
else:
    print("== Source already cached ==")

name = f"clip_{MOMENT_INDEX}"

print(f"== Cutting {START}-{END}s ==")
run(["ffmpeg", "-y", "-ss", str(START), "-to", str(END), "-i", source_file,
     "-c", "copy", f"{name}_cut.mp4", "-loglevel", "error"])

print("== Converting to 9:16 vertical ==")
run([
    "ffmpeg", "-y", "-i", f"{name}_cut.mp4", "-filter_complex",
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
    "gblur=sigma=25[bg];[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]",
    "-map", "[outv]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast",
    "-crf", "20", "-c:a", "aac", "-b:a", "192k", f"{name}.mp4", "-loglevel", "error",
])
os.remove(f"{name}_cut.mp4")

print("== Removing dead air (silence-based jump cuts) ==")
NOISE_DB, MIN_DUR, PAD = -30, 0.5, 0.08


def get_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def detect_silences(path):
    cmd = ["ffmpeg", "-i", path, "-af", f"silencedetect=noise={NOISE_DB}dB:d={MIN_DUR}", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", r.stderr)]
    n = min(len(starts), len(ends))
    return list(zip(starts[:n], ends[:n]))


duration = get_duration(f"{name}.mp4")
silences = detect_silences(f"{name}.mp4")
cut_ranges = [(s + PAD, e - PAD) for s, e in silences if (e - PAD) - (s + PAD) > 0.05]

if cut_ranges:
    keep = []
    prev = 0.0
    for cs, ce in cut_ranges:
        if cs > prev:
            keep.append((prev, cs))
        prev = ce
    if prev < duration:
        keep.append((prev, duration))
    keep = keep[:30]

    parts, concat_in = [], []
    for idx, (s, e) in enumerate(keep):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{idx}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{idx}]")
        concat_in.append(f"[v{idx}][a{idx}]")
    filter_complex = ";".join(parts) + ";" + "".join(concat_in) + f"concat=n={len(keep)}:v=1:a=1[outv][outa]"
    tight = f"{name}_tight.mp4"
    run(["ffmpeg", "-y", "-i", f"{name}.mp4", "-filter_complex", filter_complex,
         "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-c:a", "aac", tight, "-loglevel", "error"])
    os.replace(tight, f"{name}.mp4")
    print(f"removed {sum(e - s for s, e in cut_ranges):.2f}s of dead air across {len(cut_ranges)} cuts")
else:
    print("no dead air found, keeping clip as-is")

duration = get_duration(f"{name}.mp4")

print("== Transcribing + building captions ==")
from faster_whisper import WhisperModel


def ass_time(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02}:{s:05.2f}"


model = WhisperModel("small", device="cpu", compute_type="int8")
segments, info = model.transcribe(f"{name}.mp4", word_timestamps=True)
segments = list(segments)

avg_no_speech = sum(s.no_speech_prob for s in segments) / len(segments) if segments else 1.0
audio_warning = avg_no_speech > 0.4

words = []
for seg in segments:
    for w in seg.words:
        wd = w.word.strip()
        if wd:
            words.append((w.start, w.end, wd))

ACCENTS = ["&H0000FFFF&", "&H0014C8FC&", "&H00FF6EC7&", "&H0000FF66&"]
CHUNK = 3
res_w, res_h = 1080, 1920
fontsize = max(18, round(res_h * 0.075))

lines = []
for i in range(0, len(words), CHUNK):
    chunk = words[i:i + CHUNK]
    if not chunk:
        continue
    start, end = chunk[0][0], chunk[-1][1]
    idx_emph = max(range(len(chunk)), key=lambda k: len(chunk[k][2]))
    accent = ACCENTS[(i // CHUNK) % len(ACCENTS)]
    parts = []
    for j, (ws, we, wd) in enumerate(chunk):
        word = wd.upper()
        if j == idx_emph:
            parts.append("{\\c%s\\fscx130\\fscy130}%s{\\r}" % (accent, word))
        else:
            parts.append(word)
    text = " ".join(parts)
    lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")

watermark_fontsize = max(14, round(res_h * 0.022))
lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(duration)},Watermark,,0,0,0,,{WATERMARK_TEXT}")

headline = TITLE.replace("{", "").replace("}", "").replace("\n", " ")
hl_words = headline.split()
if len(hl_words) > 4:
    headline = " ".join(hl_words[:4]) + "\\N" + " ".join(hl_words[4:])
headline_end = min(1.8, duration)
if headline:
    lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(headline_end)},Headline,,0,0,0,,{headline}")

header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_w}
PlayResY: {res_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Poppins ExtraBold,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{max(2, round(fontsize * 0.11))},0,2,10,10,{round(res_h * 0.16)},1
Style: Watermark,Poppins ExtraBold,{watermark_fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,1,0,9,20,40,50,1
Style: Headline,Poppins ExtraBold,{round(res_h * 0.085)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{round(res_h * 0.011)},0,8,60,60,{round(res_h * 0.09)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

with open(f"{name}.ass", "w") as f:
    f.write(header)
    f.write("\n".join(lines))

print(f"language: {info.language} | lines: {len(lines) - 2} | audio_warning: {audio_warning}")

print("== Burning captions + normalizing loudness + encoding at CRF18 ==")
run([
    "ffmpeg", "-y", "-i", f"{name}.mp4", "-vf", f"ass={name}.ass",
    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", "192k", f"{name}_final.mp4", "-loglevel", "error",
])

print("== Uploading to app ==")
with open(f"{name}_final.mp4", "rb") as f:
    data = f.read()

req = urllib.request.Request(
    f"{INGEST_URL}?analysisId={ANALYSIS_ID}&momentIndex={MOMENT_INDEX}"
    f"&audioWarning={'true' if audio_warning else 'false'}",
    data=data,
    method="POST",
    headers={
        "Authorization": f"Bearer {INGEST_SECRET}",
        "Content-Type": "video/mp4",
    },
)
with urllib.request.urlopen(req, timeout=300) as resp:
    print(resp.status, resp.read().decode())

print("== Done ==")
