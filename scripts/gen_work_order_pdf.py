"""
Temporary script to generate a mock 2-page work order PDF for demo/test data.
Run: uv run python scripts/gen_work_order_pdf.py
Output: demo_files/work_order_fiber_splice.pdf
"""

from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

OUTPUT_DIR = Path(__file__).parent.parent / "content_understanding" / "demo_files"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "work_order_fiber_splice.pdf"

# ── Color palette ──────────────────────────────────────────────────────────────
BRAND_BLUE   = colors.HexColor("#1B4F9B")
BRAND_ORANGE = colors.HexColor("#F47B20")
LIGHT_GRAY   = colors.HexColor("#F4F6FA")
MID_GRAY     = colors.HexColor("#CCCCCC")
DARK_GRAY    = colors.HexColor("#444444")
RED          = colors.HexColor("#C0392B")

# ── Work order data ────────────────────────────────────────────────────────────
WO = {
    "title":                "Fiber Splice Restoration — Springfield Business Park",
    "status":               "OPEN",
    "priority":             "CRITICAL",
    "assigned_technician":  "J. Martinez",
    "site_technician":      None,            # On-site tech contact; can be empty
    "location":             "742 Evergreen Terrace, Springfield, WA 99999",
    "created_at":           "2026-05-18  08:15 PDT",
    "updated_at":           "2026-05-18  08:15 PDT",
    "due_date":             "2026-05-20  17:00 PDT",
    "description": (
        "Restore 24-count feeder splice after cabinet damage and verify light "
        "levels for affected tenants. A utility vehicle struck the fiber cabinet "
        "at the northwest corner of the building parking structure, shearing the "
        "24-count SM feeder at approximately 3 m from the splice enclosure. "
        "Fourteen tenant circuits are currently down. Technician must expose the "
        "damaged section, re-splice all affected fibers, reseal the enclosure, "
        "and confirm restore of signal for each affected circuit before closure."
    ),
    "parts_needed": [
        {"part_id": "FIB-003", "name": "Single-Mode Splice Tray (12-fiber)",  "quantity": 2, "unit": "ea"},
        {"part_id": "FIB-012", "name": "Fiber Splice Enclosure (24-count)",   "quantity": 1, "ea": "ea"},
    ],
    "site_contact":     "John Smith",
    "site_contact_phone": "(425) 555-0183",
    "site_contact_role": "Network Operations Supervisor",
    "access_notes":     "Escort required. Check in at security desk (lobby entrance). Hard hat + safety vest mandatory in parking structure.",
    "safety_protocols": [
        "Wear PPE: safety glasses, cut-resistant gloves, and high-vis vest",
        "Lock out / tag out power to cabinet before opening enclosure",
        "Confirm no live laser sources before handling bare fiber",
        "Follow aerial/confined-space entry procedures if man-hole access required",
        "Dispose of fiber cleave scraps in designated sharps container",
    ],
}

CHECKLIST = [
    ("Pre-work",  [
        "Review as-built drawings for cable route",
        "Confirm part availability (FIB-003 × 2, FIB-012 × 1)",
        "Notify NOC of maintenance window",
        "Verify OTDR baseline on affected fibers",
    ]),
    ("On-site",   [
        "Check in with contact (Marcus Tran, Building Facilities)",
        "Photograph damage before any repair",
        "Expose and clean damaged splice point",
        "Perform fusion splices — target IL ≤ 0.10 dB each",
        "Re-organize fibers into new splice tray (FIB-003)",
        "Install new enclosure (FIB-012) and reseal per manufacturer spec",
        "Run end-to-end OTDR trace on all 24 fibers",
    ]),
    ("Post-work", [
        "Confirm signal restoration for all 14 affected tenant circuits",
        "Update work order status to 'completed' in system",
        "Upload OTDR trace files and site photos to work order",
        "Return unused parts to vehicle stock",
        "Notify NOC that maintenance window is closed",
    ]),
]

SIGN_FIELDS = [
    # (role_label, print_name) — both blank, OPEN work order not yet signed
    # J. Martinez is ONLY in the Dispatch Log as "Route → J. Martinez"
    # which reads as routing metadata, not an "assigned technician" label
    ("Technician Signature", ""),
    ("Supervisor Sign-off",  ""),
]


def build_styles():
    base = getSampleStyleSheet()

    def add(name, **kw):
        base.add(ParagraphStyle(name=name, **kw))

    add("DocTitle",     fontSize=18, textColor=colors.white,  fontName="Helvetica-Bold",  alignment=TA_LEFT,   leading=22)
    add("DocSubtitle",  fontSize=10, textColor=colors.white,  fontName="Helvetica",       alignment=TA_LEFT,   leading=14)
    add("SectionHead",  fontSize=11, textColor=BRAND_BLUE,    fontName="Helvetica-Bold",  spaceBefore=12,      leading=14)
    add("BodyText2",    fontSize=9,  textColor=DARK_GRAY,     fontName="Helvetica",       leading=13)
    add("BulletItem",   fontSize=9,  textColor=DARK_GRAY,     fontName="Helvetica",       leading=13, leftIndent=12, bulletIndent=0)
    add("FooterText",   fontSize=7,  textColor=MID_GRAY,      fontName="Helvetica",       alignment=TA_CENTER)
    add("BadgeText",    fontSize=9,  textColor=colors.white,  fontName="Helvetica-Bold",  alignment=TA_CENTER)
    add("FieldLabel",   fontSize=8,  textColor=DARK_GRAY,     fontName="Helvetica-Bold",  leading=11)
    add("FieldValue",   fontSize=9,  textColor=DARK_GRAY,     fontName="Helvetica",       leading=12)
    return base


def header_table(wo, styles):
    """Two-row header: blue title bar + metadata row."""
    badge_color = RED if wo["priority"] == "CRITICAL" else BRAND_ORANGE
    badge = Paragraph(wo["priority"], styles["BadgeText"])
    title = Paragraph(wo["title"], styles["DocTitle"])
    sub   = Paragraph(f"Status: {wo['status']}   •   Due: {wo['due_date']}", styles["DocSubtitle"])

    # Top bar: Title+Sub | Priority badge
    top = Table(
        [[[title, sub], badge]],
        colWidths=[5.8*inch, 1.2*inch],
        rowHeights=[0.75*inch],
    )
    top.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), BRAND_BLUE),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",       (1, 0), (1, 0),   "CENTER"),
        ("BACKGROUND",  (1, 0), (1, 0),   badge_color),
        ("LEFTPADDING", (0, 0), (0, 0),   10),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    # Metadata block — 2 rows × 4 columns.
    # Row 0: "Field Technician" → John Smith (on-site contact)  |  "On-Site Technician" → — (empty)
    # Row 1: "Location" → address                               |  "Created" → date
    #
    # Demo intent: LLM reads "Field Technician: John Smith" and confidently returns John Smith
    # as the assigned technician (WRONG). The actual dispatched tech (J. Martinez) is ONLY in
    # the Dispatch Log as "Route → J. Martinez". The custom analyzer ignores this header and
    # extracts from the Dispatch Log instead (CORRECT).
    meta_data = [
        [
            Paragraph("<b>Field Technician</b>", styles["FieldLabel"]),
            Paragraph(wo["site_contact"], styles["FieldValue"]),
            Paragraph("<b>On-Site Technician</b>", styles["FieldLabel"]),
            Paragraph("—", styles["FieldValue"]),
        ],
        [
            Paragraph("<b>Location</b>", styles["FieldLabel"]),
            Paragraph(wo["location"], styles["FieldValue"]),
            Paragraph("<b>Created</b>", styles["FieldLabel"]),
            Paragraph(wo["created_at"], styles["FieldValue"]),
        ],
    ]
    meta = Table(meta_data, colWidths=[1.4*inch, 1.5*inch, 1.3*inch, 2.8*inch])
    meta.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GRAY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, MID_GRAY),
    ]))

    return [top, meta]


def dispatch_table(wo, styles):
    """Dispatch routing block — J. Martinez appears here as a routing reference,
    NOT labeled as 'technician'. The LLM reading flat markdown sees John Smith as
    'Field Technical Contact' (the most prominent labeled name) and returns that.
    The custom analyzer description points exactly to the name after 'Route →' in
    this block, so it returns J. Martinez (correct).
    """
    DISPATCH_BLUE = colors.HexColor("#E8EEF7")
    rows = [[
        Paragraph("<b>Dispatch Log</b>", styles["FieldLabel"]),
        Paragraph(f"2026-05-18 08:15 PDT  |  NOC Ref: WO-DISP-0518  |  "
                  f"Dispatcher: R. Singh  |  Route → {wo['assigned_technician']}  |  Status: Pending Accept",
                  styles["FieldValue"]),
    ]]
    t = Table(rows, colWidths=[1.1*inch, 5.9*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), DISPATCH_BLUE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, MID_GRAY),
    ]))
    return t


def section(title, styles):
    return [
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1, color=BRAND_BLUE, spaceAfter=4),
        Paragraph(title.upper(), styles["SectionHead"]),
    ]


def parts_table(parts, styles):
    header = ["Part ID", "Description", "Qty", "Unit"]
    rows   = [header] + [[p["part_id"], p["name"], str(p["quantity"]), "ea"] for p in parts]
    t = Table(rows, colWidths=[0.9*inch, 4.2*inch, 0.6*inch, 0.6*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("ALIGN",         (2, 0), (3, -1),  "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    return t


def checklist_table(checklist, styles):
    rows = []
    for phase, items in checklist:
        rows.append([Paragraph(f"<b>{phase}</b>", styles["FieldLabel"]), ""])
        for item in items:
            rows.append(["☐", Paragraph(item, styles["BodyText2"])])

    t = Table(rows, colWidths=[0.35*inch, 6.65*inch])
    style_cmds = [
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (1, 0), (1, -1),  6),
    ]
    # Shade phase header rows
    row_idx = 0
    for phase, items in checklist:
        style_cmds.append(("BACKGROUND",  (0, row_idx), (-1, row_idx), LIGHT_GRAY))
        style_cmds.append(("SPAN",        (0, row_idx), (-1, row_idx)))
        row_idx += 1 + len(items)

    t.setStyle(TableStyle(style_cmds))
    return t


def sign_table(fields, styles):
    """Sign-off block. fields = list of (role_label, print_name).
    Signature is always blank (OPEN work order). Print Name is pre-filled
    where provided — J. Martinez appears here as the assigned technician,
    but it's subtle enough that a plain LLM returns the more prominent
    'Field Technical Contact: John Smith' instead.
    """
    header_row = [
        Paragraph("<b>Role</b>",        styles["FieldLabel"]),
        Paragraph("<b>Signature</b>",   styles["FieldLabel"]),
        Paragraph("<b>Print Name</b>",  styles["FieldLabel"]),
        Paragraph("<b>Date</b>",        styles["FieldLabel"]),
    ]
    rows = [header_row]
    for label, print_name in fields:
        rows.append([
            Paragraph(f"<b>{label}</b>", styles["FieldLabel"]),
            Paragraph("", styles["FieldValue"]),           # Signature — always blank
            Paragraph(print_name or "", styles["FieldValue"]),  # Print Name — may be pre-filled
            Paragraph("", styles["FieldValue"]),
        ])

    t = Table(rows,
              colWidths=[1.5*inch, 2.2*inch, 2.0*inch, 1.3*inch],
              rowHeights=[0.28*inch] + [0.6*inch] * len(fields))
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("GRID",          (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("BACKGROUND",    (0, 1), (0, -1),  LIGHT_GRAY),
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (1, 1), (3, -1),  0.6, DARK_GRAY),
    ]))
    return t


def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MID_GRAY)
    canvas.drawCentredString(
        LETTER[0] / 2, 0.4 * inch,
        f"Fibey Field Ops  •  Fiber Splice Restoration  •  Page {doc.page} of 2  •  CONFIDENTIAL"
    )
    canvas.restoreState()


def build_pdf():
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=LETTER,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.5*inch,
        bottomMargin=0.6*inch,
        title="Fiber Splice Restoration — Redmond Business Park",
        author="Fibey Field Ops",
    )

    story = []

    # ── PAGE 1 ─────────────────────────────────────────────────────────────────
    story += header_table(WO, styles)
    story.append(dispatch_table(WO, styles))

    # Description
    story += section("Job Description", styles)
    story.append(Paragraph(WO["description"], styles["BodyText2"]))

    # Site access
    story += section("Site Access & Contact", styles)
    story.append(Paragraph(f"<b>Contact:</b>  {WO['site_contact']}  —  {WO['site_contact_role']}  |  {WO['site_contact_phone']}", styles["BodyText2"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Access Notes:</b>  {WO['access_notes']}", styles["BodyText2"]))

    # Safety
    story += section("Safety Protocols", styles)
    for item in WO["safety_protocols"]:
        story.append(Paragraph(f"• {item}", styles["BulletItem"]))

    # Parts
    story += section("Parts & Materials Required", styles)
    story.append(parts_table(WO["parts_needed"], styles))

    # ── PAGE 2 ─────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story += header_table(WO, styles)
    story.append(dispatch_table(WO, styles))

    # Checklist
    story += section("Field Completion Checklist", styles)
    story.append(checklist_table(CHECKLIST, styles))

    # Notes box
    story += section("Technician Notes / Observations", styles)
    notes_data = [["" for _ in range(1)] for _ in range(6)]
    notes_t = Table(notes_data, colWidths=[7*inch], rowHeights=[18]*6)
    notes_t.setStyle(TableStyle([
        ("GRID",       (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
    ]))
    story.append(notes_t)

    # Sign-off pinned to bottom via large spacer + KeepTogether
    sign_block = section("Sign-Off & Completion", styles) + [sign_table(SIGN_FIELDS, styles)]
    story.append(Spacer(1, 0.3*inch))
    story.append(KeepTogether(sign_block))

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"✅ PDF written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
