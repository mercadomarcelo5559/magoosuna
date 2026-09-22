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
ASPECT_RATIO = env("ASPECT_RATIO", required=False, default="9:16")
ASPECT_DIMENSIONS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
OUT_W, OUT_H = ASPECT_DIMENSIONS.get(ASPECT_RATIO, (1080, 1920))

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


name = f"clip_{MOMENT_INDEX}"

# When run from the process-video workflow, the source was already
# downloaded ONCE and this moment's range pre-cut by download_segments.py
# (same ffmpeg settings as the cut below) -- so skip YouTube entirely.
# Clips are cut with extra margin and then snapped to sentence boundaries
# after transcription (see "Snapping to sentence boundaries" below), so a
# clip never starts or ends mid-word/mid-thought. Must match
# download_segments.py's PAD_BEFORE/PAD_AFTER.
PAD_BEFORE, PAD_AFTER = 3.0, 8.0
SEG_START = max(0.0, START - PAD_BEFORE)
SEG_END = END + PAD_AFTER
REL_START, REL_END = START - SEG_START, END - SEG_START

SEGMENT_FILE = os.environ.get("SEGMENT_FILE")
if SEGMENT_FILE:
    print(f"== Using pre-cut segment {SEGMENT_FILE} (no YouTube download) ==")
    import shutil
    shutil.copy(SEGMENT_FILE, f"{name}_cut.mp4")

video_id = extract_video_id(VIDEO_URL)
source_file = f"source_{video_id}.mp4"

if not SEGMENT_FILE and not os.path.exists(source_file):
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
elif not SEGMENT_FILE:
    print("== Source already cached ==")

if not SEGMENT_FILE:
    print(f"== Cutting {SEG_START}-{SEG_END}s (padded) ==")
    run([
        "ffmpeg", "-y", "-ss", str(SEG_START), "-to", str(SEG_END), "-i", source_file,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        f"{name}_cut.mp4", "-loglevel", "error",
    ])

print(f"== Converting to {ASPECT_RATIO} ({OUT_W}x{OUT_H}) ==")
run([
    "ffmpeg", "-y", "-i", f"{name}_cut.mp4", "-filter_complex",
    f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
    f"gblur=sigma=25[bg];[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fg];"
    "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]",
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

KEEP_RANGES = [(0.0, duration)]
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
    KEEP_RANGES = list(keep)

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
# language is intentionally left unset -- clips aren't guaranteed to be
# Spanish (this pipeline runs on whatever YouTube video someone submits,
# any language), so Whisper auto-detects per clip instead of a hardcoded
# language forcing every clip's audio into the wrong one when it isn't
# Spanish. The bigger model + tighter VAD below already make that
# auto-detection meaningfully more reliable than it was on "medium".
#
# NO initial_prompt on purpose. It used to prime the decoder with the
# clip's AI-written title as a vocabulary hint, but that backfired badly:
# the top-scored clip's title paraphrases what's said in it most closely,
# and Whisper would echo the prompt back as the "transcript" instead of
# listening -- e.g. a 33s clip came out as just the title text for the
# first 30s (15 words total) vs 126 real words without the prompt. It hit
# clip 0 on essentially every video. A Spanish title on English audio made
# it worse. Plain transcription is strictly more reliable here.
model = WhisperModel("large-v3", device="cpu", compute_type="int8")
segments, info = model.transcribe(
    f"{name}.mp4",
    word_timestamps=True,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=300),
    beam_size=5,
    condition_on_previous_text=False,
    # A low-speech stretch (a reaction shot, a sound-effect-only beat, a
    # laugh with no clear words) can make Whisper "hallucinate" -- instead
    # of correctly outputting nothing, it gets stuck looping the same
    # phrase over and over for many seconds. These two options are the
    # standard mitigation: no_repeat_ngram_size blocks the decoder from
    # repeating the same 3-word sequence back to back, and
    # repetition_penalty further discourages it from choosing an
    # already-used word again. Normal, non-repetitive speech is
    # unaffected by either.
    no_repeat_ngram_size=3,
    repetition_penalty=1.2,
)
segments = list(segments)

# The old metric here averaged no_speech_prob across only the segments
# Whisper DID detect speech in -- so a clip that's 88% silence but has
# one confidently-transcribed 3-second line in it (exactly what happened
# on a real clip: two short lines, 22 seconds apart, in an otherwise
# silent 33-second clip) came out looking perfectly fine by that average,
# even though almost the whole thing has no dialogue at all. This instead
# measures how much of the CLIP'S OWN DURATION actually has detected
# speech in it, which is what "should I review the audio on this one"
# actually needs to know.
speech_seconds = sum(s.end - s.start for s in segments)
speech_coverage = speech_seconds / duration if duration > 0 else 0
# faster-whisper's segment.start/.end can come back as numpy float32, which
# makes the comparison below a numpy.bool_ instead of a plain Python bool --
# and numpy.bool_ isn't JSON-serializable, which broke the result upload
# entirely (the clip rendered fine, but reporting the result back failed).
# bool(...) forces it back to a plain, always-JSON-safe Python bool.
audio_warning = bool(speech_coverage < 0.4)

# Extra safety net on top of the decoder-level anti-repeat options above:
# if a hallucination loop still slips through, this skips a word that's
# the exact same text as the one right before it with barely any gap in
# between (a real person repeating a word for emphasis pauses noticeably
# longer than a looping hallucination does), so a burned-in caption never
# visibly freezes on the same phrase for many seconds even in that
# fallback case.
words = []
for seg in segments:
    for w in seg.words:
        wd = w.word.strip()
        if not wd:
            continue
        if words and words[-1][2].strip().lower() == wd.lower() and (w.start - words[-1][1]) < 0.25:
            continue
        words.append((w.start, w.end, wd))

# == Snapping to sentence boundaries ==
# The AI's moment times are estimates in whole seconds, so cutting exactly
# on them often lands mid-sentence or mid-word. The clip was cut with
# PAD_BEFORE/PAD_AFTER margin; now pick the real start/end from Whisper's
# word timings: start on the first word of a sentence near the target,
# end on the last word of a sentence at/after the target (letting a
# thought finish, up to PAD_AFTER extra), never splitting a word.
print("== Snapping to sentence boundaries ==")


def _map_time(t):
    acc = 0.0
    for s, e in KEEP_RANGES:
        if t < s:
            return acc
        if t <= e:
            return acc + (t - s)
        acc += e - s
    return acc


_END_PUNCT = (".", "?", "!", "\u2026", "\u3002")
target_s, target_e = _map_time(REL_START), _map_time(REL_END)
new_start, new_end = target_s, min(target_e, duration)
if words:
    def _starts_sentence(i):
        return i == 0 or words[i - 1][2].endswith(_END_PUNCT) or words[i][0] - words[i - 1][1] >= 0.35

    def _ends_sentence(j):
        return j == len(words) - 1 or words[j][2].endswith(_END_PUNCT) or words[j + 1][0] - words[j][1] >= 0.5

    starts = [i for i in range(len(words)) if _starts_sentence(i) and target_s - 3.0 <= words[i][0] <= target_s + 2.0]
    if starts:
        si = min(starts, key=lambda i: abs(words[i][0] - target_s))
    else:  # no clean sentence start nearby: at least start on a whole word
        si = next((i for i in range(len(words)) if words[i][0] >= target_s - 0.2), 0)
    ends = [j for j in range(si, len(words)) if _ends_sentence(j) and target_e - 1.0 <= words[j][1] <= target_e + PAD_AFTER]
    if ends:
        ej = ends[0]
    else:  # no sentence end in range: end on the whole word nearest the target
        cand = [j for j in range(si, len(words)) if words[j][1] <= target_e + PAD_AFTER] or [len(words) - 1]
        ej = min(cand, key=lambda j: abs(words[j][1] - target_e))
    # Guard against a degenerate snap (e.g. a far-off sentence boundary
    # shrinking the clip): fall back to plain whole-word boundaries around
    # the targets -- still never mid-word, never the raw estimate.
    if words[ej][1] - words[si][0] < 0.6 * max(1.0, target_e - target_s):
        si = next((i for i in range(len(words)) if words[i][0] >= target_s - 0.2), 0)
        cand = [j for j in range(si, len(words)) if words[j][1] <= target_e + 1.0] or [len(words) - 1]
        ej = max(cand)
    new_start = max(0.0, words[si][0] - 0.15)
    new_end = min(duration, words[ej][1] + 0.35)
print(f"target {target_s:.2f}-{target_e:.2f}s -> snapped {new_start:.2f}-{new_end:.2f}s")

snapped = f"{name}_snap.mp4"
run(["ffmpeg", "-y", "-ss", f"{new_start:.3f}", "-to", f"{new_end:.3f}", "-i", f"{name}.mp4",
     "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
     snapped, "-loglevel", "error"])
os.replace(snapped, f"{name}.mp4")
words = [(s - new_start, e - new_start, t) for s, e, t in words if s >= new_start - 0.05 and e <= new_end + 0.05]
duration = get_duration(f"{name}.mp4")

# Keyword -> emoji, appended after the highlighted word when it matches —
# the same kind of reaction-emoji clippers add by hand, but automatic. Only
# the CURRENTLY highlighted word is checked (not the whole context window)
# so at most one emoji shows per line, keeping it a light touch rather than
# cluttering every caption. Checked as a whole-word match on the stripped,
# lowercased, accent-insensitive token so plurals/punctuation don't miss.
EMOJI_KEYWORDS = {
    "dinero": "💰", "pesos": "💰", "dolares": "💰", "plata": "💰",
    "dios": "🙏", "amor": "❤️", "fuego": "🔥", "increible": "🤯",
    "loco": "🤯", "locura": "🤯", "miedo": "😱", "asustado": "😱",
    "triste": "😢", "llorar": "😢", "risa": "😂", "reir": "😂",
    "ganar": "🏆", "perder": "📉", "exito": "🚀", "negocio": "💼",
    "tiempo": "⏰", "rapido": "⚡", "cuidado": "⚠️", "peligro": "⚠️",
    "secreto": "🤫", "mentira": "🤥", "verdad": "💯", "muerte": "💀",
    "corazon": "❤️", "familia": "👪", "trabajo": "💼", "idea": "💡",
}
import unicodedata as _ud


def _emoji_for(word_raw: str):
    stripped = word_raw.strip('.,!?¡¿"\'():;').lower()
    normalized = "".join(
        c for c in _ud.normalize("NFD", stripped) if _ud.category(c) != "Mn"
    )
    return EMOJI_KEYWORDS.get(normalized)


ACCENTS = ["&H0000FFFF&", "&H0014C8FC&", "&H00FF6EC7&", "&H0000FF66&"]
CONTEXT_BEFORE, CONTEXT_AFTER = 1, 1
MAX_GAP_BRIDGE = 0.15
res_w, res_h = OUT_W, OUT_H
# Caption/headline sizing scales off the SHORTER side so text stays a
# sensible size whether the frame is tall (9:16), square (1:1), or wide
# (16:9) — sizing purely off res_h (as before, when this was always
# 1080x1920) would make captions comically huge on a 1920x1080 horizontal
# clip.
short_side = min(res_w, res_h)
fontsize = max(18, round(short_side * 0.075))

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
            emoji = _emoji_for(jw_t)
            display = f"{word} {emoji}" if emoji else word
            parts.append("{\\c%s\\fscx128\\fscy128}%s{\\r}" % (accent, display))
        else:
            parts.append(word)
    text = " ".join(parts)
    display_end = we
    if i + 1 < len(words):
        gap = words[i + 1][0] - we
        if gap > 0:
            display_end = we + min(gap, MAX_GAP_BRIDGE)
    lines.append(f"Dialogue: 0,{ass_time(ws)},{ass_time(display_end)},Default,,0,0,0,,{text}")

watermark_fontsize = max(14, round(short_side * 0.022))
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
Style: Headline,{FONT_FAMILY},{round(short_side * 0.085)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{round(short_side * 0.011)},0,8,60,60,{round(res_h * 0.09)},1

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
