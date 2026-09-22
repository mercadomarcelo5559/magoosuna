#!/usr/bin/env python3
"""
Stage 1 of the process-video workflow: downloads the source video from
YouTube ONCE, then cuts each moment's time range into its own small
segment file (seg_<index>.mp4). Those segments are passed to the parallel
per-clip jobs as a workflow artifact, so a 6-clip video costs 1 YouTube
download instead of 6 -- faster, and far less likely to trip YouTube's
bot detection (the pipeline's biggest operational risk).

The cut uses exactly the same ffmpeg settings process_clip.py used to
apply itself, so the per-clip output is unchanged.
"""
import json
import os
import re
import subprocess
import sys
import time

VIDEO_URL = os.environ["VIDEO_URL"]
MOMENTS = json.loads(os.environ["MOMENTS_JSON"])
OUT_DIR = os.path.abspath(os.environ.get("SEGMENTS_DIR", "segments"))
os.makedirs(OUT_DIR, exist_ok=True)

FORMAT_SELECTOR = "bv*[height<=1080]+ba/b[height<=1080]"
# Extra margin around each moment so process_clip.py can snap the final
# cut to sentence boundaries. Must match process_clip.py's constants.
PAD_BEFORE, PAD_AFTER = 3.0, 20.0


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def extract_video_id(url):
    for p in [r"watch\?v=([\w-]{11})", r"youtu\.be/([\w-]{11})",
              r"shorts/([\w-]{11})", r"live/([\w-]{11})", r"embed/([\w-]{11})"]:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError("Could not extract video ID from " + url)


video_id = extract_video_id(VIDEO_URL)
source_file = os.path.join(OUT_DIR, f"source_{video_id}.mp4")

print(f"== Downloading source video once for {len(MOMENTS)} clip(s) ==")
strategies = [
    ["--js-runtimes", "node", "--remote-components", "ejs:github"],
    ["--extractor-args", "youtube:player_client=tv,web_safari"],
    ["--extractor-args", "youtube:player_client=web_safari"],
]
last_err = None
for attempt, extra_args in enumerate(strategies, start=1):
    try:
        print(f"-- download attempt {attempt}: {' '.join(extra_args)} --")
        run(["yt-dlp", "--cookies", "/tmp/youtube_cookies.txt", *extra_args,
             "-f", FORMAT_SELECTOR, "--merge-output-format", "mp4",
             "-o", source_file, f"https://www.youtube.com/watch?v={video_id}"])
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

for m in MOMENTS:
    idx = m["i"]
    if m.get("exact"):  # user hand-edited times: cut exactly there
        start, end = float(m["s"]), float(m["e"])
    else:
        start, end = max(0.0, float(m["s"]) - PAD_BEFORE), float(m["e"]) + PAD_AFTER
    out = os.path.join(OUT_DIR, f"seg_{idx}.mp4")
    print(f"== Cutting moment {idx}: {start}-{end}s ==")
    run(["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", source_file,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", out, "-loglevel", "error"])

os.remove(source_file)  # only the small segments go into the artifact
print("segments:", sorted(os.listdir(OUT_DIR)))
