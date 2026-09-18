#!/usr/bin/env python3
"""
GitHub Actions worker for the "Subtitular video" tool — automated
equivalent of the agent's manual scripts/subtitle-video.sh, triggered by a
repository_dispatch webhook from Convex (see videoEditWorker.ts) instead of
being run by hand. Downloads the user's own uploaded video directly (no
yt-dlp needed — sourceUrl is already a direct file link), transcribes it,
burns in captions at the ORIGINAL resolution/aspect ratio (no crop, no
watermark — that's the whole difference from process_clip.py), and reports
the finished MP4 straight to the app's HTTP endpoints.

This file lives here in the app's own repo as the source of truth, and
gets copied into the separate mercadomarcelo5559/magoosuna GitHub repo
(which runs it via .github/workflows/subtitle-video.yml) — it is not
executed as part of this app itself.
"""
import json
import os
import subprocess
import sys
import urllib.request


def env(name, required=True, default=None):
    v = os.environ.get(name, default)
    if required and not v:
        print(f"Missing required env var: {name}", file=sys.stderr)
        sys.exit(1)
    return v


SOURCE_URL = env("SOURCE_URL")
DESCRIPTION = env("DESCRIPTION", required=False, default="")
VIDEO_EDIT_ID = env("VIDEO_EDIT_ID")
CONVEX_SITE_URL = env("CONVEX_INGEST_URL").rstrip("/")
INGEST_SECRET = env("INGEST_SECRET")

WORKDIR = "/tmp/subtitle-work"
os.makedirs(WORKDIR, exist_ok=True)
os.chdir(WORKDIR)


def run(cmd, **kwargs):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kwargs)


def report_error(message):
    req = urllib.request.Request(
        f"{CONVEX_SITE_URL}/complete-video-edit",
        data=json.dumps({
            "videoEditId": VIDEO_EDIT_ID,
            "errorMessage": message,
        }).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {INGEST_SECRET}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print("error reported:", resp.status, resp.read().decode())
    except Exception as report_err:
        print("failed to report error:", report_err, file=sys.stderr)


try:
    source_file = "source.mp4"
    print("== Downloading source video ==")
    # Macaly's asset CDN blocks requests carrying urllib's default
    # User-Agent ("Python-urllib/3.x") as a bot-protection measure --
    # returns a bare 403 with no other explanation. A normal browser-like
    # UA (or curl's own default) passes fine, so this sets one explicitly
    # instead of using urlretrieve's bare, header-less request.
    dl_req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SubtitleWorker/1.0)"},
    )
    with urllib.request.urlopen(dl_req, timeout=120) as resp, open(source_file, "wb") as out:
        out.write(resp.read())

    print("== Transcribing + building captions ==")
    from faster_whisper import WhisperModel

    def ass_time(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h}:{m:02}:{s:05.2f}"

    # "medium" (not the heavier "large-v3" used for the short viral clips
    # in process_clip.py) — this pipeline transcribes the person's WHOLE
    # uploaded video, whatever its length, inside the same 30-minute CI
    # timeout, so a much slower model risks timing out on a longer upload
    # instead of just being more accurate on a short one.
    #
    # language is intentionally left unset so Whisper auto-detects per
    # video — uploads here aren't guaranteed to be Spanish, so forcing
    # one language would garble anything that isn't. initial_prompt still
    # leads with the user's own DESCRIPTION (their own words, whatever
    # language those happen to be in) as a light content/vocabulary hint.
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        source_file,
        word_timestamps=True,
        initial_prompt=DESCRIPTION if DESCRIPTION else None,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300),
        beam_size=5,
        condition_on_previous_text=False,
    )
    segments = list(segments)

    words = []
    for seg in segments:
        for w in seg.words:
            wd = w.word.strip()
            if wd:
                words.append((w.start, w.end, wd))

    CHUNK = 3
    ACCENTS = ["&H0000FFFF&", "&H0014C8FC&", "&H00FF6EC7&", "&H0000FF66&"]

    # Read the actual video resolution so captions scale to fit any aspect
    # ratio (this tool keeps the original, unlike the vertical clip
    # pipeline in process_clip.py).
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", source_file],
        capture_output=True, text=True, check=True,
    )
    res_w, res_h = [int(x) for x in probe.stdout.strip().split(",")]
    fontsize = max(16, round(res_h * 0.055))

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
                parts.append(f"{{\\c{accent}}}{word}{{\\r}}")
            else:
                parts.append(word)
        text = " ".join(parts)
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_w}
PlayResY: {res_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Poppins ExtraBold,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{max(2, round(fontsize * 0.11))},0,2,10,10,{round(res_h * 0.08)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open("captions.ass", "w") as f:
        f.write(header)
        f.write("\n".join(lines))

    print(f"language: {info.language} | caption lines: {len(lines)} | resolution: {res_w}x{res_h}")

    print("== Burning captions (original resolution, no crop/watermark) ==")
    run([
        "ffmpeg", "-y", "-i", source_file,
        "-vf", "ass=captions.ass",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy",
        "result.mp4", "-loglevel", "error",
    ])

    print("== Uploading result ==")
    file_size = os.path.getsize("result.mp4")

    get_url_req = urllib.request.Request(
        f"{CONVEX_SITE_URL}/get-video-upload-url?videoEditId={VIDEO_EDIT_ID}&fileSize={file_size}",
        method="POST",
        headers={"Authorization": f"Bearer {INGEST_SECRET}"},
    )
    with urllib.request.urlopen(get_url_req, timeout=60) as resp:
        upload_info = json.load(resp)

    put_req = urllib.request.Request(
        upload_info["uploadUrl"],
        data=open("result.mp4", "rb").read(),
        method=upload_info.get("method", "PUT"),
        headers=upload_info.get("headers", {}),
    )
    with urllib.request.urlopen(put_req, timeout=300) as put_resp:
        print("upload PUT status:", put_resp.status)

    complete_req = urllib.request.Request(
        f"{CONVEX_SITE_URL}/complete-video-edit",
        data=json.dumps({
            "videoEditId": VIDEO_EDIT_ID,
            "fileId": upload_info["fileId"],
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

except Exception as err:
    print(f"ERROR: {err}", file=sys.stderr)
    report_error(f"Falló el procesamiento: {err}"[:500])
    raise
