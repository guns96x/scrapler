"""Render a local deck with Microsoft PowerPoint and inspect real text bounds.

Requires pywin32, Pillow, and an installed PowerPoint. Never closes other decks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pythoncom
import win32com.client
from PIL import Image, ImageDraw, ImageFont


def render(deck_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = None
    problems = []
    overlaps = []
    files = []
    try:
        pres = app.Presentations.Open(str(deck_path.resolve()), True, False, False)
        sw, sh = pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight
        for i in range(1, pres.Slides.Count + 1):
            slide = pres.Slides.Item(i)
            text_rects = []
            target = output_dir / f"slide_{i:02}.png"
            slide.Export(str(target.resolve()), "PNG", 1600, 900)
            files.append(target)
            for j in range(1, slide.Shapes.Count + 1):
                shape = slide.Shapes.Item(j)
                if not shape.HasTextFrame or not shape.TextFrame.HasText:
                    continue
                tf = shape.TextFrame2
                tr = tf.TextRange
                text_rects.append((shape.Name, float(tr.BoundLeft), float(tr.BoundTop),
                                   float(tr.BoundWidth), float(tr.BoundHeight)))
                # A 2 pt tolerance avoids rounding noise in Office text metrics.
                if tr.BoundHeight > shape.Height - tf.MarginTop - tf.MarginBottom + 2:
                    problems.append({"slide": i, "shape": shape.Name,
                                     "kind": "text_height",
                                     "excess_pt": round(tr.BoundHeight - shape.Height + tf.MarginTop + tf.MarginBottom, 2)})
                if tr.BoundWidth > shape.Width - tf.MarginLeft - tf.MarginRight + 2:
                    problems.append({"slide": i, "shape": shape.Name,
                                     "kind": "text_width",
                                     "excess_pt": round(tr.BoundWidth - shape.Width + tf.MarginLeft + tf.MarginRight, 2)})
                if (tr.BoundLeft < -2 or tr.BoundTop < -2 or
                        tr.BoundLeft + tr.BoundWidth > sw + 2 or
                        tr.BoundTop + tr.BoundHeight > sh + 2):
                    problems.append({"slide": i, "shape": shape.Name, "kind": "outside_slide"})
            for a, first in enumerate(text_rects):
                for second in text_rects[a + 1:]:
                    an, ax, ay, aw, ah = first
                    bn, bx, by, bw, bh = second
                    iw = min(ax + aw, bx + bw) - max(ax, bx)
                    ih = min(ay + ah, by + bh) - max(ay, by)
                    if iw > 2 and ih > 2 and iw * ih > .04 * min(aw * ah, bw * bh):
                        overlaps.append({"slide": i, "shapes": [an, bn],
                                         "intersection_pt": [round(iw, 2), round(ih, 2)]})
        pres.SaveAs(str((output_dir.parent / "RTN_Premium.pdf").resolve()), 32)
    finally:
        if pres is not None:
            pres.Close()
        # PowerPoint is a shared desktop application. Leave its other documents alone.
        pythoncom.CoUninitialize()

    cols, tw, th, label = 3, 480, 270, 28
    rows = (len(files) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * tw, rows * (th + label)), "#171b22")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 16)
    for n, path in enumerate(files):
        x, y = (n % cols) * tw, (n // cols) * (th + label)
        with Image.open(path) as im:
            canvas.paste(im.resize((tw, th), Image.Resampling.LANCZOS), (x, y))
        draw.text((x + 10, y + th + 3), f"{n + 1:02}", fill="#a5adba", font=font)
    canvas.save(output_dir.parent / "contact_sheet.jpg", quality=92)
    report = {"deck": str(deck_path.resolve()), "slide_count": len(files),
              "renderer": "Microsoft PowerPoint", "text_bound_issues": problems,
              "text_overlap_candidates": overlaps}
    (output_dir.parent / "render_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("premium_deck/preview"))
    args = parser.parse_args()
    print(json.dumps(render(args.deck, args.output_dir), ensure_ascii=False, indent=2))
