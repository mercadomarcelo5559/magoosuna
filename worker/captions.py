"""Clipea caption engine, shared by process_clip.py (viral clips) and
subtitle_video.py ("Subtitular video"). Deployed as worker/captions.py in
the GitHub worker repo; this file is the source copy.

What it does better than the old per-script code:
- Language: CAPTION_LANGUAGE = auto | es | en. "auto" detects over several
  audio windows (not just the first 30s) and, if the result is an unsure
  guess outside es/en, re-runs forced to whichever of es/en scored higher.
- Readable phrase groups (2-5 words, never across a pause or sentence end,
  max chars per line so it never overflows), shown for the whole phrase
  while the word being spoken lights up (karaoke). No more text jumping
  every word or rainbow colors.
- One accent color (CAPTION_COLOR), position (CAPTION_POSITION), case
  (CAPTION_CASE), stronger outline + shadow for any background.
- Correct size for rotated phone videos (iPhone portrait).
"""
import json
import os
import re
import subprocess
import unicodedata

LANGUAGE = (os.environ.get("CAPTION_LANGUAGE") or "auto").strip().lower()
COLOR = (os.environ.get("CAPTION_COLOR") or "yellow").strip().lower()
POSITION = (os.environ.get("CAPTION_POSITION") or "bottom").strip().lower()
CASE = (os.environ.get("CAPTION_CASE") or "upper").strip().lower()

# ASS colors are &HAABBGGRR
COLORS = {
    "yellow": "&H0000E5FF&",
    "green": "&H0066FF22&",
    "pink": "&H007F3DFF&",
    "cyan": "&H00FFE500&",
    "white": "&H00FFFFFF&",
}
ACCENT = COLORS.get(COLOR, COLORS["yellow"])

BASE_KW = dict(
    word_timestamps=True,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=300),
    beam_size=5,
    condition_on_previous_text=False,
    no_repeat_ngram_size=3,
    repetition_penalty=1.2,
)
DETECT_KW = dict(language_detection_segments=4, language_detection_threshold=0.6)


def _run(model, path, kw):
    try:
        segments, info = model.transcribe(path, **kw)
    except TypeError:
        # older faster-whisper without these options
        for k in ("language_detection_segments", "language_detection_threshold", "hotwords"):
            kw.pop(k, None)
        segments, info = model.transcribe(path, **kw)
    return list(segments), info


def transcribe(model, path, hotwords=None):
    kw = dict(BASE_KW)
    if hotwords:
        # hotwords bias vocabulary WITHOUT the echo problem initial_prompt had
        kw["hotwords"] = hotwords[:220]
    if LANGUAGE in ("es", "en"):
        kw["language"] = LANGUAGE
        segments, info = _run(model, path, kw)
    else:
        segments, info = _run(model, path, {**kw, **DETECT_KW})
        if info.language not in ("es", "en") and (info.language_probability or 0) < 0.8:
            probs = dict(info.all_language_probs or [])
            best = "en" if probs.get("en", 0) > probs.get("es", 0) else "es"
            print(f"unsure language {info.language} ({info.language_probability:.2f}) -> retry as {best}")
            segments, info = _run(model, path, {**kw, "language": best})
    print(f"caption language: {info.language} ({(info.language_probability or 0):.2f})")
    return segments, info


def words_from(segments):
    words = []
    for seg in segments:
        for w in seg.words or []:
            wd = w.word.strip()
            if not wd:
                continue
            if words and words[-1][2].lower() == wd.lower() and (w.start - words[-1][1]) < 0.25:
                continue  # hallucination loop guard
            words.append((float(w.start), float(w.end), wd))
    return words


def probe_size(path):
    """Display size, honoring rotation metadata (iPhone portrait videos)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    ).stdout
    st = json.loads(out)["streams"][0]
    w, h = int(st["width"]), int(st["height"])
    rot = (st.get("tags") or {}).get("rotate")
    for sd in st.get("side_data_list") or []:
        if "rotation" in sd:
            rot = sd["rotation"]
    try:
        if abs(int(float(rot or 0))) % 180 == 90:
            w, h = h, w
    except ValueError:
        pass
    return w, h


EMOJI = {
    "dinero": "💰", "pesos": "💰", "dolares": "💰", "money": "💰", "cash": "💰",
    "dios": "🙏", "god": "🙏", "amor": "❤️", "love": "❤️", "corazon": "❤️",
    "fuego": "🔥", "fire": "🔥", "increible": "🤯", "insane": "🤯", "crazy": "🤯",
    "loco": "🤯", "locura": "🤯", "miedo": "😱", "scared": "😱",
    "triste": "😢", "sad": "😢", "risa": "😂", "funny": "😂",
    "ganar": "🏆", "win": "🏆", "exito": "🚀", "success": "🚀",
    "negocio": "💼", "business": "💼", "trabajo": "💼",
    "tiempo": "⏰", "rapido": "⚡", "fast": "⚡",
    "secreto": "🤫", "secret": "🤫", "verdad": "💯", "truth": "💯",
    "idea": "💡", "muerte": "💀", "dead": "💀",
}


def _norm(t):
    t = t.strip(".,!?¡¿\"'():;…").lower()
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def _display(t):
    t = re.sub(r"[,.;:]+$", "", t.strip())  # keep ? ! … ¿ ¡
    t = t.replace("{", "").replace("}", "").replace("\\", "")
    return t.upper() if CASE == "upper" else t


_END = (".", "?", "!", "…")


def group_words(words, vertical):
    max_words = 3 if vertical else 5
    max_chars = 16 if vertical else 30
    groups, cur = [], []
    for s, e, t in words:
        if cur:
            ps, pe, pt = cur[-1]
            chars = sum(len(x[2]) for x in cur) + len(cur) + len(t)
            if (s - pe >= 0.45 or pt.endswith(_END) or len(cur) >= max_words
                    or chars > max_chars or (pt.endswith(",") and len(cur) >= 2)):
                groups.append(cur)
                cur = []
        cur.append((s, e, t))
    if cur:
        groups.append(cur)
    return groups


def build_events(words, res_w, res_h, duration, ass_time, emojis=True):
    """Dialogue lines for style "Default": phrase on screen, active word lit."""
    lines = []
    groups = group_words(words, res_h >= res_w)
    for gi, g in enumerate(groups):
        nxt = groups[gi + 1][0][0] if gi + 1 < len(groups) else None
        g_end = g[-1][1] + 0.6 if nxt is None else min(nxt, g[-1][1] + 0.6)
        if duration:
            g_end = min(g_end, duration)
        shown = [_display(t) for _, _, t in g]
        for k, (s, e, t) in enumerate(g):
            start = g[0][0] if k == 0 else s
            end = g[k + 1][0] if k + 1 < len(g) else g_end
            if end - start < 0.05:
                end = start + 0.05
            parts = []
            for j, word in enumerate(shown):
                if j == k:
                    emo = EMOJI.get(_norm(t)) if emojis else None
                    lit = f"{word} {emo}" if emo else word
                    parts.append("{\\c%s\\fscx110\\fscy110}%s{\\r}" % (ACCENT, lit))
                else:
                    parts.append(word)
            fade = "{\\fad(70,0)}" if k == 0 else ""
            text = " ".join(parts)
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{fade}{text}")
    return lines


def style_line(font, fontsize, res_w, res_h):
    outline = max(2, round(fontsize * 0.12))
    shadow = max(1, round(fontsize * 0.04))
    if POSITION == "middle":
        align, margin_v = 5, 0
    elif POSITION == "top":
        align, margin_v = 8, round(res_h * 0.14)
    else:
        align, margin_v = 2, round(res_h * (0.16 if res_h >= res_w else 0.08))
    margin_h = round(res_w * 0.06)
    return (f"Style: Default,{font},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,"
            f"-1,0,0,0,100,100,0,0,1,{outline},{shadow},{align},{margin_h},{margin_h},{margin_v},1")
