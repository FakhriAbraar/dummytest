"""Export Service — generate PDF reports for single content and CSV for content lists."""
from __future__ import annotations

import csv
import io
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ─── Rating helpers ──────────────────────────────────────────────────────────

_AGE_LABEL = {
    "SU": "Semua Umur",
    "7+": "Umur 7+",
    "13+": "Umur 13+",
    "17+": "Umur 17+",
    "PRC": "Perlu Pendampingan",
}

_KATEGORI_LABEL = {
    "educational": "Edukatif",
    "normal": "Normal",
    "bullying": "Bullying",
    "violence": "Kekerasan",
    "sexual": "Seksual",
    "health": "Kesehatan",
    "hoax": "Hoaks",
    "drugs": "Narkoba / Rokok",
    "gambling": "Judi",
    "radicalism": "Radikalisme / SARA",
    "safe": "Aman",
}

_STATUS_LABEL = {
    "SAFE": "Aman",
    "VIOLATION": "Pelanggaran",
    "NEEDS_REVIEW": "Perlu Tinjauan",
}

_PLATFORM_LABEL = {
    "instagram": "Instagram",
    "twitter": "Twitter / X",
    "tiktok": "TikTok",
    "youtube": "YouTube",
}


# ─── Image download helper ───────────────────────────────────────────────────


def _download_image_to_tempfile(url: str) -> str | None:
    """Download an image URL to a temp file and return the path.

    Returns None if the download fails or the response is not an image.
    Caller is responsible for cleaning up the temp file.
    """
    if not url or url.startswith("data:"):
        return None
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return None

        # Determine file extension from content type
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        ext = ext_map.get(content_type.split(";")[0].strip(), ".jpg")

        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"[export] Failed to download image {url[:80]}: {e}")
        return None


# ─── PDF generation for a single content classification ──────────────────────


def generate_content_pdf(item: dict[str, Any]) -> bytes:
    """Build a PDF report for one content item and return the raw PDF bytes.

    When a thumbnailUrl is present, the image is downloaded and embedded as
    visual evidence in the report.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    page_width = A4[0] - 4 * cm  # usable width

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=18,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=4 * mm,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )
    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#1a1a2e"),
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "BodyText2",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#333333"),
        alignment=TA_JUSTIFY,
    )
    label_style = ParagraphStyle(
        "LabelStyle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
        fontName="Helvetica-Bold",
    )
    value_style = ParagraphStyle(
        "ValueStyle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1a1a2e"),
    )
    caption_label_style = ParagraphStyle(
        "CaptionLabel",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#999999"),
        alignment=TA_CENTER,
    )

    story: list[Any] = []

    # Track temp files to clean up later
    temp_files: list[str] = []

    # Header
    story.append(Paragraph("Laporan Hasil Klasifikasi Konten", title_style))
    story.append(
        Paragraph(
            f"Digenerate pada: {datetime.now().strftime('%d %B %Y, %H:%M WIB')}",
            subtitle_style,
        )
    )
    story.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor("#e5e5e5"),
            spaceAfter=4 * mm,
        )
    )

    # ── Evidence image ───────────────────────────────────────────────────
    thumbnail_url = item.get("thumbnailUrl") or ""
    if thumbnail_url:
        img_path = _download_image_to_tempfile(thumbnail_url)
        if img_path:
            temp_files.append(img_path)
            try:
                story.append(Paragraph("Bukti Visual / Screenshot", section_style))

                # Scale image to fit within page width, max height 10 cm
                max_img_width = page_width
                max_img_height = 10 * cm

                img = RLImage(img_path)
                iw, ih = img.imageWidth, img.imageHeight

                if iw > 0 and ih > 0:
                    # Scale proportionally
                    ratio = min(max_img_width / iw, max_img_height / ih, 1.0)
                    display_w = iw * ratio
                    display_h = ih * ratio
                else:
                    display_w = max_img_width
                    display_h = 6 * cm

                img = RLImage(img_path, width=display_w, height=display_h)

                # Wrap the image in a bordered table for a clean "frame" look
                img_table = Table(
                    [[img]],
                    colWidths=[display_w + 4 * mm],
                    rowHeights=[display_h + 4 * mm],
                )
                img_table.setStyle(
                    TableStyle(
                        [
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8f8f8")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                        ]
                    )
                )
                story.append(img_table)
                story.append(
                    Paragraph("Screenshot konten sebagai bukti visual", caption_label_style)
                )
                story.append(Spacer(1, 4 * mm))
            except Exception as e:
                print(f"[export] Failed to embed image in PDF: {e}")

    # Info table
    platform = _PLATFORM_LABEL.get(
        (item.get("platform") or "").lower(),
        item.get("platform", "—"),
    )
    age_group = item.get("ageGroup") or item.get("age_group") or "—"
    age_label = _AGE_LABEL.get(age_group, age_group)
    category = (item.get("category") or "").lower()
    kategori_display = _KATEGORI_LABEL.get(category, category or "—")
    status = _STATUS_LABEL.get(
        item.get("engine_status", ""),
        "Aman" if item.get("classification") == "safe" else "Pelanggaran",
    )

    created_at = item.get("createdAt") or item.get("crawl_timestamp") or ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            created_at = dt.strftime("%d %B %Y, %H:%M")
        except (ValueError, AttributeError):
            pass

    info_data = [
        ["Platform", platform],
        ["Username", item.get("username") or "—"],
        ["Kategori Umur", f"{age_group} — {age_label}"],
        ["Kategori Konten", kategori_display],
        ["Status Klasifikasi", status],
        ["Tanggal Crawl", created_at or "—"],
        ["URL Konten", item.get("contentUrl") or item.get("source_url") or "—"],
        ["ID Konten", str(item.get("id") or item.get("content_id") or "—")],
    ]

    story.append(Paragraph("Informasi Konten", section_style))

    info_table = Table(
        [
            [
                Paragraph(label, label_style),
                Paragraph(str(val), value_style),
            ]
            for label, val in info_data
        ],
        colWidths=[4.5 * cm, None],
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#f0f0f0")),
            ]
        )
    )
    story.append(info_table)

    # Reasoning section
    reason = item.get("reasonAi") or item.get("reason") or ""
    if reason:
        story.append(Paragraph("Keputusan Akhir (Penjelasan AI)", section_style))
        story.append(Paragraph(reason, body_style))

    # Classification details
    classifications = item.get("classifications")
    if classifications:
        story.append(Paragraph("Detail Klasifikasi AI", section_style))

        for label, key in [
            ("Analisis Teks / Linguistik", "tim1_text"),
            ("Analisis Visual", "tim3_visual"),
        ]:
            cls = classifications.get(key)
            if not cls:
                continue

            story.append(Paragraph(f"<b>{label}</b>", body_style))
            story.append(Spacer(1, 2 * mm))

            cls_kategori = _KATEGORI_LABEL.get(
                (cls.get("kategori_ai") or "").lower(),
                cls.get("kategori_ai", "—"),
            )
            cls_data = [
                ["Kategori AI", cls_kategori],
                ["Rating Prediksi", cls.get("predicted_rating", "—")],
                [
                    "Confidence",
                    f"{(cls.get('confidence_score', 0) * 100):.0f}%",
                ],
                ["Reasoning", cls.get("reasoning_category", "—")],
            ]

            cls_table = Table(
                [
                    [
                        Paragraph(l, label_style),
                        Paragraph(str(v), value_style),
                    ]
                    for l, v in cls_data
                ],
                colWidths=[4 * cm, None],
            )
            cls_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#f0f0f0")),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
                    ]
                )
            )
            story.append(cls_table)
            story.append(Spacer(1, 3 * mm))

    # Caption / description
    caption = item.get("caption") or item.get("description") or ""
    if caption:
        story.append(Paragraph("Caption / Deskripsi Konten", section_style))
        # Truncate for safety in PDF
        display_caption = caption[:2000]
        story.append(Paragraph(display_caption, body_style))

    # Keyword
    keyword = item.get("keyword") or ""
    if keyword:
        story.append(Paragraph("Keyword Tren", section_style))
        story.append(Paragraph(keyword, body_style))

    # Footer
    story.append(Spacer(1, 10 * mm))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor("#cccccc"),
            spaceAfter=3 * mm,
        )
    )
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#999999"),
        alignment=TA_CENTER,
    )
    story.append(
        Paragraph(
            "Dokumen ini digenerate secara otomatis oleh Sistem PAD — "
            "Platform Analisis Digital untuk Perlindungan Anak.",
            footer_style,
        )
    )

    doc.build(story)

    # Clean up temporary image files
    for tmp in temp_files:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass

    return buf.getvalue()


# ─── CSV generation for content list ─────────────────────────────────────────


def _clean_cell(value: str) -> str:
    """Sanitize a cell value for clean Excel display.

    - Strip leading/trailing whitespace
    - Replace newlines and carriage returns with a single space
    - Collapse multiple spaces
    """
    if not value:
        return ""
    text = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Collapse multiple spaces
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def generate_content_csv(items: list[dict[str, Any]]) -> bytes:
    """Build a CSV file from a list of content items.

    Returns raw bytes (UTF-8 with BOM) ready for Excel.

    Uses semicolons (;) as the delimiter because:
    - Excel auto-detects semicolons and maps them to separate columns
    - Avoids issues with commas inside caption/reason text
    - Standard for many non-English locales including Indonesian
    """
    buf = io.BytesIO()
    # Write UTF-8 BOM so Excel opens it properly
    buf.write(b"\xef\xbb\xbf")

    text_wrapper = io.TextIOWrapper(buf, encoding="utf-8", newline="")
    writer = csv.writer(
        text_wrapper,
        delimiter=";",
        quoting=csv.QUOTE_ALL,
        quotechar='"',
    )

    # Header row
    writer.writerow(
        [
            "No",
            "ID",
            "Platform",
            "Username",
            "URL Konten",
            "Klasifikasi",
            "Rating Umur",
            "Label Rating",
            "Kategori",
            "Keyword",
            "Caption",
            "Penjelasan AI",
            "Tanggal Crawl",
        ]
    )

    for idx, item in enumerate(items, start=1):
        platform = _PLATFORM_LABEL.get(
            (item.get("platform") or "").lower(),
            item.get("platform", ""),
        )
        classification = (
            "Aman" if item.get("classification") == "safe" else "Tidak Aman"
        )
        age_group = item.get("ageGroup") or item.get("final_rating") or ""
        age_label = _AGE_LABEL.get(age_group, age_group)
        category = _KATEGORI_LABEL.get(
            (item.get("category") or "").lower(),
            item.get("category", ""),
        )
        created_at = item.get("createdAt") or item.get("crawl_timestamp") or ""
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                created_at = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                pass

        caption_raw = item.get("caption") or item.get("description") or ""
        reason_raw = item.get("reasonAi") or item.get("reason", "")

        writer.writerow(
            [
                idx,
                item.get("id") or item.get("content_id", ""),
                platform,
                _clean_cell(item.get("username", "")),
                _clean_cell(item.get("contentUrl") or item.get("source_url", "")),
                classification,
                age_group,
                age_label,
                category,
                _clean_cell(item.get("keyword", "")),
                _clean_cell(caption_raw[:500]),
                _clean_cell(reason_raw[:500]),
                created_at,
            ]
        )

    text_wrapper.detach()  # detach so buf stays open
    return buf.getvalue()
