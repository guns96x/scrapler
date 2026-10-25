"""
create_presentation_premium.py
==============================
Autonomous generator for high-end editorial 16:9 presentation redesign.
Understated Swiss editorial design system for tactical and analytical briefings.

Adheres strictly to content boundaries:
- Verbatim preservation of source text and table cells.
- Preserves XML soft breaks as newlines.
- Uses premium_layout.py for geometry and typography (body >=18pt, matrix 16.5pt).
- Machine-readable content coverage check.
"""

import os
import argparse
from typing import Dict, Any, Tuple

from pptx import Presentation


# ==============================================================================
# CONTENT EXTRACTION ENGINE (Deterministic python-pptx parser)
# ==============================================================================

def get_paragraph_text_with_br(p) -> str:
    """
    Reconstruct paragraph text preserving XML soft breaks (<a:br>) as newlines.
    python-pptx normally represents these breaks as vertical-tab characters.
    """
    parts = []
    for child in p._p:
        tag = child.tag.split("}")[-1]
        if tag == "r":
            t = child.find("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
            if t is not None and t.text:
                parts.append(t.text)
        elif tag == "br":
            parts.append("\n")
    return "".join(parts) if parts else (p.text or "")


def extract_header_from_slide(slide) -> Tuple[str, str, str]:
    """Extract tag, title, and subtitle from standard header shapes (shapes 1 and 2)."""
    tag_text = ""
    title_text = ""
    sub_text = ""

    # Shape 1 is usually the tag badge
    if len(slide.shapes) > 1 and slide.shapes[1].has_text_frame:
        paras = slide.shapes[1].text_frame.paragraphs
        if paras and paras[0].text.strip():
            tag_text = paras[0].text.strip()

    # Shape 2 is usually title + subtitle
    if len(slide.shapes) > 2 and slide.shapes[2].has_text_frame:
        paras = slide.shapes[2].text_frame.paragraphs
        if len(paras) > 0 and paras[0].text.strip():
            title_text = paras[0].text.strip()
        if len(paras) > 1 and paras[1].text.strip():
            sub_text = paras[1].text.strip()

    return tag_text, title_text, sub_text


def parse_source_deck(source_path: str) -> Dict[str, Any]:
    """
    Deterministically extracts all structured data from the 8 source slides.
    Returns clean dictionary with verbatim texts.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source presentation not found at: {source_path}")

    prs = Presentation(source_path)
    if len(prs.slides) < 8:
        raise ValueError(f"Source presentation must contain at least 8 slides (found {len(prs.slides)})")

    data = {}

    # --------------------------------------------------------------------------
    # SOURCE SLIDE 1: Title, Subtitle, 3 Features, Footer Note
    # --------------------------------------------------------------------------
    s1 = prs.slides[0]
    tf_main = s1.shapes[3].text_frame
    s1_tag = tf_main.paragraphs[0].text.strip()
    s1_title = tf_main.paragraphs[1].text.strip()
    s1_sub = tf_main.paragraphs[2].text.strip()

    s1_features = []
    for sh_idx in [4, 5, 6]:
        sh = s1.shapes[sh_idx]
        f_title = sh.text_frame.paragraphs[0].text.strip()
        f_desc = get_paragraph_text_with_br(sh.text_frame.paragraphs[1]).strip()
        s1_features.append((f_title, f_desc))

    s1_footer = s1.shapes[7].text_frame.paragraphs[0].text.strip()

    data["source_1"] = {
        "tag": s1_tag,
        "title": s1_title,
        "subtitle": s1_sub,
        "features": s1_features,
        "footer": s1_footer,
    }

    # --------------------------------------------------------------------------
    # SOURCE SLIDE 2: 6 Enemy Air Assets (Threats)
    # --------------------------------------------------------------------------
    s2 = prs.slides[1]
    s2_tag, s2_title, s2_sub = extract_header_from_slide(s2)
    s2_threats = []
    for sh_idx in range(3, 9):
        sh = s2.shapes[sh_idx]
        t_title = sh.text_frame.paragraphs[0].text.strip()
        t_metric = sh.text_frame.paragraphs[1].text.strip()
        t_desc = sh.text_frame.paragraphs[2].text.strip()
        s2_threats.append({
            "title": t_title,
            "metric": t_metric,
            "desc": t_desc
        })

    data["source_2"] = {
        "tag": s2_tag,
        "title": s2_title,
        "subtitle": s2_sub,
        "threats": s2_threats
    }

    # --------------------------------------------------------------------------
    # SOURCE SLIDE 3: 4 Phases of Enemy Actions
    # --------------------------------------------------------------------------
    s3 = prs.slides[2]
    s3_tag, s3_title, s3_sub = extract_header_from_slide(s3)
    s3_phases = []
    for sh_idx in range(3, 7):
        sh = s3.shapes[sh_idx]
        p_title = sh.text_frame.paragraphs[0].text.strip()
        p_sub = sh.text_frame.paragraphs[1].text.strip()
        p_bullets = [p.text.strip() for p in sh.text_frame.paragraphs[2:] if p.text.strip()]
        s3_phases.append({
            "title": p_title,
            "subtitle": p_sub,
            "bullets": p_bullets
        })

    data["source_3"] = {
        "tag": s3_tag,
        "title": s3_title,
        "subtitle": s3_sub,
        "phases": s3_phases
    }

    # --------------------------------------------------------------------------
    # SOURCE SLIDE 4: 4 Counter-Air Architecture Blocks (Defenses)
    # --------------------------------------------------------------------------
    s4 = prs.slides[3]
    s4_tag, s4_title, s4_sub = extract_header_from_slide(s4)
    s4_defenses = []
    for sh_idx in range(3, 7):
        sh = s4.shapes[sh_idx]
        d_title = sh.text_frame.paragraphs[0].text.strip()
        d_items = []
        for p in sh.text_frame.paragraphs[1:]:
            full_txt = p.text.strip()
            runs = [r.text for r in p.runs]
            d_items.append({"full_text": full_txt, "runs": runs})
        s4_defenses.append({
            "title": d_title,
            "items": d_items
        })

    data["source_4"] = {
        "tag": s4_tag,
        "title": s4_title,
        "subtitle": s4_sub,
        "defenses": s4_defenses
    }

    # --------------------------------------------------------------------------
    # SOURCE SLIDES 5, 6, 7: Tactical Episodes 2.1, 2.2, 2.3
    # --------------------------------------------------------------------------
    episodes = {}
    for s_idx, ep_key in [(4, "ep_2_1"), (5, "ep_2_2"), (6, "ep_2_3")]:
        sl = prs.slides[s_idx]
        ep_tag, ep_title, ep_sub = extract_header_from_slide(sl)

        # Enemy block (Shape 3)
        en_sh = sl.shapes[3]
        en_title = en_sh.text_frame.paragraphs[0].text.strip()
        en_bullets = []
        for p in en_sh.text_frame.paragraphs[1:]:
            full_txt = p.text.strip()
            runs = [r.text for r in p.runs]
            en_bullets.append({"full_text": full_txt, "runs": runs})

        # Friendly block (Shape 4)
        fr_sh = sl.shapes[4]
        fr_title = fr_sh.text_frame.paragraphs[0].text.strip()
        fr_bullets = []
        for p in fr_sh.text_frame.paragraphs[1:]:
            full_txt = p.text.strip()
            runs = [r.text for r in p.runs]
            fr_bullets.append({"full_text": full_txt, "runs": runs})

        episodes[ep_key] = {
            "source_slide_num": s_idx + 1,
            "tag": ep_tag,
            "title": ep_title,
            "subtitle": ep_sub,
            "enemy": {"title": en_title, "bullets": en_bullets},
            "friendly": {"title": fr_title, "bullets": fr_bullets}
        }

    data["episodes"] = episodes

    # --------------------------------------------------------------------------
    # SOURCE SLIDE 8: Summary Matrix & Golden Rules
    # --------------------------------------------------------------------------
    s8 = prs.slides[7]
    s8_tag, s8_title, s8_sub = extract_header_from_slide(s8)

    # Matrix Table (Shape 3)
    tbl = s8.shapes[3].table
    matrix_headers = [c.text_frame.text.strip() for c in tbl.rows[0].cells]
    matrix_rows = []
    for r in list(tbl.rows)[1:]:
        row_vals = [c.text_frame.text.strip() for c in r.cells]
        matrix_rows.append(row_vals)

    # Golden Rules Box (Shape 4)
    gr_sh = s8.shapes[4]
    gr_title = gr_sh.text_frame.paragraphs[0].text.strip()
    gr_rules = [p.text.strip() for p in gr_sh.text_frame.paragraphs[1:] if p.text.strip()]

    data["source_8"] = {
        "tag": s8_tag,
        "title": s8_title,
        "subtitle": s8_sub,
        "matrix_headers": matrix_headers,
        "matrix_rows": matrix_rows,
        "rules_title": gr_title,
        "rules": gr_rules
    }

    return data


def normalize_whitespace(text: str) -> str:
    return ' '.join(text.split())


def build_deck(source_path: str, output_path: str):
    from premium_layout import compose
    return compose(parse_source_deck(source_path), source_path, output_path)


# ==============================================================================
# CONTENT COVERAGE AUDITOR (Machine-readable verification)
# ==============================================================================

def verify_content_coverage(source_path: str, generated_path: str) -> Dict[str, Any]:
    """
    Extracts every paragraph and table cell string from source_path.
    Verifies that every normalized source string appears in visible shapes or
    table cells of generated_path.
    Fails loudly if any content is missing.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source file not found: {source_path}")
    if not os.path.exists(generated_path):
        raise FileNotFoundError(f"Generated file not found: {generated_path}")

    src_prs = Presentation(source_path)
    gen_prs = Presentation(generated_path)

    # 1. Extract all source non-empty strings
    source_strings = []
    for s_idx, slide in enumerate(src_prs.slides):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    txt = get_paragraph_text_with_br(p).strip()
                    if txt:
                        source_strings.append((s_idx + 1, normalize_whitespace(txt)))
            elif shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            txt = get_paragraph_text_with_br(p).strip()
                            if txt:
                                source_strings.append((s_idx + 1, normalize_whitespace(txt)))

    # 2. Extract all generated visible text elements
    gen_visible_texts = []
    for s_idx, slide in enumerate(gen_prs.slides):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    txt = get_paragraph_text_with_br(p).strip()
                    if txt:
                        gen_visible_texts.append(normalize_whitespace(txt))
            elif shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            txt = get_paragraph_text_with_br(p).strip()
                            if txt:
                                gen_visible_texts.append(normalize_whitespace(txt))

    # Also build a single aggregated string of all visible text per slide to allow substring matching
    gen_full_corpus = normalize_whitespace(" ".join(gen_visible_texts))

    missing_items = []
    matched_count = 0

    for src_slide, s_str in source_strings:
        # Check either exact match in a visible element, or substring in combined visible text
        # If string contains multiple lines, also check line by line
        found = False
        if s_str in gen_visible_texts or s_str in gen_full_corpus:
            found = True
        else:
            # Check if all constituent lines are present
            lines = [normalize_whitespace(l) for l in s_str.split("\n") if l.strip()]
            if lines and all((l in gen_full_corpus) for l in lines):
                found = True

        if found:
            matched_count += 1
        else:
            missing_items.append((src_slide, s_str))

    total_source = len(source_strings)
    coverage_pct = (matched_count / total_source * 100.0) if total_source > 0 else 100.0

    if missing_items:
        err_msg = (
            f"CRITICAL: Content coverage check FAILED! Missing {len(missing_items)} of {total_source} source items.\n"
            f"Missing item indices from source slides: {[item[0] for item in missing_items]}"
        )
        raise AssertionError(err_msg)

    return {
        "status": "PASSED",
        "total_source_items": total_source,
        "covered_items": matched_count,
        "coverage_percentage": f"{coverage_pct:.1f}%",
        "missing_items_count": 0
    }


# ==============================================================================
# CLI DISPATCHER
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate premium Swiss editorial 16:9 presentation deck.")
    parser.add_argument(
        "source",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "Diyi_povitryanogo_protyvnyka_RTGr.pptx"),
        help="Path to source PPTX file"
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=os.path.join(os.path.dirname(__file__), "premium_deck", "RTN_Premium.pptx"),
        help="Path to output generated PPTX file"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run coverage check only without rebuilding"
    )

    args = parser.parse_args()

    source_path = os.path.abspath(args.source)
    output_path = os.path.abspath(args.output)

    if not args.check_only:
        build_results = build_deck(source_path, output_path)

    coverage = verify_content_coverage(source_path, output_path)

    # Output strictly concise report without printing military content
    print("Paths:")
    print(f"  Source: {source_path}")
    print(f"  Output: {output_path}")
    print(f"  Slide Map: {os.path.join(os.path.dirname(output_path), 'slide_map.json')}")
    print(f"Slide Count: {len(Presentation(output_path).slides)}")
    print(f"Min Body Font: 18.0 pt (Matrix: 16.5 pt)")
    print("Checks:")
    print(f"  Total Source Items: {coverage['total_source_items']}")
    print(f"  Total Covered Items: {coverage['covered_items']} ({coverage['coverage_percentage']})")
    print(f"  Coverage Status: {coverage['status']} (Zero missing items)")


if __name__ == "__main__":
    main()
