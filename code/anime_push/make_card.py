#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""番剧放送表 -> 图片卡片（模板 C：竖版杂志清单）

版式: 米白纸感 / 竖版 2:3 封面 / 单行时间 + 番名 + 集数 / 日报纸式分隔线
用法:
  python3 make_card.py                 # 今天
  python3 make_card.py --day 1         # 明天
  python3 make_card.py -o /tmp/a.png   # 指定输出
  python3 make_card.py --date 2026-10-25
"""
import os
import re
import sys
import json
import datetime
import importlib.util
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
SC_INDEX = 2  # .ttc 中第 2 面为简体中文
COVER_DIR = os.path.join(HERE, "covers")

# ---- 版式常量（模板 C）----
W = 1080
MARGIN = 72
HEAD_H = 280
THUMB_W, THUMB_H = 96, 144
THUMB_RADIUS = 6
ROW_H = 190

PAPER = (247, 245, 240)
INK = (28, 28, 30)
GREY = (140, 138, 132)
RED = (196, 62, 45)
HAIR = (216, 212, 204)


def f(size, bold=True):
    p = FONT_BOLD if bold else FONT_REG
    try:
        ft = ImageFont.truetype(p, size, index=SC_INDEX)
        if "SC" in ft.getname()[0]:
            return ft
    except Exception:
        pass
    try:
        return ImageFont.truetype(p, size, index=SC_INDEX)
    except Exception:
        return ImageFont.truetype(p, size)


def tw(d, s, font):
    b = d.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


def ell(d, s, font, max_w):
    if tw(d, s, font) <= max_w:
        return s
    while s and tw(d, s + "…", font) > max_w:
        s = s[:-1]
    return s + "…"


SUFFIX_PATTERNS = [
    re.compile(r"\s*[～~][^～~]{1,30}[～~]\s*$"),                    # ～副标题～
    re.compile(r"\s*(第[一二三四五六七八九十百0-9]+[季期章篇])\s*$"),   # 第X季/期/章/篇
    re.compile(r"\s*(最终章|最终篇|完结篇|完结章)\s*$"),               # 最终章
    re.compile(r"\s*([^\s～~]{2,10}篇)\s*$"),                        # XXX篇
    re.compile(r"\s*(Season\s*\d+|\d+(?:st|nd|rd|th)\s+Season)\s*$", re.I),
]


def split_season(title):
    """把主标题与季数/篇章后缀拆开, 后缀不进括号"""
    text = (title or "").strip()
    for pat in SUFFIX_PATTERNS:
        m = pat.search(text)
        if m:
            main = text[:m.start()].strip()
            suffix = text[m.start():].strip()
            if main and suffix:
                return main, suffix
    return text, ""


def wrap_text(d, text, font, max_w, max_lines=2):
    """贪心折行, 尽量在标点处断开; 仅当确实超过 max_lines 行才省略"""
    if tw(d, text, font) <= max_w:
        return [text]

    brk = " ／/·・，、！？）」』-–—"
    lines = []
    rest = text
    while rest:
        if tw(d, rest, font) <= max_w:
            lines.append(rest)
            rest = ""
            break
        cur = ""
        for ch in rest:
            if tw(d, cur + ch, font) <= max_w:
                cur += ch
            else:
                break
        if not cur:                       # 单字都放不下
            cur = rest[0]
        # 在已放下的部分里找最后一个标点, 避免把词切断
        cut = -1
        for i in range(len(cur) - 1, max(0, len(cur) - 6), -1):
            if cur[i] in brk and i < len(cur) - 1:
                cut = i + 1
                break
        if cut > 0:
            lines.append(cur[:cut].rstrip())
            rest = cur[cut:].lstrip() + rest[len(cur):]
        else:
            lines.append(cur)
            rest = rest[len(cur):]

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ell(d, lines[-1], font, max_w)
    return lines


def load_cover(bid):
    if not bid:
        return None
    p = os.path.join(COVER_DIR, "%s.jpg" % bid)
    if os.path.exists(p):
        try:
            return Image.open(p).convert("RGB")
        except Exception:
            return None
    return None


def portrait(cover, w, h, radius=THUMB_RADIUS, bias=0.28):
    """竖版 2:3 裁切, 3x 超采样; 保持完整画面比例"""
    im = cover.copy()
    cw, ch = im.size
    target = w / h
    if cw / ch > target:
        nw = int(ch * target)
        left = (cw - nw) // 2
        im = im.crop((left, 0, left + nw, ch))
    else:
        nh = int(cw / target)
        top = max(0, int((ch - nh) * bias))
        im = im.crop((0, top, cw, top + nh))
    im = im.resize((w * 3, h * 3), Image.LANCZOS).resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    out = Image.new("RGB", (w, h), PAPER)
    out.paste(im, (0, 0), mask)
    return out, mask


def _moon(canvas, x, y, s=22, ss=4):
    """实心月牙图标 (超采样后贴图)"""
    e = s * ss
    layer = Image.new("RGBA", (e, e), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([0, 0, e - 1, e - 1], fill=RED + (255,))
    ox = int(e * 0.45)
    oy = int(-e * 0.05)
    ld.ellipse([ox, oy, ox + e - 1, oy + e - 1], fill=(0, 0, 0, 0))
    layer = layer.resize((s, s), Image.LANCZOS)
    canvas.paste(layer, (x, y), layer)


def render(items, date, weekday, out_path):
    f_h1 = f(60)
    f_sub = f(15, False)
    f_date = f(24, False)
    f_wd = f(48)
    f_head = f(17)
    f_time = f(40)
    f_name = f(34)
    f_ep = f(30)
    f_sep = f(17)

    # ---- 视觉基准线 ----
    TIME_W = 190          # 时间列宽
    SEP_H = 64            # 次日分隔带高度
    RULE_Y = 176          # 报头粗线
    HEAD_TOP = 188        # 表头基线
    BODY_TOP = 236        # 列表首行分隔线
    TEXT_DY = 62          # 行内文字相对分隔线的偏移
    LINE_GAP = 46         # 两行标题的行距

    has_sep = any(i.get("next_day") for i in items)
    H = BODY_TOP + ROW_H * len(items) + (SEP_H if has_sep else 0) + 48

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # ---- 报头 ----
    d.text((MARGIN, 46), "ANIME  SCHEDULE", font=f_sub, fill=RED)
    d.text((MARGIN, 72), "今日放送", font=f_h1, fill=INK)

    # 右上: 日期 + 细竖线 + 大号星期
    mm, dd = date[5:7], date[8:10]
    wd_txt = "周" + weekday
    ww = tw(d, wd_txt, f_wd)
    right = W - MARGIN
    d.text((right - ww, 88), wd_txt, font=f_wd, fill=RED)

    dt = "%s / %s" % (mm, dd)
    dx = right - ww - 26 - tw(d, dt, f_date)
    d.text((dx, 112), dt, font=f_date, fill=GREY)

    d.rectangle([right - ww - 14, 96, right - ww - 12, 142], fill=HAIR)

    # 粗细分隔线
    d.rectangle([MARGIN, RULE_Y, W - MARGIN, RULE_Y + 3], fill=INK)
    d.rectangle([MARGIN, RULE_Y + 6, W - MARGIN, RULE_Y + 7], fill=HAIR)

    # ---- 表头栏（与内容列严格对齐）----
    hy = HEAD_TOP
    d.text((MARGIN, hy), "TIME", font=f_head, fill=GREY)
    d.text((MARGIN + TIME_W, hy), "TITLE", font=f_head, fill=GREY)
    d.text((W - MARGIN - tw(d, "EP", f_head), hy), "EP", font=f_head, fill=GREY)

    # ---- 列表 ----
    y = BODY_TOP
    shown_next = False
    for it in items:
        # 次日分隔带（只在切换处出现一次）
        if it.get("next_day") and not shown_next:
            shown_next = True
            band_top = y
            d.line([MARGIN, band_top, W - MARGIN, band_top], fill=INK, width=1)
            _moon(img, MARGIN, band_top + 20)
            d.text((MARGIN + 34, band_top + 21), "NEXT DAY", font=f_sep, fill=RED)
            y = band_top + SEP_H

        d.line([MARGIN, y, W - MARGIN, y], fill=HAIR, width=1)

        # 时间（与番名垂直居中对齐）
        t_h = d.textbbox((0, 0), it["time"], font=f_time)[3]
        d.text((MARGIN, y + TEXT_DY + (f_name.size - t_h) // 2), it["time"],
               font=f_time, fill=INK)

        # 封面
        cx = MARGIN + TIME_W
        cy = y + (ROW_H - THUMB_H) // 2
        cover = load_cover(it.get("bangumi"))
        if cover:
            th, mask = portrait(cover, THUMB_W, THUMB_H)
            img.paste(th, (cx, cy), mask)
        else:
            d.rounded_rectangle([cx, cy, cx + THUMB_W, cy + THUMB_H],
                                radius=THUMB_RADIUS, fill=(232, 229, 222))

        # 标题：「主标题」+ 后缀（同字号；放不下时后缀换行，不省略）
        tx = cx + THUMB_W + 26
        main, suffix = split_season(it["title"])

        bracket_w = tw(d, "「", f_name)
        inner = 0
        total_w = W - MARGIN - tx - 80
        body_x = tx + bracket_w - inner

        # 主标题先排（最多两行，为两侧括号预留）
        main_avail = total_w - (bracket_w - inner) * 2
        main_lines = wrap_text(d, main, f_name, main_avail, max_lines=2)

        # 」之后是否还有位置放后缀
        last_w = tw(d, main_lines[-1], f_name)
        after_bracket = bracket_w - inner
        used = (body_x - tx) + last_w + after_bracket
        remain = total_w - used - 6

        suffix_lines = []
        same_line = True
        if suffix:
            if tw(d, suffix, f_name) <= remain:
                suffix_lines = [suffix]
            else:
                same_line = False
                max_l = 1 if len(main_lines) >= 2 else 2
                suffix_lines = wrap_text(d, suffix, f_name,
                                         total_w - (body_x - tx), max_lines=max_l)

        total_lines = len(main_lines) + (0 if same_line else len(suffix_lines))
        block_h = total_lines * LINE_GAP - (LINE_GAP - f_name.size)
        ty = y + (ROW_H - block_h) // 2

        d.text((tx, ty), "「", font=f_name, fill=INK)
        for i, ln in enumerate(main_lines):
            d.text((body_x, ty + i * LINE_GAP), ln, font=f_name, fill=INK)

        rb_x = body_x + tw(d, main_lines[-1], f_name) - inner
        rb_y = ty + (len(main_lines) - 1) * LINE_GAP
        d.text((rb_x, rb_y), "」", font=f_name, fill=INK)

        if suffix:
            if same_line:
                d.text((rb_x + after_bracket, rb_y), suffix,
                       font=f_name, fill=INK)
            else:
                sy = ty + len(main_lines) * LINE_GAP
                for j, ln in enumerate(suffix_lines):
                    d.text((body_x, sy + j * LINE_GAP), ln,
                           font=f_name, fill=INK)

        # 集数（与标题同基线）
        ep = it.get("ep")
        lbl = ("%02d" % ep) if ep else "?"
        d.text((W - MARGIN - tw(d, lbl, f_ep), ty), lbl, font=f_ep, fill=RED)

        y += ROW_H

    # 收尾
    d.line([MARGIN, y, W - MARGIN, y], fill=HAIR, width=1)
    d.rectangle([MARGIN, y + 6, W - MARGIN, y + 9], fill=INK)

    img.save(out_path, "PNG", optimize=True)
    return out_path


def build(date_obj, out_path=None):
    """生成指定日期的卡片, 返回文件路径; 无番返回 None"""
    m = _load_schedule()
    data = m.load_data()
    items = m.collect(data, date_obj)
    if not items:
        return None

    import episodes as eps
    import covers_fetch
    covers_fetch.ensure_covers(items)          # 缺封面就现下
    for it in items:
        it["ep"] = eps.episode_on(it["bangumi"], date_obj.isoformat()) if it.get("bangumi") else None

    if out_path is None:
        out_path = "/tmp/anime_%s.png" % date_obj.isoformat()
    render(items, date_obj.isoformat(), "一二三四五六日"[date_obj.weekday()], out_path)
    return out_path


def _load_schedule():
    spec = importlib.util.spec_from_file_location(
        "bgm_schedule", os.path.join(HERE, "bgm_schedule.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    args = sys.argv[1:]

    def val(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    m = _load_schedule()
    if val("--date"):
        target = datetime.datetime.strptime(val("--date"), "%Y-%m-%d").date()
    else:
        offset = int(val("--day") or 0)
        now = datetime.datetime.now(m.BJ)
        if now.hour < m.DAY_CUTOFF_HOUR:
            now -= datetime.timedelta(days=1)
        target = (now + datetime.timedelta(days=offset)).date()

    out = val("-o") or "/tmp/anime_%s.png" % target.isoformat()
    path = build(target, out)
    if not path:
        print("当天没有番，跳过")
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
