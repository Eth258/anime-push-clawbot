"""番剧推送卡片渲染：bleed（满幅封面）/ inset（浅色留白）"""
import io
import os

import qrcode
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_BOLD = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
             "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
             "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
FONT_REG = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def _font(paths, size):
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def fetch_image(url, timeout=20):
    """支持远程 URL 与本地文件路径（本地路径用于缓存与离线场景）"""
    if not url:
        return None
    try:
        if os.path.exists(str(url)):
            return Image.open(url).convert("RGB")
    except Exception:
        pass
    try:
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": UA, "Referer": "https://www.bilibili.com/"})
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def _cover_fill(img, w, h):
    src_r, dst_r = img.width / img.height, w / h
    if src_r > dst_r:
        nh, nw = h, int(h * src_r)
    else:
        nw, nh = w, int(w / src_r)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _round_corners(img, r):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1],
                                           radius=r, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if draw.textlength(cur + ch, font=font) > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _text_center(draw, cx, cy, text, font, fill):
    """把文字的「墨迹」精确居中到 (cx, cy)：按 ink bbox 计算，不用 font 行高"""
    b = draw.textbbox((0, 0), text, font=font)
    w, h = b[2] - b[0], b[3] - b[1]
    draw.text((cx - w / 2 - b[0], cy - h / 2 - b[1]), text, font=font, fill=fill)


def _placeholder(w, h, accent):
    ph = Image.new("RGB", (w, h), (30, 22, 48))
    d = ImageDraw.Draw(ph)
    for yy in range(h):
        t = yy / max(h, 1)
        d.line([(0, yy), (w, yy)],
               fill=(int(40 + accent[0] * 0.10 * t),
                     int(26 + accent[1] * 0.06 * t),
                     int(60 + accent[2] * 0.14 * t)))
    return ph


def render_card(title, content, up_name, url, out_path, cover_url=None, avatar_url=None,
                accent=(255, 92, 141), qr_content=None, code_text=None, style="bleed"):
    if style == "inset":
        return _render_inset(title, content, up_name, url, out_path, cover_url,
                             avatar_url, accent, qr_content, code_text)
    return _render_bleed(title, content, up_name, url, out_path, cover_url,
                         avatar_url, accent, qr_content, code_text)


def _render_bleed(title, content, up_name, url, out_path, cover_url, avatar_url,
                  accent, qr_content, code_text):
    W, H = 1000, 1240
    COVER_H = 570
    PAD = 56

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    cover = fetch_image(cover_url) or _placeholder(W, COVER_H, accent)
    cover = _cover_fill(cover, W, COVER_H)
    img.paste(cover, (0, 0))

    # 封面底部向白色渐隐
    fade_h = 180
    mask = Image.new("L", (1, fade_h))
    for i in range(fade_h):
        mask.putpixel((0, i), int(255 * (i / fade_h) ** 1.5))
    mask = mask.resize((W, fade_h))
    img.paste(Image.new("RGB", (W, fade_h), (255, 255, 255)),
              (0, COVER_H - fade_h), mask)

    y = COVER_H + 30

    # 顶部小标签
    f_tag = _font(FONT_BOLD, 22)
    tag = "番剧推送"
    tw = d.textlength(tag, font=f_tag)
    d.rounded_rectangle([PAD, y, PAD + tw + 30, y + 40], radius=20, fill=accent)
    _text_center(d, PAD + 15 + tw / 2, y + 20, tag, f_tag, (255, 255, 255))
    d.text((PAD + tw + 46, y + 9), up_name, font=_font(FONT_REG, 23), fill=(140, 140, 155))
    y += 72

    f_title = _font(FONT_BOLD, 50)
    for line in _wrap(d, title, f_title, W - 2 * PAD)[:2]:
        d.text((PAD, y), line, font=f_title, fill=(18, 18, 28))
        y += 66
    y += 26

    f_body = _font(FONT_REG, 27)
    for line in _wrap(d, content, f_body, W - 2 * PAD)[:3]:
        d.text((PAD, y), line, font=f_body, fill=(88, 88, 104))
        y += 44

    # 分隔线
    y = max(y + 16, H - 300)
    d.line([(PAD, y), (W - PAD, y)], fill=(238, 238, 244), width=2)

    qr_size = 150
    qr = qrcode.make(qr_content or url).resize((qr_size, qr_size))
    qx, qy = W - PAD - qr_size, H - PAD - qr_size
    img.paste(qr.convert("RGB"), (qx, qy))

    if code_text:
        d.text((PAD, qy + 8), code_text.split()[0], font=_font(FONT_BOLD, 40), fill=(24, 24, 36))
        rest = " ".join(code_text.split()[1:])
        if rest:
            d.text((PAD, qy + 62), rest, font=_font(FONT_BOLD, 26), fill=accent)
        d.text((PAD, qy + 100), "相机扫码或复制到 B站搜索", font=_font(FONT_REG, 20), fill=(160, 160, 175))
    else:
        d.text((PAD, qy + 40), "扫码打开 B站", font=_font(FONT_REG, 22), fill=(150, 150, 165))

    out = _round_corners(img, 26)
    out.save(out_path, "PNG", optimize=True)
    return out_path


def _render_inset(title, content, up_name, url, out_path, cover_url, avatar_url,
                  accent, qr_content, code_text):
    W, H = 1000, 1290
    M = 26
    CW = W - 2 * M
    COVER_H = 500

    bg = Image.new("RGB", (W, H), (245, 246, 250))
    d = ImageDraw.Draw(bg)
    for yy in range(H):
        t = yy / H
        d.line([(0, yy), (W, yy)],
               fill=(int(247 - 6 * t), int(247 - 6 * t), int(251 - 3 * t)))

    # 封面 + 柔和阴影
    cover = fetch_image(cover_url) or _placeholder(CW, COVER_H, accent)
    cover = _cover_fill(cover, CW, COVER_H)
    cover = cover.convert("RGBA")
    cmask = Image.new("L", (CW, COVER_H), 0)
    ImageDraw.Draw(cmask).rounded_rectangle([0, 0, CW - 1, COVER_H - 1], radius=24, fill=255)
    cover.putalpha(cmask)

    shadow = Image.new("RGBA", (CW + 40, COVER_H + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([20, 24, CW + 20, COVER_H + 24],
                                             radius=28, fill=(120, 120, 150, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    bg.paste(shadow, (M - 20, M - 16), shadow)
    bg.paste(cover, (M, M), cover)

    # 白色内容卡
    top = M + COVER_H - 30
    card_h = H - top - M
    card = Image.new("RGBA", (CW, card_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 0, CW - 1, card_h - 1], radius=26, fill=(255, 255, 255, 255))
    shadow2 = Image.new("RGBA", (CW + 40, card_h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow2).rounded_rectangle([20, 22, CW + 20, card_h + 22],
                                              radius=28, fill=(120, 120, 150, 60))
    shadow2 = shadow2.filter(ImageFilter.GaussianBlur(12))
    bg.paste(shadow2, (M - 20, top - 14), shadow2)
    bg.paste(card, (M, top), card)

    d2 = ImageDraw.Draw(bg)
    x0 = M + 48
    y = top + 46

    f_tag = _font(FONT_BOLD, 22)
    tag = "番剧推送"
    tw = d2.textlength(tag, font=f_tag)
    d2.rounded_rectangle([x0, y, x0 + tw + 30, y + 40], radius=20, fill=accent)
    _text_center(d2, x0 + 15 + tw / 2, y + 20, tag, f_tag, (255, 255, 255))
    d2.text((x0 + tw + 46, y + 9), up_name, font=_font(FONT_REG, 23), fill=(140, 140, 155))
    y += 74

    f_title = _font(FONT_BOLD, 48)
    for line in _wrap(d2, title, f_title, CW - 96)[:2]:
        d2.text((x0, y), line, font=f_title, fill=(20, 20, 30))
        y += 64
    y += 22

    f_body = _font(FONT_REG, 26)
    for line in _wrap(d2, content, f_body, CW - 96)[:3]:
        d2.text((x0, y), line, font=f_body, fill=(92, 92, 108))
        y += 42

    qr_size = 146
    qr = qrcode.make(qr_content or url).resize((qr_size, qr_size))
    qx = W - M - 48 - qr_size
    qy = H - M - 44 - qr_size
    bg.paste(qr.convert("RGB"), (qx, qy))
    d2.rectangle([qx - 1, qy - 1, qx + qr_size, qy + qr_size], outline=(232, 232, 240))

    if code_text:
        parts = code_text.split()
        d2.text((x0, qy + 4), parts[0], font=_font(FONT_BOLD, 38), fill=(26, 26, 38))
        if len(parts) > 1:
            pw = d2.textlength(parts[0], font=_font(FONT_BOLD, 38))
            d2.text((x0 + pw + 16, qy + 12), parts[1], font=_font(FONT_BOLD, 26), fill=accent)
        d2.text((x0, qy + 58), "相机扫码或复制到 B站搜索", font=_font(FONT_REG, 20), fill=(160, 160, 175))
    else:
        d2.text((x0, qy + 40), "扫码打开 B站", font=_font(FONT_REG, 22), fill=(150, 150, 165))

    out = _round_corners(bg, 30)
    out.save(out_path, "PNG", optimize=True)
    return out_path
