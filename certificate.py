#!/usr/bin/env python3
# certificate.py — polished PDF certificate
# - Institution header (from previous version)
# - Better logo placement (uniform height, aspect-fit, safe margins)
# - Centered certificate number under title
# - Director: F. Nabiyev on signature line
# - Optional QR
# - Optional faint ("colorless") watermark; uses Pillow to fade if available
#
# Required: reportlab
# Optional: qrcode[pil], pillow

import io, hashlib
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# Optional libs
try:
    import qrcode
    HAS_QR = True
except Exception:
    HAS_QR = False

try:
    from PIL import Image, ImageEnhance
    HAS_PIL = True
except Exception:
    HAS_PIL = False

DEFAULT_INSTITUTION = (
    "O'ZBEKISTON RESPUBLIKASI\n ENERGETIKA VAZIRLIGI HUZURIDAGI\n "
    "QAYTA TIKLANUVCHI ENERGIYA MANBALARI \nMILLIY ILMIY-TADQIQOT INSTITUTI"
)

def _short_cert_id(name: str, dt: datetime) -> str:
    b = (name.strip() + "|" + dt.isoformat()).encode("utf-8")
    return dt.strftime("%y%m%d") + "-" + hashlib.sha1(b).hexdigest()[:8].upper()

def _draw_img_fit(c: canvas.Canvas, path: str, x: float, y: float, max_w: float, max_h: float):
    """Draw image fitting inside (max_w, max_h) maintaining aspect ratio."""
    try:
        img = ImageReader(path)
        iw, ih = img.getSize()
        scale = min(max_w/iw, max_h/ih)
        w, h = iw*scale, ih*scale
        c.drawImage(img, x, y, width=w, height=h, mask='auto')
    except Exception:
        pass

def _draw_faint_watermark(c: canvas.Canvas, path: str, x: float, y: float, w: float, h: float, opacity: float=0.12):
    """Place watermark faded to given opacity. If Pillow present, pre-fade; else draw as-is."""
    try:
        if HAS_PIL:
            im = Image.open(path).convert("RGBA")
            # desaturate (colorless)
            im = ImageEnhance.Color(im).enhance(0.0)
            # adjust alpha
            alpha = im.split()[-1]
            alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
            im.putalpha(alpha)
            buf = io.BytesIO(); im.save(buf, format="PNG"); buf.seek(0)
            c.drawImage(ImageReader(buf), x, y, width=w, height=h, mask='auto')
        else:
            # fallback: just draw; advise user to provide already-faint PNG
            c.drawImage(ImageReader(path), x, y, width=w, height=h, mask='auto')
    except Exception:
        pass

def _draw_center_wrapped(c: canvas.Canvas, text: str, y_top: float, max_width_cm: float, line_height: float, font_name="Helvetica-Bold", font_size=12):
    c.setFont(font_name, font_size)
    max_width = max_width_cm * cm
    lines = []
    for raw in text.splitlines():
        words = raw.split()
        cur = ""
        for w in words:
            t = (cur + " " + w).strip()
            if c.stringWidth(t, font_name, font_size) <= max_width:
                cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
    y = y_top
    for ln in lines:
        c.drawCentredString(A4[0]/2, y, ln)
        y -= line_height
    return y

def generate_certificate(
    name: str,
    score: int,
    total: int,
    dt: datetime,
    path: str,
    *,
    institution_name: str = DEFAULT_INSTITUTION,
    issuer: str = "Hydrogen Safety Trainer",
    left_logo_path: str | None = "logo_left.png",
    right_logo_path: str | None = "logo_right.png",
    watermark_path: str | None = "bg_watermark.png",
    verify_url_base: str | None = None
):
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4

    # Borders
    c.setLineWidth(4); c.rect(1*cm, 1*cm, W-2*cm, H-2*cm)
    c.setLineWidth(1); c.rect(1.4*cm, 1.4*cm, W-2.8*cm, H-2.8*cm)

    # Watermark (big, faint, centered)
    if watermark_path:
        try:
            ir, iw, ih = _imgreader_from_path_faint_colorless(watermark_path, opacity=0.12)
            if watermark_mode == "center-original":
                # Draw at original image size, centered on page (in PDF units; ImageReader sizes are points)
                x = (W - iw) / 2.0
                y = (H - ih) / 2.0
                c.drawImage(ir, x, y, width=iw, height=ih, mask='auto')
            else:
                # "fit-faint" — fill a large central region like the old behavior
                x = 1.6*cm; y = 5.0*cm; w = W - 3.2*cm; h = H - 9.0*cm
                c.drawImage(ir, x, y, width=w, height=h, mask='auto')
        except Exception:
            pass

    # Top logos (consistent placement & height)
    TOP_Y = H-4.8*cm
    LOGO_H = 3.0*cm
    MARGIN_X = 1.8*cm
    if left_logo_path:
        _draw_img_fit(c, left_logo_path, x=MARGIN_X, y=TOP_Y, max_w=4.2*cm, max_h=LOGO_H)
    if right_logo_path:
        _draw_img_fit(c, right_logo_path, x=W-MARGIN_X-3.2*cm, y=TOP_Y, max_w=3.2*cm, max_h=LOGO_H)

    # Institution header
    _draw_center_wrapped(
        c, institution_name,
        y_top=H-2.4*cm, max_width_cm=17.5, line_height=0.7*cm,
        font_name="Helvetica-Bold", font_size=12
    )

    # Main title
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(W/2, H-8.0*cm, "CERTIFICATE OF COMPLETION")

    # Certificate number (centered under title)
    cert_id = _short_cert_id(name, dt)
    c.setFont("Helvetica", 11)
    c.drawCentredString(W/2, H-10.2*cm, f"Certificate No: {cert_id}")

    # Issuer / subtitle
    c.setFont("Helvetica", 13)
    c.drawCentredString(W/2, H-9.2*cm, issuer)

    # Recipient
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(W/2, H-14.0*cm, name or "Participant")

    # Score + date
    pct = int(100 * score / max(1, total))
    c.setFont("Helvetica", 12)
    c.drawCentredString(W/2, H-11.2*cm, f"Score: {score}/{total} ({pct}%)")
    c.setFont("Helvetica-Oblique", 11)
    c.drawCentredString(W/2, H-12.0*cm, f"Date: {dt.strftime('%Y-%m-%d %H:%M')}")

    # QR (optional)
    if HAS_QR and verify_url_base:
        url = f"{verify_url_base}{cert_id}"
        qr = qrcode.QRCode(version=2, box_size=5, border=2)
        qr.add_data(url); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        qr_size = 3.0*cm
        c.drawImage(ImageReader(buf), W-1.8*cm-qr_size, 1.5*cm, qr_size, qr_size, mask='auto')
        c.setFont("Helvetica", 8)
        c.drawRightString(W-1.8*cm, 1.2*cm, url)

    # Signature
    c.line(W/2 - 5*cm, 3.4*cm, W/2 + 5*cm, 3.4*cm)
    c.setFont("Helvetica", 10)
    c.drawCentredString(W/2, 2.8*cm, "Director: F. Nabiyev")

    # Footer
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(W/2, 2.1*cm, "For educational purposes only — not a substitute for code compliance or professional training.")

    c.showPage(); c.save()
