#!/usr/bin/env python3
"""
GitHub Actions clip worker — automated equivalent of the agent's manual
scripts/process-clips.sh, but processes a single moment per invocation
(triggered by a repository_dispatch webhook from Convex) and reports the
finished MP4 straight to the app's HTTP endpoints instead of going through
the Convex CLI.

This file lives here in the app's own repo as the source of truth, and gets
copied into the separate mercadomarcelo5559/magoosuna GitHub repo (which
runs it via .github/workflows/process-clip.yml) — it is not executed as
part of this app itself.
"""
import json
import os
import re
import subprocess
import sys
import time
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
CONVEX_SITE_URL = env("CONVEX_INGEST_URL").rstrip("/")
INGEST_SECRET = env("INGEST_SECRET")
WATERMARK_TEXT = env("WATERMARK_TEXT", required=False, default="@tu_canal")
FONT_FAMILY = env("FONT_FAMILY", required=False, default="Poppins ExtraBold")

WORKDIR = "/tmp/clip-work"
os.makedirs(WORKDIR, exist_ok=True)
os.chdir(WORKDIR)

FORMAT_SELECTOR = "bv*[height<=1080]+ba/b[height<=1080]"


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
    strategies = [
        ["--js-runtimes", "node", "--remote-components", "ejs:github"],
        ["--extractor-args", "youtube:player_client=tv,web_safari"],
        ["--extractor-args", "youtube:player_client=web_safari"],
    ]
    last_err = None
    for attempt, extra_args in enumerate(strategies, start=1):
        try:
            print(f"-- download attempt {attempt}: {' '.join(extra_args)} --")
            run([
                "yt-dlp", "--cookies", "/tmp/youtube_cookies.txt",
                *extra_args,
                "-f", FORMAT_SELECTOR,
                "--merge-output-format", "mp4",
                "-o", source_file,
                f"https://www.youtube.com/watch?v={video_id}",
            ])
            last_err = None
            break
        except subprocess.CalledProcessError as e:
            last_err = e
            if os.path.exists(source_file):
                os.remove(source_file)
            print(f"attempt {attempt} failed, retrying in 8s...")
            time.sleep(8)
    if last_err:
        raise last_err
else:
    print("== Source already cached ==")

name = f"clip_{MOMENT_INDEX}"

print(f"== Cutting {START}-{END}s ==")
run([
    "ffmpeg", "-y", "-ss", str(START), "-to", str(END), "-i", source_file,
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
    "-c:a", "aac", "-b:a", "192k",
    f"{name}_cut.mp4", "-loglevel", "error",
])

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

print("== Preparing caption font ==")
FONT_DOWNLOAD_URLS = {
    "Anton": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "Bebas Neue": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    "Archivo Black": "https://raw.githubusercontent.com/google/fonts/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
}
FONTS_DIR = os.path.join(WORKDIR, "fonts")
os.makedirs(FONTS_DIR, exist_ok=True)
if FONT_FAMILY != "Poppins ExtraBold":
    if FONT_FAMILY in FONT_DOWNLOAD_URLS:
        font_path = os.path.join(FONTS_DIR, FONT_FAMILY.replace(" ", "") + ".ttf")
        if not os.path.exists(font_path):
            print(f"downloading font: {FONT_FAMILY}")
            urllib.request.urlretrieve(FONT_DOWNLOAD_URLS[FONT_FAMILY], font_path)
    else:
        print(f"unknown font {FONT_FAMILY!r}, falling back to Poppins ExtraBold")
        FONT_FAMILY = "Poppins ExtraBold"

print("== Transcribing + building captions ==")
from faster_whisper import WhisperModel


def ass_time(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02}:{s:05.2f}"


# "large-v3" instead of "medium" -- a real accuracy step up, and
# affordable here since this only ever transcribes one already-cut clip
# (15-90s of audio), never the full source video, so the extra CPU time
# stays well inside the job's timeout even on GitHub's free runners.
#
# language="es" removes Whisper's own language auto-detection entirely --
# on a short clip (often with music, slang, or a noisy intro) guessing the
# wrong language was a real source of garbled transcripts; every clip
# here is Spanish, so there is nothing to detect.
#
# initial_prompt primes the decoder with the clip's own AI-written title
# as a light content/vocabulary hint (names, topic words it might
# otherwise mishear), plus a note that this is informal spoken Mexican
# Spanish -- Whisper's baseline otherwise tends to "clean up" slang and
# filler words into more formal, unrelated text.
model = WhisperModel("large-v3", device="cpu", compute_type="int8")
segments, info = model.transcribe(
    f"{name}.mp4",
    word_timestamps=True,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=300),
    beam_size=5,
    language="es",
    initial_prompt=(
        f"Transcripcion en espanol informal hablado de Mexico, con muletillas, "
        f"jerga y groserias tal como se dicen. Tema del clip: {TITLE}."
    ),
    condition_on_previous_text=False,
)
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
CONTEXT_BEFORE, CONTEXT_AFTER = 1, 1
MAX_GAP_BRIDGE = 0.15
res_w, res_h = 1080, 1920
fontsize = max(18, round(res_h * 0.075))

lines = []
for i, (ws, we, wd) in enumerate(words):
    start_idx = max(0, i - CONTEXT_BEFORE)
    end_idx = min(len(words), i + CONTEXT_AFTER + 1)
    window = words[start_idx:end_idx]
    accent = ACCENTS[i % len(ACCENTS)]
    parts = []
    for j, (jw_s, jw_e, jw_t) in enumerate(window):
        word = jw_t.upper()
        if start_idx + j == i:
            parts.append("{\\c%s\\fscx128\\fscy128}%s{\\r}" % (accent, word))
        else:
            parts.append(word)
    text = " ".join(parts)
    display_end = we
    if i + 1 < len(words):
        gap = words[i + 1][0] - we
        if gap > 0:
            display_end = we + min(gap, MAX_GAP_BRIDGE)
    lines.append(f"Dialogue: 0,{ass_time(ws)},{ass_time(display_end)},Default,,0,0,0,,{text}")

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
Style: Default,{FONT_FAMILY},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{max(2, round(fontsize * 0.11))},0,2,10,10,{round(res_h * 0.16)},1
Style: Watermark,Poppins ExtraBold,{watermark_fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,1,0,9,20,40,50,1
Style: Headline,{FONT_FAMILY},{round(res_h * 0.085)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{round(res_h * 0.011)},0,8,60,60,{round(res_h * 0.09)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

with open(f"{name}.ass", "w") as f:
    f.write(header)
    f.write("\n".join(lines))

print(f"language: {info.language} | lines: {len(lines) - 2} | audio_warning: {audio_warning} | font: {FONT_FAMILY}")

print("== Burning captions + normalizing loudness + encoding at CRF18 ==")
run([
    "ffmpeg", "-y", "-i", f"{name}.mp4", "-vf", f"ass={name}.ass:fontsdir={FONTS_DIR}",
    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac", "-b:a", "192k", f"{name}_final.mp4", "-loglevel", "error",
])

print("== Uploading to app ==")
final_path = f"{name}_final.mp4"
file_size = os.path.getsize(final_path)

get_url_req = urllib.request.Request(
    f"{CONVEX_SITE_URL}/get-upload-url?analysisId={ANALYSIS_ID}&momentIndex={MOMENT_INDEX}&fileSize={file_size}",
    method="POST",
    headers={"Authorization": f"Bearer {INGEST_SECRET}"},
)
with urllib.request.urlopen(get_url_req, timeout=60) as resp:
    upload_info = json.load(resp)

put_req = urllib.request.Request(
    upload_info["uploadUrl"],
    data=open(final_path, "rb").read(),
    method=upload_info.get("method", "PUT"),
    headers=upload_info.get("headers", {}),
)
with urllib.request.urlopen(put_req, timeout=300) as put_resp:
    print("upload PUT status:", put_resp.status)

complete_req = urllib.request.Request(
    f"{CONVEX_SITE_URL}/complete-clip",
    data=json.dumps({
        "analysisId": ANALYSIS_ID,
        "momentIndex": int(MOMENT_INDEX),
        "fileId": upload_info["fileId"],
        "audioWarning": audio_warning,
    }).encode(),
    method="POST",
    headers={
        "Authorization": f"Bearer {INGEST_SECRET}",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(complete_req, timeout=60) as resp:
    print(resp.status, resp.read().decode())

print("== Done ==")
