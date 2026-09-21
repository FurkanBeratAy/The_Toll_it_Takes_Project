#!/usr/bin/env python3
"""Build The Toll It Takes — presentation deck.
Captures live-site elements via Playwright, assembles with python-pptx.
"""
import sys, json, math, tempfile, shutil
from pathlib import Path
from io import BytesIO

# ── paths ────────────────────────────────────────────────────────────────────
REPO     = Path(r"C:\Users\Furkan\Desktop\The Toll it Takes GitHub")
DOCS     = REPO / "docs"
DATA     = REPO / "data" / "processed"
IMGS     = REPO / "_slide_imgs"
PPTX_OUT = DOCS / "The_Toll_It_Takes_slides.pptx"
CONTACT  = DOCS / "contact_sheet.png"
IMGS.mkdir(exist_ok=True)

# ── palette (mirror docs/css/style.css) ─────────────────────────────────────
from pptx.dml.color import RGBColor
PURPLE     = RGBColor(0x4B, 0x2E, 0x83)
BRICK      = RGBColor(0xB4, 0x39, 0x1B)
GREEN      = RGBColor(0x2F, 0x6B, 0x3A)
INK        = RGBColor(0x2A, 0x2D, 0x2B)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
HAZE       = RGBColor(0xF2, 0xF3, 0xF1)
RULE_C     = RGBColor(0xD8, 0xDB, 0xD8)
MUTED      = RGBColor(0x6B, 0x70, 0x6C)
TOLL_SOFT  = RGBColor(0xE9, 0xE3, 0xF3)
WORSE_SOFT = RGBColor(0xF6, 0xE4, 0xDD)

# ── data ─────────────────────────────────────────────────────────────────────
with open(DATA / "headline_stats.json") as f:
    hs = json.load(f)
with open(DATA / "canyon_analysis.json") as f:
    ca = json.load(f)
with open(DATA / "school_zone.json") as f:
    sz = json.load(f)

# ── pptx imports ─────────────────────────────────────────────────────────────
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_CONNECTOR_TYPE
from pptx.oxml.ns import qn
from lxml import etree

# slide: 16 × 9 widescreen
W = Inches(13.333)
H = Inches(7.5)

MARGIN_L  = Inches(0.55)
MARGIN_T  = Inches(0.45)
CONTENT_W = W - Inches(1.1)

# ── pptx helpers ─────────────────────────────────────────────────────────────
def new_prs():
    prs = Presentation()
    prs.slide_width  = W
    prs.slide_height = H
    return prs

def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])

def rect(sl, l, t, w, h, fill=None, line_color=None, line_w=Pt(0)):
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    sh = sl.shapes.add_shape(1, l, t, w, h)   # 1 = MSO_AUTO_SHAPE_TYPE.RECTANGLE
    if fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    else:
        sh.fill.background()
    if line_color:
        sh.line.color.rgb = line_color
        sh.line.width = line_w
    else:
        sh.line.fill.background()
    return sh

def txt(sl, text, l, t, w, h,
        size=13, bold=False, italic=False,
        color=INK, align=PP_ALIGN.LEFT,
        font="Arial", wrap=True):
    tb = sl.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.auto_size = None
    p = tf.paragraphs[0]
    p.alignment = align
    rn = p.add_run()
    rn.text = text
    rn.font.name = font
    rn.font.size = Pt(size)
    rn.font.bold = bold
    rn.font.italic = italic
    rn.font.color.rgb = color
    return tb

def img(sl, path, l, t, w=None, h=None):
    path = Path(path)
    if not path.exists():
        return None
    kw = {}
    if w: kw["width"] = w
    if h: kw["height"] = h
    return sl.shapes.add_picture(str(path), l, t, **kw)

def rule(sl, y, color=RULE_C, width=Pt(0.75)):
    cn = sl.shapes.add_connector(
        MSO_CONNECTOR_TYPE.STRAIGHT,
        MARGIN_L, y, W - MARGIN_L, y)
    cn.line.color.rgb = color
    cn.line.width = width

def top_bar(sl, color=PURPLE, h=Inches(0.07)):
    rect(sl, 0, 0, W, h, fill=color)

def kicker(sl, text, color=PURPLE):
    txt(sl, text, MARGIN_L, MARGIN_T, CONTENT_W, Inches(0.38),
        size=10, bold=True, color=color, font="Arial")

def heading(sl, text, color=INK, size=26):
    txt(sl, text, MARGIN_L, Inches(0.83), CONTENT_W, Inches(0.55),
        size=size, bold=True, color=color, font="Arial")

def caption(sl, text, y=Inches(6.95)):
    txt(sl, text, MARGIN_L, y, CONTENT_W, Inches(0.48),
        size=8, italic=True, color=MUTED)

def notes(sl, text):
    sl.notes_slide.notes_text_frame.text = text

# ── Playwright screenshot capture ────────────────────────────────────────────
def capture():
    from playwright.sync_api import sync_playwright

    part1_url  = "file:///" + str(DOCS / "part1.html").replace("\\", "/")
    index_url  = "file:///" + str(DOCS / "index.html").replace("\\", "/")

    print("  Launching Chromium…")
    with sync_playwright() as p:
        br = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--enable-webgl",
                "--ignore-gpu-blocklist",
                "--disable-gpu-driver-bug-workarounds",
                "--enable-accelerated-2d-canvas",
            ],
        )
        ctx = br.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
        )
        pg = ctx.new_page()

        def wait_charts(timeout=18000):
            try:
                pg.wait_for_function(
                    "document.querySelectorAll('.js-plotly-plot').length > 0",
                    timeout=timeout,
                )
                pg.wait_for_timeout(2500)
            except Exception:
                pg.wait_for_timeout(4000)

        def shot(selector, fname, fallback=None):
            el = pg.query_selector(selector)
            if el:
                el.screenshot(path=str(IMGS / fname))
                print(f"    captured {fname}")
            elif fallback:
                fb = pg.query_selector(fallback)
                if fb:
                    fb.screenshot(path=str(IMGS / fname))
                    print(f"    captured {fname} (fallback)")
                else:
                    print(f"    WARNING: neither {selector!r} nor {fallback!r} found")
            else:
                print(f"    WARNING: {selector!r} not found")

        # ── index.html: corridor strip ──────────────────────────────────────
        print("  Loading index.html…")
        pg.goto(index_url)
        pg.wait_for_timeout(4000)
        shot(".corridor-strip", "corridor_strip.png", "main")

        # ── part1.html ──────────────────────────────────────────────────────
        print("  Loading part1.html…")
        pg.goto(part1_url)
        pg.wait_for_timeout(6000)
        wait_charts()

        # Section 1: map wrap (map + legend + toggles)
        shot(".map-wrap", "map_section1.png", "#map-aqi")

        # Section 2: wait for loading spinner to hide, then grab ITS container
        try:
            pg.wait_for_selector("#chart-its-container .loading",
                                  state="hidden", timeout=12000)
        except Exception:
            pass
        pg.wait_for_timeout(2000)

        # Try to find the Manhattan Bridge chart specifically
        mb = None
        for sel in [
            "#chart-its-container [data-site='Manhattan_Bridge'] .js-plotly-plot",
            "#chart-its-container .js-plotly-plot",
        ]:
            mb = pg.query_selector(sel)
            if mb:
                break
        if mb:
            mb.screenshot(path=str(IMGS / "manhattan_bridge_its.png"))
            print("    captured manhattan_bridge_its.png")
        else:
            shot("#chart-its-container", "manhattan_bridge_its.png")

        # Section 4: equity scatter
        try:
            pg.wait_for_selector("#chart-equity-container .loading",
                                  state="hidden", timeout=10000)
        except Exception:
            pass
        pg.wait_for_timeout(1000)
        shot("#chart-equity-container", "equity_scatter.png")

        # Check 7: matched-day DiD table
        try:
            pg.wait_for_selector("#check7-table-wrap .loading",
                                  state="hidden", timeout=10000)
        except Exception:
            pass
        pg.wait_for_timeout(800)
        shot("#check7-table-wrap", "check7_table.png",
             fallback="[id='check7-table-wrap']")

        # Check 9: PurpleAir sensor table
        try:
            pg.wait_for_selector("#check9-wrap .loading",
                                  state="hidden", timeout=10000)
        except Exception:
            pass
        pg.wait_for_timeout(800)
        shot("#check9-wrap", "check9_table.png")

        br.close()
    print("  Screenshots done.")


# ── darken image for title slide ─────────────────────────────────────────────
def dark_bg(src, dst, brightness=0.30):
    from PIL import Image, ImageEnhance
    im = Image.open(src).convert("RGB")
    im = ImageEnhance.Brightness(im).enhance(brightness)
    # also desaturate slightly
    im = ImageEnhance.Color(im).enhance(0.6)
    im.save(dst)


# ── slide builders ────────────────────────────────────────────────────────────

def s01_title(prs):
    sl = blank(prs)
    bg_src = DOCS / "img" / "major-deegan-willis-ave.jpg"
    bg_dst = IMGS / "title_bg.jpg"
    if bg_src.exists():
        dark_bg(bg_src, bg_dst)
        img(sl, bg_dst, 0, 0, W, H)

    # Left purple bar
    rect(sl, 0, 0, Inches(0.22), H, fill=PURPLE)

    txt(sl, "THE TOLL\nIT TAKES",
        Inches(0.42), Inches(0.8), Inches(10), Inches(4.0),
        size=100, bold=True, color=WHITE, font="Arial Narrow")

    txt(sl,
        "Congestion pricing cleaned the air where it charges.\n"
        "What about everyone else?",
        Inches(0.42), Inches(5.05), Inches(11.5), Inches(1.1),
        size=22, italic=True,
        color=RGBColor(0xCC, 0xC8, 0xE8))

    txt(sl, "Furkan Beray  ·  NYC Congestion Pricing Datathon 2026",
        Inches(0.42), Inches(6.55), Inches(11), Inches(0.55),
        size=14, color=RGBColor(0xAA, 0xA5, 0xC5))

    notes(sl,
        "Opening. The Deegan photo sets the scene: Mott Haven, 44 m from the highway, "
        "6 km outside the toll zone. The question the deck answers is on this slide.")


def s02_question(prs):
    sl = blank(prs)
    top_bar(sl)
    kicker(sl, "THE QUESTION")
    heading(sl, "Is congestion pricing eliminating pollution, or moving it?")

    txt(sl,
        "“Is congestion pricing eliminating pollution, or moving it? "
        "And if moving, toward neighborhoods already most vulnerable?”",
        MARGIN_L, Inches(1.42), CONTENT_W, Inches(2.0),
        size=26, color=INK, font="Arial", wrap=True)

    rule(sl, Inches(3.5))

    # two claim boxes
    cw = (CONTENT_W - Inches(0.35)) / 2

    # left — Cornell
    rect(sl, MARGIN_L, Inches(3.65), cw, Inches(2.7), fill=TOLL_SOFT)
    txt(sl, "−22%  PM₂.₅ daily max\ninside the zone",
        MARGIN_L + Inches(0.18), Inches(3.8), cw - Inches(0.28), Inches(1.15),
        size=30, bold=True, color=GREEN, font="Arial")
    txt(sl, "Cornell / MTA headline: significant reduction in peak PM₂.₅ "
        "inside the Congestion Relief Zone after January 5, 2025.",
        MARGIN_L + Inches(0.18), Inches(4.9), cw - Inches(0.28), Inches(1.3),
        size=12, color=INK)

    # right — SBU
    r2 = MARGIN_L + cw + Inches(0.35)
    rect(sl, r2, Inches(3.65), cw, Inches(2.7), fill=WORSE_SOFT)
    txt(sl, "Increases near\nBronx expressways",
        r2 + Inches(0.18), Inches(3.8), cw - Inches(0.28), Inches(1.15),
        size=30, bold=True, color=BRICK, font="Arial")
    txt(sl, "South Bronx Unite community sensors: PM₂.₅ rising at "
        "12–14 of 19 sensors, avg +0.22 µg/m³, up to +1.29 near expressways.",
        r2 + Inches(0.18), Inches(4.9), cw - Inches(0.28), Inches(1.3),
        size=12, color=INK)

    txt(sl, "We tested both.",
        MARGIN_L, Inches(6.42), CONTENT_W, Inches(0.45),
        size=15, bold=True, color=PURPLE, font="Arial")

    notes(sl,
        "Two credible claims in tension. Cornell/MTA documented a ~22% reduction in PM2.5 "
        "daily maximum inside the CRZ. South Bronx Unite documented increases at expressway-adjacent "
        "sensors in the same period. We tested both using interrupted time series with HAC standard "
        "errors, 11 NYCCAS monitors, 2019–2026, with MTA bridge/tunnel crossings as the mechanism check.")


def s03_data(prs):
    sl = blank(prs)
    top_bar(sl)
    kicker(sl, "THE DATA")
    heading(sl, "11 monitors  ·  2 controls  ·  2019–2026  ·  plus MTA crossings")

    img(sl, IMGS / "map_section1.png",
        MARGIN_L, Inches(1.42), w=CONTENT_W, h=Inches(5.3))

    caption(sl,
        "Figure 1. ITS step-changes after the toll (ITS β_post) at 5 treatment sites. "
        "Green = improved. Brick = worsened. DAC-designated tracts shaded. CRZ boundary in purple. "
        "Controls: Queens College + Van Wyck (not shown). Source: NYCCAS hourly PM₂.₅ 2019–2026; "
        "MTA CRZ entries 2025–2026; NYS DAC tracts.",
        y=Inches(6.9))

    notes(sl,
        "11 monitors total; 5 treatment sites: Cross Bronx Expy, Mott Haven (both outside CRZ, "
        "both DAC-designated), Manhattan Bridge, Williamsburg Bridge, Queensboro Bridge "
        "(inside or on CRZ boundary). Plus Broadway 35th St, FDR, Hamilton Bridge, BQE, "
        "SI Expwy, Midtown DOT in the full panel. Controls: Queens College and Van Wyck. "
        "Hunts Point excluded: offline Sept 2023–Mar 2025, zero pre-toll observations "
        "at the VW-window start date — no valid step-change can be estimated.")


def s04_finding1(prs):
    sl = blank(prs)
    top_bar(sl, GREEN)
    kicker(sl, "FINDING 1 — INSIDE THE ZONE", color=GREEN)
    heading(sl, "Inside the zone, it worked.", color=INK)

    txt(sl, "−1.33 µg/m³",
        MARGIN_L, Inches(1.42), Inches(6.5), Inches(1.25),
        size=80, bold=True, color=GREEN, font="Arial")

    txt(sl, "p = 0.03  ·  Manhattan Bridge  ·  significant in every specification tested",
        MARGIN_L, Inches(2.6), Inches(11), Inches(0.42),
        size=13, italic=True, color=INK)

    img(sl, IMGS / "manhattan_bridge_its.png",
        MARGIN_L, Inches(3.08), w=CONTENT_W, h=Inches(3.65))

    caption(sl,
        "Section 2: Observed vs. counterfactual monthly mean PM₂.₅, Manhattan Bridge. "
        "Purple vertical line: toll launch Jan 5, 2025. "
        "Counterfactual anchored on Queens College + Van Wyck. Source: NYCCAS 2019–2026.",
        y=Inches(6.9))

    notes(sl,
        "Manhattan Bridge: β_post = −1.33 µg/m³ (SE 0.60, p = 0.028, n = 599). "
        "Holds in every spec: weather-adjusted −1.10 (p = 0.020), step-only −0.86 (p = 0.003), "
        "pooled panel same direction. "
        "Williamsburg Bridge similar: β = −1.04, p = 0.026 (model-dependent in step-only spec, p = 0.065). "
        "Both monitors ~800 m inside the CRZ on Manhattan landings of the East River bridges.")


def s05_finding2(prs):
    sl = blank(prs)
    top_bar(sl, BRICK)
    kicker(sl, "FINDING 2 — OUTSIDE THE ZONE", color=BRICK)
    heading(sl, "Outside the zone, nothing changed.", color=INK)

    img(sl, IMGS / "check7_table.png",
        MARGIN_L, Inches(1.42), w=CONTENT_W, h=Inches(4.85))

    txt(sl,
        "East River bridges → improved.  "
        "South Bronx, Brooklyn, East Harlem → flat.",
        MARGIN_L, Inches(6.35), CONTENT_W, Inches(0.42),
        size=13, bold=True, color=INK)

    caption(sl,
        "Check 7: Matched day-of-year DiD — site minus Van Wyck, 2025 vs. 2024. "
        "Bridges negative; every outside-zone site positive and similar. "
        "PurpleAir: EPA-corrected Barkjohn 2021. Source: NYCCAS + PurpleAir 2024–2026.",
        y=Inches(6.88))

    notes(sl,
        "Matched day-of-year DiD (Check 7): Van Wyck fell 0.48 µg/m³ vs. 2024; "
        "QC fell 0.24 µg/m³. After removing the VW trend: "
        "Manhattan −0.60, Williamsburg −0.81, Queensboro −0.14. "
        "Bronx: Cross Bronx +0.97, Mott Haven +0.87. "
        "PurpleAir: Bay Ridge +0.85, Brooklyn Heights +1.26, East Harlem +1.19. "
        "Bay Ridge and Brooklyn Heights look exactly like the Bronx — "
        "the organizing variable is inside vs. outside the zone, not borough or EJ status.")


def s06_robustness(prs):
    sl = blank(prs)
    top_bar(sl)
    kicker(sl, "ROBUSTNESS")
    heading(sl, "Did we look hard enough?")

    # Table: plain two-column, styled like site ITS table
    checks = [
        # (num, description, verdict, highlight)
        ("1", "Weather adjustment",                   "Robust",                      False),
        ("2", "Peak / overnight differencing",        "One hint",                    True),
        ("3", "Placebo-in-time",                      "Inconclusive",                False),
        ("4", "Pooled panel (site + date FE)",        "Same direction, not sig.",     False),
        ("5", "Mechanism check (Throgs Neck slope)",  "Bounded",                     True),
        ("6", "Bronx NO₂ (EPA AQS 2022–2025)", "No change",              False),
        ("7", "Matched-day DiD",                      "Consistent",                  False),
        ("8", "Step-only ITS",                        "Mixed",                       False),
        ("9", "Outside-zone PurpleAir sensors",       "No EJ gap",                   False),
    ]

    ROW_H = Inches(0.465)
    HDR_T = Inches(1.47)
    C1    = MARGIN_L
    C2    = MARGIN_L + Inches(7.2)
    CW1   = Inches(7.1)
    CW2   = CONTENT_W - Inches(7.2)

    # header
    rect(sl, C1, HDR_T, CONTENT_W, ROW_H, fill=INK)
    txt(sl, "Check", C1 + Inches(0.1), HDR_T + Pt(5), Inches(0.55), ROW_H,
        size=10, bold=True, color=WHITE)
    txt(sl, "Description", C1 + Inches(0.72), HDR_T + Pt(5), Inches(6.2), ROW_H,
        size=10, bold=True, color=WHITE)
    txt(sl, "Verdict", C2 + Inches(0.1), HDR_T + Pt(5), CW2 - Inches(0.15), ROW_H,
        size=10, bold=True, color=WHITE)

    for i, (num, desc, verdict, hi) in enumerate(checks):
        t  = HDR_T + ROW_H * (i + 1)
        bg = TOLL_SOFT if hi else (HAZE if i % 2 == 0 else WHITE)
        rect(sl, C1, t, CONTENT_W, ROW_H, fill=bg)
        # thin bottom rule
        rect(sl, C1, t + ROW_H - Pt(0.5), CONTENT_W, Pt(0.5), fill=RULE_C)

        vc = PURPLE if hi else INK
        txt(sl, num,    C1 + Inches(0.1),  t + Pt(5), Inches(0.55), ROW_H,
            size=11, bold=hi, color=vc)
        txt(sl, desc,   C1 + Inches(0.72), t + Pt(5), Inches(6.2),  ROW_H,
            size=11, bold=hi, color=vc)
        txt(sl, verdict, C2 + Inches(0.1),  t + Pt(5), CW2 - Inches(0.15), ROW_H,
            size=11, bold=hi, color=vc)

    notes(sl,
        "Nine robustness checks. Two highlighted:\n"
        "Check 2 (peak/overnight): Cross Bronx weekday-only β = +0.90 (p = 0.04). "
        "One significant result among 22 tests — a hint, consistent with the Throgs Neck diversion route.\n"
        "Check 5 (mechanism): Throgs Neck slope +0.018 µg/m³ per 1k veh × +2,041 veh/day "
        "residual = +0.04 µg/m³ implied — about 1/8 of the observed +0.30 at Mott Haven.\n"
        "Check 3 (placebo): SD of placebo distributions 7–17 µg/m³; "
        "observed effects of 1–3 µg/m³ are not exceptional against that baseline.\n"
        "Check 8 (step-only): Mott Haven sign reverses (full +0.30, step-only −0.65); "
        "Williamsburg model-dependent (p = 0.026 full, p = 0.065 step-only).")


def s07_ej(prs):
    sl = blank(prs)
    top_bar(sl)
    kicker(sl, "FINDING 3 — EQUITY")
    heading(sl, "EJ can’t be separated from the zone.")

    txt(sl, "β_EJ  −0.38 to +0.02 µg/m³",
        MARGIN_L, Inches(1.42), Inches(9.5), Inches(1.15),
        size=58, bold=True, color=INK, font="Arial")

    txt(sl, "None significant  (p = 0.65–0.96)  across all three EJ-flag definitions",
        MARGIN_L, Inches(2.52), Inches(11), Inches(0.42),
        size=13, italic=True, color=INK)

    img(sl, IMGS / "equity_scatter.png",
        MARGIN_L, Inches(3.0), w=CONTENT_W, h=Inches(3.75))

    caption(sl,
        "Section 4: β_post by EJ status and zone membership. No fitted line. "
        "EJ flag: NYS DAC point-in-polygon. Panel: 11 sites, site + date FE, wild-cluster bootstrap. "
        "Source: ITS results × DAC spatial join. NYCCAS 2019–2026.",
        y=Inches(6.9))

    notes(sl,
        "Every in-zone monitor except Queensboro sits in a DAC-designated tract. "
        "Every outside-zone monitor with a full pre-toll record is also in a DAC tract. "
        "The missing cell (outside-zone, non-EJ) was filled with PurpleAir (Check 9): "
        "Bay Ridge, Brooklyn Heights, East Harlem — they moved the same as the Bronx. "
        "Panel EJ estimates: B1 −0.07 (p=0.77), B2 −0.38 (p=0.65), B3 +0.02 (p=0.96). "
        "Geography explains everything. Inside the zone improved; outside did not — EJ or not.")


def s08_reconcile(prs):
    sl = blank(prs)
    top_bar(sl)
    kicker(sl, "RECONCILING WITH SOUTH BRONX UNITE")
    heading(sl, "Same data. Different counterfactual.")

    cw = (CONTENT_W - Inches(0.4)) / 2
    c1 = MARGIN_L
    c2 = MARGIN_L + cw + Inches(0.4)

    # column headers
    rect(sl, c1, Inches(1.55), cw, Inches(0.44), fill=BRICK)
    txt(sl, "South Bronx Unite (raw)",
        c1 + Inches(0.12), Inches(1.58), cw - Inches(0.2), Inches(0.44),
        size=12, bold=True, color=WHITE)

    rect(sl, c2, Inches(1.55), cw, Inches(0.44), fill=GREEN)
    txt(sl, "This study (control-adjusted)",
        c2 + Inches(0.12), Inches(1.58), cw - Inches(0.2), Inches(0.44),
        size=12, bold=True, color=WHITE)

    sbu = [
        ("Sensors showing increase",   "12–14 of 19"),
        ("Average year-over-year",      "+0.22 µg/m³"),
        ("Near expressways (max)",      "+1.29 µg/m³"),
        ("Counterfactual",              "Raw 2024 → 2025"),
    ]
    ours = [
        ("Mott Haven raw 2025 vs 2024",       "+0.08 µg/m³"),
        ("Mott Haven ITS β_post",         "+0.30 (p = 0.61)"),
        ("Cross Bronx peak-hour (wkday) ★", "+0.90 (p = 0.04)"),
        ("Counterfactual",                      "QC + Van Wyck trend"),
    ]

    row_h = Inches(0.55)
    for i, ((l1, v1), (l2, v2)) in enumerate(zip(sbu, ours)):
        t  = Inches(1.99) + row_h * i
        bg = HAZE if i % 2 == 0 else WHITE
        rect(sl, c1, t, cw, row_h, fill=bg)
        rect(sl, c2, t, cw, row_h, fill=bg)
        txt(sl, l1, c1 + Inches(0.1), t + Pt(5), cw * 0.55, row_h, size=11, color=INK)
        txt(sl, v1, c1 + cw * 0.55, t + Pt(5), cw * 0.43, row_h,
            size=11, bold=bool(v1 and "+" in v1), color=BRICK if (v1 and "+" in v1) else INK,
            align=PP_ALIGN.RIGHT)
        txt(sl, l2, c2 + Inches(0.1), t + Pt(5), cw * 0.6,  row_h, size=11, color=INK)
        txt(sl, v2, c2 + cw * 0.6, t + Pt(5), cw * 0.38, row_h,
            size=11, bold=False, color=PURPLE, align=PP_ALIGN.RIGHT)

    rule(sl, Inches(4.26))

    txt(sl,
        "South Bronx Unite’s increases are real. Our control-adjusted estimates show the same "
        "underlying signal — but the regional PM₂.₅ trend moved every outside-zone site "
        "identically, regardless of borough or EJ status.",
        MARGIN_L, Inches(4.35), CONTENT_W, Inches(0.88),
        size=14, color=INK)

    caption(sl,
        "Check 2 (peak-hour ITS) and Check 7 (matched-day DiD). "
        "★ = one significant result among 22 peak/overnight tests.",
        y=Inches(6.9))

    notes(sl,
        "South Bronx Unite documented real increases. So did we in the raw numbers. "
        "The difference is the counterfactual: when we subtract a control monitor, "
        "Bay Ridge, Brooklyn Heights, and East Harlem show the same upward shift as the Bronx. "
        "That points to a regional PM2.5 background trend, not a toll-specific Bronx effect. "
        "Our Cross Bronx peak-hour hint (p=0.04) agrees with SBU's expressway sensors — "
        "one result among 22 tests.")


def s09_boulevard(prs):
    sl = blank(prs)
    top_bar(sl, INK)
    kicker(sl, "SO WHAT REACHES THE BRONX?", color=MUTED)
    heading(sl, "The leverage is in the boulevard, not the toll.")

    # Three big-number facts
    facts = [
        ("44 m",  "from the Major Deegan\nto the Mott Haven monitor"),
        ("6 km",  "from Mott Haven\nto the nearest CRZ toll point"),
        ("9",     "school entries within\n400 m of the monitor"),
    ]
    fw = CONTENT_W / 3
    for i, (num, desc) in enumerate(facts):
        l = MARGIN_L + fw * i
        txt(sl, num,
            l, Inches(1.48), fw, Inches(1.05),
            size=64, bold=True, color=PURPLE, font="Arial", align=PP_ALIGN.CENTER)
        txt(sl, desc,
            l + Inches(0.1), Inches(2.48), fw - Inches(0.2), Inches(0.72),
            size=12, color=INK, align=PP_ALIGN.CENTER)

    rule(sl, Inches(3.28))

    txt(sl, "Traffic → PM₂.₅ at Mott Haven  (back-of-envelope, honest about it)",
        MARGIN_L, Inches(3.36), CONTENT_W, Inches(0.42),
        size=13, bold=True, color=INK)

    rows = [
        ("Current traffic contribution at this monitor",     "~1–2 µg/m³",  INK),
        ("Effect of halving corridor traffic",               "~0.5–1 µg/m³ reduction", GREEN),
        ("Largest toll effect measured outside the zone",    "~0 (statistically null)",    BRICK),
    ]
    rh = Inches(0.6)
    for i, (label, val, vc) in enumerate(rows):
        t  = Inches(3.82) + rh * i
        bg = HAZE if i % 2 == 0 else WHITE
        rect(sl, MARGIN_L, t, CONTENT_W, rh, fill=bg)
        txt(sl, label,
            MARGIN_L + Inches(0.1), t + Pt(6), Inches(8.5), rh, size=12, color=INK)
        txt(sl, val,
            W - MARGIN_L - Inches(3.6), t + Pt(6), Inches(3.5), rh,
            size=12, bold=True, color=vc, align=PP_ALIGN.RIGHT)

    caption(sl,
        "Mechanism slope: +0.018 µg/m³ per 1,000 veh/day at Throgs Neck (p=0.27, 2022–2024). "
        "Halving estimate is back-of-envelope. Schools: NYC DOE geocoded within 400 m of monitor.",
        y=Inches(6.88))

    notes(sl,
        "The Mott Haven monitor sits 44 m from the Major Deegan Expressway and 6 km outside the CRZ. "
        "Nine school entries are within 400 m (6 physical locations); nearest: P.S. 043 Jonas Bronck at 76 m. "
        "The pre-toll mechanism regression gives a slope of +0.018 µg/m³ per 1,000 veh/day "
        "at Throgs Neck (p=0.27, n=144). Traffic contribution ~1–2 µg/m³. "
        "Halving corridor traffic → ~0.5–1 µg/m³ reduction — "
        "more than any toll effect measured outside the zone. This is a back-of-envelope and "
        "being honest about that is the point.")


def s10_corridor(prs):
    sl = blank(prs)
    top_bar(sl, GREEN)
    kicker(sl, "PART II — THE GREEN CORRIDOR", color=GREEN)
    heading(sl, "What the mitigation money already on the table should buy.")

    txt(sl,
        "Mott Haven  ·  H/W 1.02  ·  existing canopy 4% vs. 22% citywide  "
        "·  canyon discount 13%",
        MARGIN_L, Inches(1.42), CONTENT_W, Inches(0.38),
        size=12, italic=True, color=MUTED)

    # typology table
    typ = ca["typologies"]
    hdrs    = ["Typology", "PM₂.₅ removed (canyon-adj., maturity)", "Stormwater (maturity)", "Trees"]
    col_ls  = [MARGIN_L, MARGIN_L + Inches(4.0), MARGIN_L + Inches(7.2), MARGIN_L + Inches(9.65)]
    col_ws  = [Inches(3.85), Inches(3.1), Inches(2.35), CONTENT_W - Inches(9.65)]
    rh      = Inches(0.56)
    ht      = Inches(1.88)

    rect(sl, MARGIN_L, ht, CONTENT_W, rh, fill=INK)
    for j, (h, cl, cw) in enumerate(zip(hdrs, col_ls, col_ws)):
        txt(sl, h, cl + Inches(0.08), ht + Pt(4), cw - Inches(0.1), rh,
            size=10, bold=True, color=WHITE,
            align=PP_ALIGN.LEFT if j == 0 else PP_ALIGN.RIGHT)

    data_rows = [
        ("Dense street trees (20 ft spacing)",
         f"{typ['dense_street_trees']['removal_adjusted_kg_yr']:,.0f} kg/yr",
         f"{typ['dense_street_trees']['stormwater_kL_yr']:,.0f} kL/yr",
         f"{typ['dense_street_trees']['proposed_trees']:,}"),
        ("Spaced street trees (40 ft spacing)",
         f"{typ['spaced_street_trees']['removal_adjusted_kg_yr']:,.0f} kg/yr",
         f"{typ['spaced_street_trees']['stormwater_kL_yr']:,.0f} kL/yr",
         f"{typ['spaced_street_trees']['proposed_trees']:,}"),
        ("Green wall (south-facing, 2 m height)",
         f"{typ['green_wall']['removal_adjusted_kg_yr']:.1f} kg/yr",
         "not est.", "n/a"),
    ]

    for i, row in enumerate(data_rows):
        t  = ht + rh * (i + 1)
        bg = HAZE if i % 2 == 0 else WHITE
        rect(sl, MARGIN_L, t, CONTENT_W, rh, fill=bg)
        for j, (cell, cl, cw) in enumerate(zip(row, col_ls, col_ws)):
            hi = (j == 1 and i == 0)
            txt(sl, cell, cl + Inches(0.08), t + Pt(6), cw - Inches(0.1), rh,
                size=12, bold=(j > 0),
                color=GREEN if hi else INK,
                align=PP_ALIGN.LEFT if j == 0 else PP_ALIGN.RIGHT)

    rule(sl, Inches(4.65))

    txt(sl,
        "Dense canopy in a street canyon traps more particulates than open canopy "
        "— hence the 13% discount. Year-1 removal is 10% of maturity; year-20 is 90%.",
        MARGIN_L, Inches(4.73), CONTENT_W, Inches(0.65),
        size=12, color=INK)

    txt(sl,
        "Best typology at maturity: 6,030 kg PM₂.₅/yr  ·  80,573 kL stormwater/yr",
        MARGIN_L, Inches(5.42), CONTENT_W, Inches(0.52),
        size=20, bold=True, color=GREEN, font="Arial")

    caption(sl,
        "PM₂.₅ removal: Nowak et al. 2006/2018; DBH scaling Hirabayashi 2012. "
        "Canyon discount: Li et al. 2019 LES (H/W ramp 0.5–2.5, max 60%). "
        "Stormwater: Peper et al. 2007 (i-Tree Streets / USDA). "
        "Street-tree census: NYC Parks 2015.",
        y=Inches(6.88))

    notes(sl,
        "H/W 1.02 means building height ≈ street width — a deep urban canyon. "
        "25 trees/mile existing vs. 142 citywide. Canyon discount 13% because continuous "
        "canopy reduces vertical ventilation in a deep canyon, limiting dry deposition. "
        "Dense typology (14,864 trees at 20-ft spacing): 6,030 kg/yr canyon-adjusted PM2.5, "
        "80,573 kL/yr stormwater. Year-1 = 10% of maturity; year-10 = 55%; year-20 = 90%. "
        "Species: Thornless Honeylocust (primary), Swamp White Oak, Lacebark Elm, Ginkgo (male cultivar only). "
        "The mitigation funding from congestion pricing revenues should prioritise this corridor.")


def s11_claim(prs):
    sl = blank(prs)
    top_bar(sl)
    kicker(sl, "THE CLAIM")

    txt(sl,
        "“Congestion pricing is eliminating pollution, not moving it — "
        "but only inside the zone. Outside, air quality is unchanged everywhere we can "
        "measure, and the most burdened neighborhoods are exactly where they were.”",
        MARGIN_L, Inches(0.9), CONTENT_W, Inches(3.8),
        size=28, color=INK, font="Arial", wrap=True)

    rule(sl, Inches(4.85))

    txt(sl, "furkanberatay.github.io/The_Toll_it_Takes_Project/",
        MARGIN_L, Inches(5.0), CONTENT_W / 2, Inches(0.42),
        size=13, color=PURPLE)
    txt(sl, "github.com/furkanberatay/The_Toll_it_Takes_Project",
        MARGIN_L + CONTENT_W / 2, Inches(5.0), CONTENT_W / 2, Inches(0.42),
        size=13, color=PURPLE, align=PP_ALIGN.RIGHT)

    rule(sl, Inches(5.52), color=RULE_C)

    # three summary numbers
    nums = [
        ("−1.33 µg/m³", "Manhattan Bridge (p = 0.03)", GREEN),
        ("+0.30 µg/m³",  "Mott Haven (p = 0.61, n.s.)",    BRICK),
        ("−0.38 to +0.02",   "EJ gap (none significant)",                  INK),
    ]
    nw = CONTENT_W / 3
    for i, (num, lbl, col) in enumerate(nums):
        l = MARGIN_L + nw * i
        txt(sl, num,
            l, Inches(5.62), nw, Inches(0.62),
            size=26, bold=True, color=col, font="Arial", align=PP_ALIGN.CENTER)
        txt(sl, lbl,
            l, Inches(6.22), nw, Inches(0.38),
            size=10, color=MUTED, align=PP_ALIGN.CENTER)

    notes(sl,
        "The one-sentence takeaway. Congestion pricing is doing exactly what it was designed "
        "to do inside the zone. It is not moving the pollution. But it is also not reaching "
        "outside the zone. The EJ question dissolves into the geography question: zone membership "
        "and EJ status are nearly collinear in this monitoring network. "
        "The policy implication: inside the zone, celebrate the win. "
        "Outside, the leverage is in the corridor — the boulevard, the trees, the schools.")


def s12_appendix(prs):
    sl = blank(prs)
    top_bar(sl, HAZE)
    kicker(sl, "APPENDIX — not presented", color=MUTED)
    heading(sl, "ITS full results  ·  Check 9 sensor QC  ·  Limitations", size=20)

    img(sl, IMGS / "check9_table.png",
        MARGIN_L, Inches(1.48), w=CONTENT_W, h=Inches(3.5))

    rule(sl, Inches(5.08))

    txt(sl, "Limitations", MARGIN_L, Inches(5.16), CONTENT_W, Inches(0.38),
        size=13, bold=True, color=INK)

    lims = [
        "Control drift: Van Wyck trend differs from QC by ~0.2 µg/m³ — "
        "choice of control shifts outside-zone estimates.",
        "PurpleAir coverage: three primary-set sensors (Bay Ridge, Brooklyn Heights, "
        "East Harlem); none in the Bronx outside NYCCAS.",
        "Nine pre-toll months at Mott Haven in the VW window "
        "(monitor online Apr 2024, nine months before the toll).",
    ]
    for i, lim in enumerate(lims):
        txt(sl, f"•  {lim}",
            MARGIN_L, Inches(5.56) + Inches(0.3) * i, CONTENT_W, Inches(0.28),
            size=11, color=INK)

    notes(sl,
        "ITS full table: all 11 sites, both specs (full and long-baseline), "
        "β_post, SE, p, 95% CI. "
        "Check 9 sensor QC: 12 PurpleAir candidates; 3 passed coverage gate for primary set "
        "(89th & Ridge Ave / Bay Ridge, RGBIV / Brooklyn Heights, FA_O5 / East Harlem). "
        "Key limitation: nine pre-toll months at Mott Haven in the VW window; "
        "long-baseline QC-only spec uses 2019 data but is exposed to COVID distortions.")


# ── contact sheet ─────────────────────────────────────────────────────────────
def make_contact_sheet():
    from PIL import Image, ImageDraw, ImageFont

    CELL_W, CELL_H = 480, 270
    COLS, ROWS     = 4, 3
    PAD            = 10
    LBL_H          = 22
    BG             = (240, 241, 239)

    tw = COLS * CELL_W + (COLS + 1) * PAD
    th = ROWS * (CELL_H + LBL_H) + (ROWS + 1) * PAD
    sheet = Image.new("RGB", (tw, th), BG)
    draw  = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/Arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    labels = [
        "1. Title", "2. The Question", "3. The Data",
        "4. Finding 1 — Inside", "5. Finding 2 — Outside", "6. Robustness",
        "7. Finding 3 — EJ", "8. Reconcile SBU", "9. Boulevard",
        "10. Green Corridor", "11. The Claim", "12. Appendix",
    ]
    accents = [
        (75,46,131),(75,46,131),(75,46,131),
        (47,107,58),(180,57,27),(75,46,131),
        (75,46,131),(75,46,131),(42,45,43),
        (47,107,58),(75,46,131),(216,219,216),
    ]
    bgs = [
        (10,6,20),(255,255,255),(255,255,255),
        (255,255,255),(255,255,255),(255,255,255),
        (255,255,255),(255,255,255),(255,255,255),
        (255,255,255),(255,255,255),(250,251,249),
    ]
    slide_imgs = {
        0: IMGS / "title_bg.jpg",
        2: IMGS / "map_section1.png",
        3: IMGS / "manhattan_bridge_its.png",
        4: IMGS / "check7_table.png",
        6: IMGS / "equity_scatter.png",
        8: IMGS / "corridor_strip.png",
        11: IMGS / "check9_table.png",
    }

    for idx in range(12):
        col = idx % COLS
        row = idx // COLS
        x   = PAD + col * (CELL_W + PAD)
        y   = PAD + row * (CELL_H + LBL_H + PAD)

        cell = Image.new("RGB", (CELL_W, CELL_H), bgs[idx])
        # accent bar
        bar = Image.new("RGB", (CELL_W, 7), accents[idx])
        cell.paste(bar, (0, 0))

        # thumbnail
        if idx in slide_imgs and slide_imgs[idx].exists():
            try:
                thumb = Image.open(slide_imgs[idx]).convert("RGB")
                thumb.thumbnail((CELL_W - 4, CELL_H - 32))
                px = (CELL_W - thumb.width) // 2
                py = 14 + (CELL_H - 14 - thumb.height) // 2
                cell.paste(thumb, (px, py))
            except Exception:
                pass

        sheet.paste(cell, (x, y))
        draw.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1],
                       outline=(180, 180, 180), width=1)

        # label strip
        ly = y + CELL_H
        draw.rectangle([x, ly, x + CELL_W - 1, ly + LBL_H - 1],
                       fill=(230, 231, 229))
        draw.text((x + 6, ly + 4), labels[idx], fill=(42, 45, 43), font=font)

    sheet.save(str(CONTACT))
    print(f"  Contact sheet: {CONTACT}")


# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Step 1: Capturing screenshots via Playwright…")
    try:
        capture()
    except Exception as e:
        print(f"  Screenshot error: {e}")
        import traceback; traceback.print_exc()

    print("Step 2: Building PPTX…")
    prs = new_prs()
    s01_title(prs)
    s02_question(prs)
    s03_data(prs)
    s04_finding1(prs)
    s05_finding2(prs)
    s06_robustness(prs)
    s07_ej(prs)
    s08_reconcile(prs)
    s09_boulevard(prs)
    s10_corridor(prs)
    s11_claim(prs)
    s12_appendix(prs)
    prs.save(str(PPTX_OUT))
    print(f"  PPTX: {PPTX_OUT}")

    print("Step 3: Contact sheet…")
    make_contact_sheet()
    print("Done.")
