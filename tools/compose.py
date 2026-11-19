#!/usr/bin/env python3
"""Lager en 'Ranking Best X'-short (1080x1920) fra 5 klipp + config.

Bruk: python3 compose.py config.json output.mp4
config.json:
{
  "title_white": "Ranking Best",
  "title_red": "Cat Fails",
  "clips": [
    {"file": "clips/a.mp4", "rank": 3, "label": "Mid-air regret"},
    ...
  ]
}
Klippene vises i rekkefølgen i lista; hvert får plass `rank` (1-5) på lista,
og teksten dukker opp ved plassen 1 sek inn i klippet og blir stående.
"""
import json, subprocess, sys, os, tempfile

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/google-fonts/ofl/archivoblack/ArchivoBlack-Regular.ttf"
RANK_COLORS = {1: "#F7C21B", 2: "#FFFFFF", 3: "#F08A24", 4: "#A6A6A6", 5: "#E8322B"}
LIST_TOP, LIST_STEP, LIST_X = 560, 175, 70
TITLE_Y, TITLE_SIZE = 230, 74
NUM_SIZE, LABEL_SIZE = 84, 58
REVEAL = 1.0  # sek inn i klippet før teksten settes på plass


def dur(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path])
    return float(out)


def has_audio(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a",
                                   "-show_entries", "stream=index", "-of", "csv=p=0", path])
    return bool(out.strip())


def text_width(text, size):
    from PIL import ImageFont
    return ImageFont.truetype(FONT, size).getlength(text)


def main(cfg_path, out_path):
    cfg = json.load(open(cfg_path))
    base = os.path.dirname(os.path.abspath(cfg_path))
    clips = cfg["clips"]
    tmp = tempfile.mkdtemp()

    # 1) Normaliser hvert klipp til 1080x1920, 30fps, med lydspor
    norm, starts, t = [], [], 0.0
    for i, c in enumerate(clips):
        src = os.path.join(base, c["file"])
        d = dur(src)
        dst = os.path.join(tmp, f"n{i}.mp4")
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"fps=30,format=yuv420p,setsar=1")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
        if not has_audio(src):
            cmd += ["-f", "lavfi", "-t", str(d), "-i", "anullsrc=r=44100:cl=stereo"]
        cmd += ["-vf", vf, "-map", "0:v:0", "-map", "0:a:0" if has_audio(src) else "1:a:0",
                "-t", str(d), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-ar", "44100", "-ac", "2", dst]
        subprocess.run(cmd, check=True)
        norm.append(dst); starts.append(t); t += d
    total = t

    # 2) Slå sammen
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in norm))
    joined = os.path.join(tmp, "joined.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", joined], check=True)

    # 3) Tekst-overlegg (tekst via filer for å slippe escaping)
    def tf(name, text):
        p = os.path.join(tmp, name); open(p, "w").write(text); return p

    stroke = "borderw=7:bordercolor=black"
    shadow = "shadowcolor=black@0.6:shadowx=4:shadowy=5"
    filters = []
    tw = text_width(cfg["title_white"] + " ", TITLE_SIZE)
    tr = text_width(cfg["title_red"], TITLE_SIZE)
    x0 = (W - (tw + tr)) / 2
    filters.append(f"drawtext=fontfile={FONT}:textfile={tf('tw.txt', cfg['title_white'])}:"
                   f"fontsize={TITLE_SIZE}:fontcolor=white:{stroke}:{shadow}:x={x0:.0f}:y={TITLE_Y}")
    filters.append(f"drawtext=fontfile={FONT}:textfile={tf('tr.txt', cfg['title_red'])}:"
                   f"fontsize={TITLE_SIZE}:fontcolor=#E8211B:{stroke}:{shadow}:x={x0 + tw:.0f}:y={TITLE_Y}")
    for r in range(1, 6):
        y = LIST_TOP + (r - 1) * LIST_STEP
        filters.append(f"drawtext=fontfile={FONT}:text='{r}.':fontsize={NUM_SIZE}:"
                       f"fontcolor={RANK_COLORS[r]}:{stroke}:{shadow}:x={LIST_X}:y={y}")
    pops = []
    for i, c in enumerate(clips):
        r = c["rank"]; at = starts[i] + REVEAL
        y = LIST_TOP + (r - 1) * LIST_STEP + (NUM_SIZE - LABEL_SIZE) // 2 + 4
        x = LIST_X + text_width(f"{r}.", NUM_SIZE) + 22
        # liten "pop": skalerer opp fontstørrelsen de første 0.15 s
        size = f"if(lt(t-{at:.2f}\\,0.15)\\,{LABEL_SIZE}*(0.6+0.4*(t-{at:.2f})/0.15)\\,{LABEL_SIZE})"
        filters.append(f"drawtext=fontfile={FONT}:textfile={tf(f'l{i}.txt', c['label'])}:"
                       f"fontsize='{size}':fontcolor=white:{stroke}:{shadow}:x={x:.0f}:y={y}:"
                       f"enable='gte(t\\,{at:.2f})'")
        pops.append(at)

    # 4) Lydeffekt ("pop") når hver tekst settes på plass
    pop = os.path.join(tmp, "pop.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=f=880:d=0.12,afade=t=out:st=0.02:d=0.1,volume=0.5", pop], check=True)
    inputs = ["-i", joined] + sum([["-i", pop] for _ in pops], [])
    amix = "".join(f"[{k+1}:a]adelay={int(p*1000)}|{int(p*1000)}[p{k}];" for k, p in enumerate(pops))
    amix += "[0:a]" + "".join(f"[p{k}]" for k in range(len(pops)))
    amix += f"amix=inputs={len(pops)+1}:normalize=0:duration=first[a]"
    fc = "[0:v]" + ",".join(filters) + "[v];" + amix
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", str(total),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_path], check=True)
    print(f"OK: {out_path} ({total:.1f}s)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
