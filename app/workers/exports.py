"""Excel export builder (Phase 4-D). Pure function: day sheet → .xlsx bytes."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from app.schemas.day_sheet import DaySheetOut

HEADERS = [
    "Party",
    "Sold",
    "Empty",
    "Return",
    "Total amount",
    "UPI",
    "Cash",
    "Online",
    "Balance",
]


def build_day_sheet_xlsx(sheet: DaySheetOut) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Day Sheet"

    ws["A1"] = f"Day Sheet — {sheet.business_date}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "CLOSED" if sheet.is_closed else "OPEN"

    ws.append([])
    ws.append(HEADERS)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    for row in sheet.rows:
        name = (
            f"{row.delivery_name} (customer)" if row.party_kind == "customer" else row.delivery_name
        )
        ws.append(
            [
                name,
                row.cylinders,
                row.empties,
                row.damaged,
                float(row.amount),
                float(row.upi),
                float(row.cash),
                float(row.online),
                float(row.balance),
            ]
        )

    t = sheet.totals
    ws.append(
        [
            "Total",
            t.cylinders,
            t.empties,
            t.damaged,
            float(t.amount),
            float(t.upi),
            float(t.cash),
            float(t.online),
            float(t.balance),
        ]
    )
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
