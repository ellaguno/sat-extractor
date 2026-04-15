"""Generación de reportes Excel con openpyxl."""

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..db.repository import Repository
from ..fiscal import calcular_impuestos_mensuales
from ..models import TIPO_COMPROBANTE

# Estilos
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
SECTION_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
SECTION_FONT = Font(bold=True, size=12, color="2F5496")
TOTAL_FONT = Font(bold=True, size=11)
CURRENCY_FMT = '#,##0.00'
THIN_BORDER = Border(
    bottom=Side(style="thin", color="CCCCCC"),
)

CFDI_COLUMNS = [
    ("Fecha", 13),
    ("UUID", 38),
    ("RFC Emisor", 15),
    ("Nombre Emisor", 30),
    ("RFC Receptor", 15),
    ("Nombre Receptor", 30),
    ("Concepto", 40),
    ("Tipo", 10),
    ("SubTotal", 14),
    ("Descuento", 12),
    ("Total", 14),
    ("IVA Trasladado", 14),
    ("ISR Retenido", 13),
    ("IVA Retenido", 13),
    ("Moneda", 8),
    ("Método Pago", 12),
    ("Forma Pago", 11),
    ("Estado", 10),
]

MESES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


class ExcelExporter:
    def __init__(self, db: Repository):
        self.db = db

    def annual_report(self, year: int, output_dir: Path) -> Path:
        """Genera reporte anual: pestaña resumen + una pestaña por mes."""
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"reporte_anual_{year:04d}.xlsx"
        output_path = output_dir / filename

        wb = Workbook()

        # Primera pestaña: Resumen Anual
        ws_resumen = wb.active
        ws_resumen.title = "Resumen Anual"
        self._write_annual_summary(ws_resumen, year)

        # Una pestaña por cada mes
        for month in range(1, 13):
            ws = wb.create_sheet(MESES[month])
            self._write_month_sheet(ws, year, month)

        wb.save(str(output_path))
        return output_path

    def monthly_report(self, year: int, month: int, output_dir: Path) -> Path:
        """Genera reporte de un solo mes."""
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"reporte_mensual_{year:04d}_{month:02d}.xlsx"
        output_path = output_dir / filename

        wb = Workbook()

        ws = wb.active
        ws.title = f"{MESES[month]} {year}"
        self._write_month_sheet(ws, year, month)

        wb.save(str(output_path))
        return output_path

    def _write_month_sheet(self, ws, year: int, month: int):
        """Escribe una hoja con emitidas arriba y recibidas abajo."""
        fecha_inicio = date(year, month, 1)
        fecha_fin = _next_month(year, month)

        emitidas = self.db.search(
            tipo="emitida",
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            limit=10000,
        )
        recibidas = self.db.search(
            tipo="recibida",
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            limit=10000,
        )

        # Configurar anchos de columna
        for col_idx, (_, width) in enumerate(CFDI_COLUMNS, 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        row = 1

        # === SECCIÓN EMITIDAS ===
        row = self._write_section(ws, row, f"EMITIDAS - {MESES[month]} {year}", emitidas)

        # Espacio
        row += 2

        # === SECCIÓN RECIBIDAS ===
        row = self._write_section(ws, row, f"RECIBIDAS - {MESES[month]} {year}", recibidas)

        ws.freeze_panes = "A1"

    def _write_section(self, ws, start_row: int, title: str, cfdis) -> int:
        """Escribe una sección (título + headers + datos + subtotal).
        Retorna la siguiente fila disponible.
        """
        row = start_row
        num_cols = len(CFDI_COLUMNS)

        # Título de sección
        cell = ws.cell(row=row, column=1, value=title)
        cell.font = SECTION_FONT
        for col in range(1, num_cols + 1):
            ws.cell(row=row, column=col).fill = SECTION_FILL
        row += 1

        # Headers
        for col_idx, (name, _) in enumerate(CFDI_COLUMNS, 1):
            cell = ws.cell(row=row, column=col_idx, value=name)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
        row += 1

        # Datos
        total_subtotal = 0.0
        total_descuento = 0.0
        total_total = 0.0
        total_iva_trasl = 0.0
        total_isr_ret = 0.0
        total_iva_ret = 0.0

        if not cfdis:
            ws.cell(row=row, column=1, value="(Sin registros)")
            ws.cell(row=row, column=1).font = Font(italic=True, color="888888")
            row += 1
        else:
            for c in cfdis:
                # Concepto: unir descripciones de todos los conceptos
                concepto = ""
                if c.conceptos:
                    descripciones = [con.descripcion for con in c.conceptos if con.descripcion]
                    concepto = " | ".join(descripciones)

                ws.cell(row=row, column=1, value=c.fecha.strftime("%d/%m/%Y"))
                ws.cell(row=row, column=2, value=c.uuid)
                ws.cell(row=row, column=3, value=c.rfc_emisor)
                ws.cell(row=row, column=4, value=c.nombre_emisor)
                ws.cell(row=row, column=5, value=c.rfc_receptor)
                ws.cell(row=row, column=6, value=c.nombre_receptor)
                ws.cell(row=row, column=7, value=concepto)
                ws.cell(row=row, column=8, value=TIPO_COMPROBANTE.get(c.tipo_comprobante, c.tipo_comprobante))

                subtotal = float(c.subtotal) if c.subtotal else 0
                descuento = float(c.descuento) if c.descuento else 0
                total = float(c.total) if c.total else 0
                iva_t = float(c.iva_trasladado) if c.iva_trasladado else 0
                isr_r = float(c.isr_retenido) if c.isr_retenido else 0
                iva_r = float(c.iva_retenido) if c.iva_retenido else 0

                for col, val in [
                    (9, subtotal), (10, descuento), (11, total),
                    (12, iva_t), (13, isr_r), (14, iva_r),
                ]:
                    cell = ws.cell(row=row, column=col, value=val)
                    cell.number_format = CURRENCY_FMT

                ws.cell(row=row, column=15, value=c.moneda)
                ws.cell(row=row, column=16, value=c.metodo_pago or "")
                ws.cell(row=row, column=17, value=c.forma_pago or "")
                ws.cell(row=row, column=18, value=c.estado)

                total_subtotal += subtotal
                total_descuento += descuento
                total_total += total
                total_iva_trasl += iva_t
                total_isr_ret += isr_r
                total_iva_ret += iva_r

                row += 1

            # Fila de totales
            ws.cell(row=row, column=7, value=f"TOTAL ({len(cfdis)} CFDIs)").font = TOTAL_FONT
            for col, val in [
                (9, total_subtotal), (10, total_descuento), (11, total_total),
                (12, total_iva_trasl), (13, total_isr_ret), (14, total_iva_ret),
            ]:
                cell = ws.cell(row=row, column=col, value=val)
                cell.number_format = CURRENCY_FMT
                cell.font = TOTAL_FONT
            # Línea superior para totales
            for col in range(1, num_cols + 1):
                ws.cell(row=row, column=col).border = Border(
                    top=Side(style="thin", color="2F5496")
                )
            row += 1

        return row

    def _write_annual_summary(self, ws, year: int):
        """Escribe la pestaña de resumen anual."""
        # Título
        title_cell = ws.cell(row=1, column=1, value=f"Resumen Anual {year}")
        title_cell.font = Font(bold=True, size=16, color="2F5496")

        # === SECCIÓN EMITIDAS ===
        row = 3
        cell = ws.cell(row=row, column=1, value="EMITIDAS")
        cell.font = SECTION_FONT
        for col in range(1, 9):
            ws.cell(row=row, column=col).fill = SECTION_FILL
        row += 1

        emi_headers = ["Mes", "CFDIs", "Ingresos", "Egresos", "IVA Trasladado", "ISR Retenido", "IVA Retenido", "Total"]
        emi_widths = [14, 10, 16, 16, 16, 14, 14, 16]
        for col_idx, (h, w) in enumerate(zip(emi_headers, emi_widths), 1):
            cell = ws.cell(row=row, column=col_idx, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            ws.column_dimensions[get_column_letter(col_idx)].width = w
        row += 1

        emi_totals = [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        for month in range(1, 13):
            se = self.db.monthly_summary(year, month, "emitida")
            ws.cell(row=row, column=1, value=MESES[month])
            values = [
                se["num_cfdis"], se["ingresos"], se["egresos"],
                se["iva_trasladado"], se["isr_retenido"], se["iva_retenido"],
                se["total"],
            ]
            for col_idx, val in enumerate(values):
                cell = ws.cell(row=row, column=col_idx + 2, value=val)
                if col_idx >= 1:
                    cell.number_format = CURRENCY_FMT
                emi_totals[col_idx] += val
            row += 1

        # Total emitidas
        ws.cell(row=row, column=1, value="TOTAL").font = TOTAL_FONT
        for col_idx, val in enumerate(emi_totals):
            cell = ws.cell(row=row, column=col_idx + 2, value=val)
            cell.font = TOTAL_FONT
            if col_idx >= 1:
                cell.number_format = CURRENCY_FMT
        for col in range(1, 9):
            ws.cell(row=row, column=col).border = Border(top=Side(style="thin", color="2F5496"))
        row += 2

        # === SECCIÓN RECIBIDAS ===
        cell = ws.cell(row=row, column=1, value="RECIBIDAS")
        cell.font = SECTION_FONT
        for col in range(1, 9):
            ws.cell(row=row, column=col).fill = SECTION_FILL
        row += 1

        for col_idx, (h, _) in enumerate(zip(emi_headers, emi_widths), 1):
            cell = ws.cell(row=row, column=col_idx, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        row += 1

        rec_totals = [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        for month in range(1, 13):
            sr = self.db.monthly_summary(year, month, "recibida")
            ws.cell(row=row, column=1, value=MESES[month])
            values = [
                sr["num_cfdis"], sr["ingresos"], sr["egresos"],
                sr["iva_trasladado"], sr["isr_retenido"], sr["iva_retenido"],
                sr["total"],
            ]
            for col_idx, val in enumerate(values):
                cell = ws.cell(row=row, column=col_idx + 2, value=val)
                if col_idx >= 1:
                    cell.number_format = CURRENCY_FMT
                rec_totals[col_idx] += val
            row += 1

        # Total recibidas
        ws.cell(row=row, column=1, value="TOTAL").font = TOTAL_FONT
        for col_idx, val in enumerate(rec_totals):
            cell = ws.cell(row=row, column=col_idx + 2, value=val)
            cell.font = TOTAL_FONT
            if col_idx >= 1:
                cell.number_format = CURRENCY_FMT
        for col in range(1, 9):
            ws.cell(row=row, column=col).border = Border(top=Side(style="thin", color="2F5496"))
        row += 2

        # === SECCIÓN IMPUESTOS PROVISIONALES ===
        fiscal = calcular_impuestos_mensuales(self.db, year)

        FISCAL_FILL = PatternFill(start_color="C65911", end_color="C65911", fill_type="solid")
        FISCAL_SECTION_FILL = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

        cell = ws.cell(row=row, column=1, value="IMPUESTOS PROVISIONALES (estimado)")
        cell.font = Font(bold=True, size=12, color="C65911")
        for col in range(1, 9):
            ws.cell(row=row, column=col).fill = FISCAL_SECTION_FILL
        row += 1

        fisc_headers = [
            "Mes", "IVA Cobrado", "IVA Acredit.", "IVA Retenido",
            "IVA x Pagar", "Base ISR Acum.", "ISR Prov.", "Total x Pagar",
        ]
        fisc_widths = [14, 16, 16, 14, 16, 16, 16, 16]
        for col_idx, (h, w) in enumerate(zip(fisc_headers, fisc_widths), 1):
            cell = ws.cell(row=row, column=col_idx, value=h)
            cell.fill = FISCAL_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
            if ws.column_dimensions[get_column_letter(col_idx)].width < w:
                ws.column_dimensions[get_column_letter(col_idx)].width = w
        row += 1

        total_iva_pagar = 0.0
        total_isr_prov = 0.0
        for fi in fiscal:
            ws.cell(row=row, column=1, value=MESES[fi["mes"]])
            total_pagar = fi["iva_a_pagar"] + fi["isr_provisional"]
            values = [
                fi["iva_cobrado"], fi["iva_acreditable"], fi["iva_retenido"],
                fi["iva_a_pagar"], fi["base_gravable"], fi["isr_provisional"],
                total_pagar,
            ]
            for col_idx, val in enumerate(values):
                cell = ws.cell(row=row, column=col_idx + 2, value=val)
                cell.number_format = CURRENCY_FMT
            total_iva_pagar += fi["iva_a_pagar"]
            total_isr_prov += fi["isr_provisional"]
            row += 1

        # Total impuestos
        ws.cell(row=row, column=1, value="TOTAL").font = TOTAL_FONT
        for col_idx, val in [
            (4, total_iva_pagar), (6, total_isr_prov),
            (7, total_iva_pagar + total_isr_prov),
        ]:
            cell = ws.cell(row=row, column=col_idx, value=val)
            cell.font = TOTAL_FONT
            cell.number_format = CURRENCY_FMT
        for col in range(1, 9):
            ws.cell(row=row, column=col).border = Border(top=Side(style="thin", color="C65911"))
        row += 1

        # Nota
        ws.cell(row=row + 1, column=1, value=(
            "* IVA x Pagar = IVA cobrado - IVA acreditable - IVA retenido"
        )).font = Font(italic=True, size=9, color="888888")
        ws.cell(row=row + 2, column=1, value=(
            "* ISR Prov. = estimado Art.96 LISR, no incluye depreciaciones, PTU ni pérdidas anteriores"
        )).font = Font(italic=True, size=9, color="888888")

        ws.freeze_panes = "A2"


def _next_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)
