"""Excel export builder (Phase 4-D). Pure function: day sheet → .xlsx bytes."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from app.schemas.day_sheet import DaySheetOut


def build_day_sheet_xlsx(sheet: DaySheetOut) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Day Sheet"

    ws["A1"] = f"Day Sheet — {sheet.business_date}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "CLOSED" if sheet.is_closed else "OPEN"

    headers = ["Delivery staff", "Cylinders", "Cash", "UPI", "Total"]
    ws.append([])
    ws.append(headers)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    for row in sheet.rows:
        ws.append(
            [row.delivery_name, row.cylinders, float(row.cash), float(row.upi), float(row.total)]
        )

    ws.append(
        [
            "Total",
            sheet.totals.cylinders,
            float(sheet.totals.cash),
            float(sheet.totals.upi),
            float(sheet.totals.total),
        ]
    )
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
