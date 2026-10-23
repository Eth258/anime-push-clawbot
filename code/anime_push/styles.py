#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五种排版风格样张生成器

用同一份数据渲染 5 张不同设计语言的卡片, 供挑选。
输出 /tmp/style_1.png ... style_5.png
"""
import os
import sys
import json
import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_MED = FONT_REG

W = 880


SC_INDEX = 2  # .ttc 集合中第 2 个面为简体中文, 避免落到日文字形


def _font(path, size):
    """按 SC 面加载, 失败则回退默认面"""
    try:
        ft = ImageFont.truetype(path, size, index=SC_INDEX)
        if "SC" in ft.getname()[0]:
            return ft
    except Exception:
        pass
    try:
        return ImageFont.truetype(path, size, index=SC_INDEX)
    except Exception:
        return ImageFont.truetype(path, size)


def f(size, bold=True, med=False):
    p = FONT_BOLD if bold else (FONT_MED if med else FONT_REG)
    return _font(p, size)


def tw(d, s, font):
    b = d.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


def ell(d, s, font, max_w):
    if tw(d, s, font) <= max_w:
        return s
    while s and tw(d, s + "…", font) > max_w:
        s = s[:-1]
    return s + "…"


def load_cover(bid):
    if not bid:
        return None
    p = os.path.join(HERE, "covers", "%s.jpg" % bid)
    if os.path.exists(p):
        try:
            return Image.open(p).convert("RGB")
        except Exception:
            return None
    return None


def cover_sq(cover, size, radius=0, zoom=1.0):
    """居中裁切为正方形, 3x 超采样"""
    target = size * 3
    im = cover.copy()
    w, h = im.size
    scale = target / min(w, h) / zoom
    im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    side = min(im.size)
    left = (im.width - side) // 2
    top = (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    if radius:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=radius, fill=255)
        out = Image.new("RGB", (size, size), (30, 32, 40))
        out.paste(im, (0, 0), mask)
        return out, mask
    return im, None


def vgrad(size, top, bot):
    w, h = size
    img = Image.new("RGB", (1, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.point((0, y), fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img.resize((w, h))


def wrap_time(it):
    t = it["time"]
    return t


# ---------------------------------------------------------------- 风格 1
def style1(items, date, wd, out):
    """杂志清单 · 米白纸质 + 细分割线 + 大留白"""
    from PIL import Image, ImageDraw
    PAPER = (247, 245, 240)
    INK = (28, 28, 30)
    GREY = (140, 138, 132)
    RED = (196, 62, 45)
    HAIR = (216, 212, 204)

    MARGIN = 56
    row_h = 104
    head = 208
    H = head + row_h * len(items) + 78

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # ---- 报头 ----
    d.text((MARGIN, 52), "ANIME  SCHEDULE", font=f(12, False), fill=RED)
    d.text((MARGIN, 72), "今日放送", font=f(50), fill=INK)

    # 右上日期块
    dt = "%s · 周%s" % (date.replace("-", " / "), wd)
    d.text((W - MARGIN - tw(d, dt, f(15, False)), 84), dt, font=f(15, False), fill=GREY)
    cnt = "%02d 部" % len(items)
    d.text((W - MARGIN - tw(d, cnt, f(20)), 104), cnt, font=f(20), fill=RED)

    # 粗细分隔线
    d.rectangle([MARGIN, 158, W - MARGIN, 160], fill=INK)
    d.rectangle([MARGIN, 162, W - MARGIN, 163], fill=HAIR)

    # 表头栏
    d.text((MARGIN, 176), "TIME", font=f(11, False), fill=GREY)
    d.text((MARGIN + 148, 176), "TITLE", font=f(11, False), fill=GREY)
    d.text((W - MARGIN - tw(d, "EP", f(11, False)), 176), "EP", font=f(11, False), fill=GREY)

    y = head
    shown_next = False
    for it in items:
        if it.get("next_day") and not shown_next:
            shown_next = True
            d.text((MARGIN, y - 26), "NEXT DAY", font=f(10, False), fill=RED)
        elif not it.get("next_day") and shown_next:
            pass

        d.line([MARGIN, y, W - MARGIN, y], fill=HAIR, width=1)

        # 时间
        d.text((MARGIN, y + 28), it["time"], font=f(32), fill=INK)

        # 封面
        cx = MARGIN + 148
        cover = load_cover(it.get("bangumi"))
        if cover:
            th, _ = cover_sq(cover, 64, radius=3)
            img.paste(th, (cx, y + 20))

        # 标题
        tx = cx + 82
        name = ell(d, it["title"], f(26), W - MARGIN - tx - 70)
        d.text((tx, y + 34), name, font=f(26), fill=INK)

        # 集数右对齐
        ep = it.get("ep")
        lbl = ("%02d" % ep) if ep else "--"
        d.text((W - MARGIN - tw(d, lbl, f(22)), y + 36), lbl, font=f(22), fill=RED)

        y += row_h

    # 收尾双线
    d.line([MARGIN, y, W - MARGIN, y], fill=HAIR, width=1)
    d.rectangle([MARGIN, y + 4, W - MARGIN, y + 6], fill=INK)

    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------- 风格 2
def style2(items, date, wd, out):
    """影院排片 · 深色 + 大封面 + 时间轴竖线"""
    BG = (13, 14, 18)
    FG = (240, 240, 244)
    DIM = (120, 126, 140)
    GOLD = (226, 178, 92)

    row_h = 128
    head = 190
    H = head + row_h * len(items) + 60

    img = vgrad((W, H), (22, 24, 32), (11, 12, 16))
    d = ImageDraw.Draw(img)

    # 顶部细金线
    d.rectangle([0, 0, W, 3], fill=GOLD)

    d.text((52, 44), "TODAY'S LINEUP", font=f(12, False), fill=GOLD)
    d.text((52, 66), "今日放送", font=f(46), fill=FG)
    info = "%s · 周%s · %d 部" % (date, wd, len(items))
    d.text((52, 132), info, font=f(16, False), fill=DIM)

    y = head
    line_x = 152
    # 时间轴
    d.line([line_x, y - 6, line_x, y + row_h * len(items) - 26], fill=(46, 48, 58), width=2)

    for it in items:
        if it.get("next_day") and items.index(it) and not items[items.index(it) - 1].get("next_day"):
            pass
        # 时间在轴上
        t = it["time"]
        tw_ = tw(d, t, f(24))
        d.text((line_x - tw_ - 22, y + 30), t, font=f(24), fill=GOLD)
        # 轴点
        d.ellipse([line_x - 5, y + 39, line_x + 5, y + 49], fill=GOLD)

        # 封面
        cover = load_cover(it.get("bangumi"))
        cx = line_x + 26
        if cover:
            th, mask = cover_sq(cover, 84, radius=8)
            img.paste(th, (cx, y + 10), mask)

        nx = cx + 84 + 24
        name = ell(d, it["title"], f(27), W - 52 - nx - 20)
        d.text((nx, y + 30), name, font=f(27), fill=FG)
        ep = it.get("ep")
        sub = ("EP.%02d" % ep) if ep else ""
        if it.get("next_day"):
            sub = (sub + "  ·  次日" ).strip()
        if sub:
            d.text((nx, y + 68), sub, font=f(15, False), fill=DIM)
        y += row_h

    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------- 风格 3
def style3(items, date, wd, out):
    """海报墙 · 大封面网格, 2 列"""
    BG = (18, 18, 22)
    FG = (245, 245, 248)
    DIM = (150, 155, 168)
    ACC = (255, 92, 122)

    card_w = (W - 48 * 2 - 24) // 2
    img_h = int(card_w * 1.28)
    rows = (len(items) + 1) // 2
    card_h = img_h + 86
    head = 170
    H = head + rows * (card_h + 24) + 20

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((48, 42), "今日番剧", font=f(44), fill=FG)
    d.text((48, 104), "%s 周%s · %d 部" % (date, wd, len(items)),
           font=f(17, False), fill=DIM)
    d.rectangle([48, 140, 48 + 60, 144], fill=ACC)

    for idx, it in enumerate(items):
        col = idx % 2
        row = idx // 2
        x = 48 + col * (card_w + 24)
        y = head + row * (card_h + 24)

        cover = load_cover(it.get("bangumi"))
        if cover:
            th, mask = cover_sq(cover, card_w, radius=16, zoom=1.0)
            # 拉伸成竖版
            th = th.resize((card_w, img_h), Image.LANCZOS)
            mask = Image.new("L", (card_w, img_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w, img_h], radius=16, fill=255)
            img.paste(th, (x, y), mask)
        else:
            d.rounded_rectangle([x, y, x + card_w, y + img_h], radius=16, fill=(40, 42, 52))

        # 底部渐变遮罩
        ov = vgrad((card_w, 90), (18, 18, 22), (18, 18, 22))
        # 用 alpha 渐变
        alpha = Image.new("L", (card_w, 90))
        ad = ImageDraw.Draw(alpha)
        for yy in range(90):
            ad.line([(0, yy), (card_w, yy)], fill=int(255 * (yy / 89) ** 1.6))
        img.paste(ov, (x, y + img_h - 90), alpha)

        # 集数角标
        ep = it.get("ep")
        if ep:
            badge = "EP.%02d" % ep
            bw = tw(d, badge, f(13)) + 18
            d.rounded_rectangle([x + 12, y + img_h - 34, x + 12 + bw, y + img_h - 10],
                                radius=6, fill=ACC)
            d.text((x + 21, y + img_h - 31), badge, font=f(13), fill=(20, 20, 24))

        # 时间
        d.text((x + 12, y + img_h - 62), it["time"], font=f(20), fill=(255, 255, 255))

        # 标题 (图下)
        name = ell(d, it["title"], f(22), card_w)
        d.text((x, y + img_h + 16), name, font=f(22), fill=FG)
        if it.get("next_day"):
            d.text((x, y + img_h + 50), "次日凌晨", font=f(13, False), fill=ACC)

    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------- 风格 4
def style4(items, date, wd, out):
    """便当盒 · 彩色分区, 每部一张小卡, 紧凑多列"""
    BG = (250, 249, 246)
    INK = (26, 26, 30)
    DIM = (130, 128, 124)
    TILE = (255, 255, 255)

    cols = 2
    gap = 16
    pad = 40
    tile_w = (W - pad * 2 - gap) // 2
    tile_h = 132
    rows = (len(items) + 1) // 2
    head = 168
    H = head + rows * (tile_h + gap) + 30

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((pad, 40), "今日更新", font=f(40), fill=INK)
    d.text((pad, 100), "%s 周%s — 共 %d 部" % (date, wd, len(items)),
           font=f(17, False), fill=DIM)

    for idx, it in enumerate(items):
        col = idx % 2
        row = idx // 2
        x = pad + col * (tile_w + gap)
        y = head + row * (tile_h + gap)

        d.rounded_rectangle([x, y, x + tile_w, y + tile_h], radius=18, fill=TILE,
                            outline=(228, 226, 220), width=2)

        cover = load_cover(it.get("bangumi"))
        if cover:
            th, mask = cover_sq(cover, 88, radius=14)
            img.paste(th, (x + 20, y + 22), mask)

        tx = x + 124
        d.text((tx, y + 26), it["time"], font=f(26), fill=INK)
        ep = it.get("ep")
        if ep:
            d.text((tx, y + 60), "第 %d 集" % ep, font=f(15, False), fill=DIM)
        name = ell(d, it["title"], f(20), tile_w - 140)
        d.text((tx, y + 88), name, font=f(20), fill=INK)

    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------- 风格 5
def style5(items, date, wd, out):
    """极简时间线 · 纯黑 + 大量留白 + 单一强调色"""
    BG = (9, 9, 11)
    FG = (250, 250, 252)
    DIM = (110, 110, 120)
    CYAN = (110, 231, 214)

    row_h = 112
    head = 230
    H = head + row_h * len(items) + 80

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 超大日期做背景
    big = date[8:10]
    fbig = f(230)
    d.text((W - 60 - tw(d, big, fbig), 10), big, font=fbig, fill=(20, 20, 26))

    d.text((60, 60), "今日放送", font=f(38), fill=FG)
    d.text((60, 118), "%s / 周%s" % (date, wd), font=f(16, False), fill=DIM)
    d.text((60, 148), "%d 部" % len(items), font=f(16, False), fill=CYAN)

    y = head
    for it in items:
        if it.get("next_day") and items.index(it) and not items[items.index(it) - 1].get("next_day"):
            d.text((60, y - 26), "NEXT DAY", font=f(11, False), fill=DIM)
            y += 14

        d.text((60, y + 22), it["time"], font=f(30), fill=CYAN)

        nx = 190
        name = ell(d, it["title"], f(26), W - 60 - nx - 100)
        d.text((nx, y + 24), name, font=f(26), fill=FG)

        ep = it.get("ep")
        if ep:
            lbl = "EP %02d" % ep
            d.text((W - 60 - tw(d, lbl, f(14, False)), y + 34), lbl,
                   font=f(14, False), fill=DIM)
        y += row_h

    img.save(out, "PNG", optimize=True)
    return out


def main():
    items = json.load(open("/tmp/items.json"))
    date = "2026-10-22"
    wd = "四"
    outs = []
    for i, fn in enumerate([style1, style2, style3, style4, style5], 1):
        p = "/tmp/style_%d.png" % i
        fn(items, date, wd, p)
        outs.append(p)
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
