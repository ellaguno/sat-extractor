"""UI interactiva con Textual — SAT CFDI Extractor."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    OptionList,
    Static,
    TabbedContent,
    TabPane,
)

from ..db.connection import get_connection
from ..db.repository import Repository
from ..export.excel import ExcelExporter, MESES
from ..fiscal import calcular_impuestos_mensuales
from ..fiscal.clasificador import ClasificadorDeducciones
from ..models import TIPO_COMPROBANTE


CURRENT_YEAR = datetime.now().year
CURRENT_MONTH = datetime.now().month


# ── Helpers ──────────────────────────────────────────────────────────────


def _fmt(value: float, prefix: str = "$") -> str:
    """Formatea un número como moneda."""
    return f"{prefix}{value:,.2f}"


def _next_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


# ── Pantallas / Screens ─────────────────────────────────────────────────


class BackScreen(Screen):
    """Base para pantallas con Escape para volver."""

    BINDINGS = [
        Binding("escape", "go_back", "Volver"),
    ]

    def action_go_back(self) -> None:
        self.app.pop_screen()


class DashboardScreen(BackScreen):
    """Dashboard anual con resumen mensual."""

    def __init__(self, db: Repository, config, year: int):
        super().__init__()
        self.db = db
        self.config = config
        self.year = year

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(f"[bold blue]Dashboard {self.year}[/bold blue]", id="dash-title"),
            DataTable(id="dash-table"),
            Static(id="dash-notes"),
            id="dash-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        fiscal = calcular_impuestos_mensuales(self.db, self.year, regimen)

        table = self.query_one("#dash-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        cols = [
            ("Mes", 12), ("Emitidas", 10), ("Facturado", 16),
            ("Recibidas", 10), ("Gastos", 16), ("IVA x Pagar", 14),
            ("ISR Prov.", 14), ("Balance", 16),
        ]
        for label, _w in cols:
            table.add_column(label, key=label)

        grand_emi = grand_rec = grand_iva = grand_isr = 0.0

        for month in range(1, 13):
            se = self.db.monthly_summary(self.year, month, "emitida")
            sr = self.db.monthly_summary(self.year, month, "recibida")
            fi = fiscal[month - 1]

            total_emi = se["total"]
            total_rec = sr["total"]
            iva_pagar = fi["iva_a_pagar"]
            isr_prov = fi["isr_provisional"]
            balance = total_emi - total_rec

            grand_emi += total_emi
            grand_rec += total_rec
            grand_iva += iva_pagar
            grand_isr += isr_prov

            n_total = se["num_cfdis"] + sr["num_cfdis"]

            table.add_row(
                MESES[month],
                str(se["num_cfdis"]) if se["num_cfdis"] else "-",
                _fmt(total_emi) if total_emi else "$0.00",
                str(sr["num_cfdis"]) if sr["num_cfdis"] else "-",
                _fmt(total_rec) if total_rec else "$0.00",
                _fmt(iva_pagar) if n_total else "-",
                _fmt(isr_prov) if n_total else "-",
                _fmt(balance) if n_total else "-",
            )

        grand_balance = grand_emi - grand_rec
        table.add_row(
            "TOTAL", "",
            _fmt(grand_emi), "",
            _fmt(grand_rec),
            _fmt(grand_iva),
            _fmt(grand_isr),
            _fmt(grand_balance),
        )

        notes = self.query_one("#dash-notes", Static)
        notes.update(
            "* IVA x Pagar = IVA cobrado - IVA acreditable - IVA retenido\n"
            "* ISR Prov. = Art.96 LISR sobre (ingresos - deducciones) "
            "- ISR retenido - pagos prev.\n"
            "* No incluye depreciaciones ni pérdidas de ejercicios anteriores"
        )


class MonthDetailScreen(BackScreen):
    """Detalle de un mes: emitidas y recibidas."""

    def __init__(self, db: Repository, year: int, month: int):
        super().__init__()
        self.db = db
        self.year = year
        self.month = month

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(
                f"[bold blue]{MESES[self.month]} {self.year}[/bold blue]",
                id="month-title",
            ),
            Static(id="month-summary"),
            DataTable(id="month-emitidas"),
            DataTable(id="month-recibidas"),
            id="month-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        fecha_inicio = date(self.year, self.month, 1)
        fecha_fin = _next_month(self.year, self.month)

        se = self.db.monthly_summary(self.year, self.month, "emitida")
        sr = self.db.monthly_summary(self.year, self.month, "recibida")

        summary = self.query_one("#month-summary", Static)
        summary.update(
            f"Emitidas: {se['num_cfdis']} CFDIs  {_fmt(se['total'])}    "
            f"Recibidas: {sr['num_cfdis']} CFDIs  {_fmt(sr['total'])}"
        )

        # Emitidas
        emitidas = self.db.search(
            tipo="emitida", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, limit=500,
        )
        self._fill_cfdi_table("#month-emitidas", emitidas, "Emitidas")

        # Recibidas
        recibidas = self.db.search(
            tipo="recibida", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, limit=500,
        )
        self._fill_cfdi_table("#month-recibidas", recibidas, "Recibidas")

    def _fill_cfdi_table(self, table_id: str, cfdis: list, label: str) -> None:
        table = self.query_one(table_id, DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        for col in ["#", "Fecha", "Contraparte", "Concepto", "Total", "Estado", "UUID"]:
            table.add_column(col, key=col)

        if not cfdis:
            table.add_row("-", "-", f"Sin {label.lower()}", "-", "-", "-", "-")
            return

        total_monto = 0.0
        for i, c in enumerate(cfdis, 1):
            contraparte = (
                c.nombre_receptor or c.rfc_receptor
                if c.tipo == "emitida"
                else c.nombre_emisor or c.rfc_emisor
            )
            concepto = ""
            if c.conceptos:
                concepto = c.conceptos[0].descripcion
                if len(c.conceptos) > 1:
                    concepto += f" (+{len(c.conceptos) - 1})"

            monto = float(c.total) if c.total else 0
            total_monto += monto

            table.add_row(
                str(i),
                c.fecha.strftime("%d/%m/%Y"),
                (contraparte or "")[:30],
                concepto[:35],
                _fmt(monto),
                c.estado[:3],
                c.uuid[:8],
            )

        table.add_row(
            "", "", "", f"{len(cfdis)} CFDIs",
            _fmt(total_monto), "", "",
        )


class CfdiDetailScreen(BackScreen):
    """Detalle completo de un CFDI."""

    def __init__(self, db: Repository, uuid: str):
        super().__init__()
        self.db = db
        self.cfdi_uuid = uuid

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(id="cfdi-info"),
            DataTable(id="cfdi-conceptos"),
            id="cfdi-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        cfdi = self.db.get_by_uuid(self.cfdi_uuid)
        if not cfdi:
            info = self.query_one("#cfdi-info", Static)
            info.update("[red]CFDI no encontrado[/red]")
            return

        tipo_label = "EMITIDA" if cfdi.tipo == "emitida" else "RECIBIDA"
        lines = [
            f"[bold]CFDI {cfdi.uuid}[/bold]",
            f"Tipo: {tipo_label} - {TIPO_COMPROBANTE.get(cfdi.tipo_comprobante, cfdi.tipo_comprobante)}",
            f"Estado: {cfdi.estado}",
            f"Fecha: {cfdi.fecha.strftime('%d/%m/%Y %H:%M')}",
            "",
            f"Emisor:   {cfdi.rfc_emisor}  {cfdi.nombre_emisor}",
            f"Receptor: {cfdi.rfc_receptor}  {cfdi.nombre_receptor}",
            f"Uso CFDI: {cfdi.uso_cfdi or '-'}",
            "",
            f"SubTotal: {_fmt(float(cfdi.subtotal))}" if cfdi.subtotal else "",
            f"Total:    {_fmt(float(cfdi.total))}",
            f"Moneda:   {cfdi.moneda}",
            "",
            f"IVA Trasladado: {_fmt(float(cfdi.iva_trasladado))}" if cfdi.iva_trasladado else "",
            f"ISR Retenido:   {_fmt(float(cfdi.isr_retenido))}" if cfdi.isr_retenido else "",
            f"IVA Retenido:   {_fmt(float(cfdi.iva_retenido))}" if cfdi.iva_retenido else "",
            "",
            f"Método Pago: {cfdi.metodo_pago or '-'}",
            f"Forma Pago:  {cfdi.forma_pago or '-'}",
        ]

        info = self.query_one("#cfdi-info", Static)
        info.update("\n".join(line for line in lines if line is not None))

        # Conceptos
        table = self.query_one("#cfdi-conceptos", DataTable)
        table.cursor_type = "row"
        for col in ["#", "Clave", "Descripción", "Cant.", "P. Unit.", "Importe"]:
            table.add_column(col, key=col)

        if cfdi.conceptos:
            for i, con in enumerate(cfdi.conceptos, 1):
                table.add_row(
                    str(i),
                    con.clave_prod_serv,
                    con.descripcion[:45],
                    f"{float(con.cantidad):g}",
                    _fmt(float(con.valor_unitario)),
                    _fmt(float(con.importe)),
                )
        else:
            table.add_row("-", "-", "(Sin conceptos - datos de Metadata)", "-", "-", "-")


class SearchScreen(BackScreen):
    """Buscar CFDIs por RFC o nombre."""

    def __init__(self, db: Repository):
        super().__init__()
        self.db = db

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("[bold]Buscar CFDIs[/bold]"),
            Input(placeholder="RFC o nombre (mín. 3 caracteres)", id="search-input"),
            Static(id="search-status"),
            DataTable(id="search-results"),
            id="search-container",
        )
        yield Footer()

    @on(Input.Submitted, "#search-input")
    def do_search(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if len(query) < 3:
            self.query_one("#search-status", Static).update(
                "[yellow]Ingresa al menos 3 caracteres.[/yellow]"
            )
            return
        self._run_search(query)

    @work(thread=True)
    def _run_search(self, query: str) -> None:
        results = self.db.search(rfc=query.upper(), limit=50)
        if not results:
            # Buscar por nombre
            conn = self.db.conn
            rows = conn.execute(
                """SELECT * FROM comprobantes
                   WHERE nombre_emisor LIKE ? OR nombre_receptor LIKE ?
                   ORDER BY fecha DESC LIMIT 50""",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
            from ..db.repository import _row_to_comprobante
            results = [_row_to_comprobante(r) for r in rows]

        status = self.query_one("#search-status", Static)
        table = self.query_one("#search-results", DataTable)
        table.clear(columns=True)

        if not results:
            status.update("[yellow]No se encontraron resultados.[/yellow]")
            return

        status.update(f"[green]{len(results)} resultado(s)[/green]")

        for col in ["#", "Fecha", "Tipo", "Contraparte", "Concepto", "Total", "UUID"]:
            table.add_column(col, key=col)

        for i, c in enumerate(results, 1):
            contraparte = (
                c.nombre_receptor or c.rfc_receptor
                if c.tipo == "emitida"
                else c.nombre_emisor or c.rfc_emisor
            )
            concepto = ""
            if c.conceptos:
                concepto = c.conceptos[0].descripcion[:30]
            monto = float(c.total) if c.total else 0
            table.add_row(
                str(i),
                c.fecha.strftime("%d/%m"),
                c.tipo[:3].upper(),
                (contraparte or "")[:28],
                concepto,
                _fmt(monto),
                c.uuid[:8],
            )


class TopEntitiesScreen(BackScreen):
    """Top emisores y receptores."""

    def __init__(self, db: Repository, year: int):
        super().__init__()
        self.db = db
        self.year = year

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(f"[bold blue]Top Entidades - {self.year}[/bold blue]"),
            DataTable(id="top-proveedores"),
            DataTable(id="top-clientes"),
            id="top-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        fecha_inicio = date(self.year, 1, 1)
        fecha_fin = date(self.year + 1, 1, 1)
        conn = self.db.conn

        # Top proveedores
        rows = conn.execute(
            """SELECT rfc_emisor, nombre_emisor, COUNT(*) as n, SUM(total) as total
               FROM comprobantes
               WHERE tipo = 'recibida' AND fecha >= ? AND fecha < ?
               GROUP BY rfc_emisor ORDER BY total DESC LIMIT 15""",
            (fecha_inicio.isoformat(), fecha_fin.isoformat()),
        ).fetchall()

        t_prov = self.query_one("#top-proveedores", DataTable)
        t_prov.cursor_type = "row"
        t_prov.zebra_stripes = True
        for col in ["#", "RFC", "Nombre", "CFDIs", "Total"]:
            t_prov.add_column(col, key=col)
        for i, r in enumerate(rows, 1):
            t_prov.add_row(
                str(i), r["rfc_emisor"], (r["nombre_emisor"] or "")[:35],
                str(r["n"]), _fmt(r["total"]),
            )

        # Top clientes
        rows = conn.execute(
            """SELECT rfc_receptor, nombre_receptor, COUNT(*) as n, SUM(total) as total
               FROM comprobantes
               WHERE tipo = 'emitida' AND fecha >= ? AND fecha < ?
               GROUP BY rfc_receptor ORDER BY total DESC LIMIT 15""",
            (fecha_inicio.isoformat(), fecha_fin.isoformat()),
        ).fetchall()

        t_cli = self.query_one("#top-clientes", DataTable)
        t_cli.cursor_type = "row"
        t_cli.zebra_stripes = True
        for col in ["#", "RFC", "Nombre", "CFDIs", "Total"]:
            t_cli.add_column(col, key=f"c_{col}")
        for i, r in enumerate(rows, 1):
            t_cli.add_row(
                str(i), r["rfc_receptor"], (r["nombre_receptor"] or "")[:35],
                str(r["n"]), _fmt(r["total"]),
            )


class FiscalClasificacionScreen(BackScreen):
    """Clasificación de deducciones por periodo."""

    def __init__(self, db: Repository, config, year: int, month: int | None = None):
        super().__init__()
        self.db = db
        self.config = config
        self.year = year
        self.month = month

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(id="fiscal-title"),
            Static(id="fiscal-loading", markup=True),
            DataTable(id="fiscal-table"),
            Static(id="fiscal-totals"),
            id="fiscal-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        titulo = (
            f"{MESES[self.month]} {self.year}" if self.month
            else str(self.year)
        )
        self.query_one("#fiscal-title", Static).update(
            f"[bold magenta]Deducciones - {titulo}[/bold magenta]"
        )
        self.query_one("#fiscal-loading", Static).update("Clasificando...")
        self._load_data()

    def _get_recibidas(self):
        if self.month:
            fecha_inicio = date(self.year, self.month, 1)
            fecha_fin = _next_month(self.year, self.month)
        else:
            fecha_inicio = date(self.year, 1, 1)
            fecha_fin = date(self.year + 1, 1, 1)

        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(self.db.search(
                tipo="recibida", tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                estado="Vigente", limit=5000,
            ))
        return gastos

    @work(thread=True)
    def _load_data(self) -> None:
        recibidas = self._get_recibidas()
        loading = self.query_one("#fiscal-loading", Static)

        if not recibidas:
            loading.update("[yellow]No hay facturas recibidas en este periodo.[/yellow]")
            return

        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        clasificador = ClasificadorDeducciones(regimen, self.db)

        table = self.query_one("#fiscal-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        for col in ["#", "Fecha", "Concepto", "Categoría", "Monto", "Deducible", "%", ""]:
            table.add_column(col, key=col)

        total_original = 0.0
        total_deducible = 0.0
        i = 0

        for comp in recibidas:
            if not comp.conceptos:
                continue
            clasificaciones = clasificador.clasificar_comprobante(comp)
            for clas in clasificaciones:
                i += 1
                monto_orig = float(clas.monto_original)
                monto_ded = float(clas.monto_deducible)
                total_original += monto_orig
                total_deducible += monto_ded

                if not clas.es_deducible:
                    indicator = "X"
                elif clas.alertas:
                    indicator = "!"
                else:
                    indicator = "V"

                table.add_row(
                    str(i),
                    comp.fecha.strftime("%d/%m"),
                    clas.concepto_descripcion[:30],
                    clas.categoria[:20],
                    _fmt(monto_orig),
                    _fmt(monto_ded),
                    f"{clas.porcentaje_deducible:.0f}%",
                    indicator,
                )
                if i >= 200:
                    break
            if i >= 200:
                break

        loading.update("")

        pct = (total_deducible / total_original * 100) if total_original > 0 else 0
        no_ded = total_original - total_deducible
        totals = self.query_one("#fiscal-totals", Static)
        totals.update(
            f"\nDeducible:     {_fmt(total_deducible)}  ({pct:.0f}%)\n"
            f"No deducible:  {_fmt(no_ded)}\n"
            f"{i} conceptos analizados\n"
            "V=deducible  !=alertas  X=no deducible"
        )


class FiscalCategoriasScreen(BackScreen):
    """Resumen de deducciones por categoría."""

    def __init__(self, db: Repository, config, year: int):
        super().__init__()
        self.db = db
        self.config = config
        self.year = year

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(
                f"[bold magenta]Deducciones por Categoría - {self.year}[/bold magenta]",
                id="cat-title",
            ),
            Static(id="cat-loading"),
            DataTable(id="cat-table"),
            Static(id="cat-totals"),
            Static(id="cat-alertas"),
            id="cat-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#cat-loading", Static).update("Analizando...")
        self._load_data()

    def _get_recibidas(self):
        fecha_inicio = date(self.year, 1, 1)
        fecha_fin = date(self.year + 1, 1, 1)
        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(self.db.search(
                tipo="recibida", tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                estado="Vigente", limit=5000,
            ))
        return gastos

    @work(thread=True)
    def _load_data(self) -> None:
        recibidas = self._get_recibidas()
        loading = self.query_one("#cat-loading", Static)

        if not recibidas:
            loading.update("[yellow]No hay facturas recibidas.[/yellow]")
            return

        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        clasificador = ClasificadorDeducciones(regimen, self.db)
        resumen = clasificador.resumen_periodo(recibidas)

        table = self.query_one("#cat-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        for col in ["Categoría", "Conceptos", "Monto Total", "Deducible", "%", "Alertas"]:
            table.add_column(col, key=col)

        cats_sorted = sorted(
            resumen["por_categoria"].items(),
            key=lambda x: float(x[1]["monto_deducible"]),
            reverse=True,
        )

        for cat_id, cat_data in cats_sorted:
            monto_orig = float(cat_data["monto_original"])
            monto_ded = float(cat_data["monto_deducible"])
            pct = cat_data["porcentaje"]
            n_alertas = len(cat_data["alertas"])

            table.add_row(
                cat_data["nombre"][:30],
                str(cat_data["num_conceptos"]),
                _fmt(monto_orig),
                _fmt(monto_ded),
                f"{pct:.0f}%",
                str(n_alertas) if n_alertas else "-",
            )

        loading.update("")

        total_orig = float(resumen["total_original"])
        total_ded = float(resumen["total_deducible"])
        total_no_ded = float(resumen["total_no_deducible"])
        pct_global = resumen["porcentaje_global"]

        totals = self.query_one("#cat-totals", Static)
        totals.update(
            f"\nTotal:         {_fmt(total_orig)}\n"
            f"Deducible:     {_fmt(total_ded)}  ({pct_global:.0f}%)\n"
            f"No deducible:  {_fmt(total_no_ded)}"
        )

        if resumen["alertas"]:
            alertas_text = "Alertas:\n" + "\n".join(
                f"  ! {a}" for a in resumen["alertas"][:5]
            )
            self.query_one("#cat-alertas", Static).update(alertas_text)


class FiscalImpuestosScreen(BackScreen):
    """ISR e IVA estimados a declarar."""

    def __init__(self, db: Repository, config, year: int):
        super().__init__()
        self.db = db
        self.config = config
        self.year = year

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(
                f"[bold magenta]Impuestos Provisionales - {self.year}[/bold magenta]",
                id="imp-title",
            ),
            Static(id="imp-loading"),
            DataTable(id="imp-table"),
            Static(id="imp-detail"),
            Static(id="imp-notes"),
            id="imp-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#imp-loading", Static).update("Calculando...")
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        fiscal = calcular_impuestos_mensuales(self.db, self.year, regimen)

        table = self.query_one("#imp-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        for col in ["Mes", "Ingresos", "Ded. Reales", "No Deducible",
                     "IVA x Pagar", "ISR Prov.", "Total x Pagar"]:
            table.add_column(col, key=col)

        grand = {"ing": 0.0, "ded": 0.0, "no_ded": 0.0, "iva": 0.0, "isr": 0.0}

        for fi in fiscal:
            m = fi["mes"]
            ingresos = fi["ingresos_mes"]
            ded_reales = fi["deducciones_mes"]
            no_ded = fi["deducciones_no_deducibles"]
            iva_pagar = fi["iva_a_pagar"]
            isr_prov = fi["isr_provisional"]
            total_pagar = iva_pagar + isr_prov

            grand["ing"] += ingresos
            grand["ded"] += ded_reales
            grand["no_ded"] += no_ded
            grand["iva"] += iva_pagar
            grand["isr"] += isr_prov

            tiene_datos = ingresos > 0 or ded_reales > 0
            if not tiene_datos:
                table.add_row(MESES[m], "-", "-", "-", "-", "-", "-")
                continue

            table.add_row(
                MESES[m],
                _fmt(ingresos),
                _fmt(ded_reales),
                _fmt(no_ded),
                _fmt(iva_pagar),
                _fmt(isr_prov),
                _fmt(total_pagar),
            )

        grand_total = grand["iva"] + grand["isr"]
        table.add_row(
            "TOTAL",
            _fmt(grand["ing"]),
            _fmt(grand["ded"]),
            _fmt(grand["no_ded"]),
            _fmt(grand["iva"]),
            _fmt(grand["isr"]),
            _fmt(grand_total),
        )

        self.query_one("#imp-loading", Static).update("")

        # Detalle del último mes con datos
        last_fi = None
        for fi in reversed(fiscal):
            if fi["ingresos_mes"] > 0 or fi["deducciones_mes"] > 0:
                last_fi = fi
                break

        if last_fi:
            m = last_fi["mes"]
            detail = (
                f"\nDetalle {MESES[m]} {self.year}:\n"
                f"  IVA cobrado:            {_fmt(last_fi['iva_cobrado']):>14}\n"
                f"  IVA acreditable:        {_fmt(last_fi['iva_acreditable']):>14}  (solo de gastos deducibles)\n"
                f"  IVA retenido:           {_fmt(last_fi['iva_retenido']):>14}\n"
                f"  IVA a pagar:            {_fmt(last_fi['iva_a_pagar']):>14}\n"
                f"\n"
                f"  Ingresos acumulados:    {_fmt(last_fi['ingresos_acum']):>14}\n"
                f"  Deducciones acumuladas: {_fmt(last_fi['deducciones_acum']):>14}  (solo deducibles)\n"
                f"  Base gravable:          {_fmt(last_fi['base_gravable']):>14}\n"
                f"  ISR s/tarifa Art.96:    {_fmt(last_fi['isr_tarifa']):>14}\n"
                f"  ISR retenido acum.:     {_fmt(last_fi['isr_retenido_acum']):>14}\n"
                f"  Pagos prov. anteriores: {_fmt(last_fi['pagos_prov_anteriores']):>14}\n"
                f"  ISR provisional:        {_fmt(last_fi['isr_provisional']):>14}\n"
            )
            self.query_one("#imp-detail", Static).update(detail)

        self.query_one("#imp-notes", Static).update(
            "\n* IVA acreditable = solo IVA de gastos clasificados como deducibles\n"
            "* ISR = Art.96 LISR sobre (ingresos acum. - deducciones reales acum.)\n"
            "* No incluye depreciaciones de inversiones, PTU ni pérdidas anteriores\n"
            "* Estimado educativo - no sustituye asesoría fiscal profesional"
        )


class FiscalSugerenciasScreen(BackScreen):
    """Sugerencias de optimización fiscal."""

    def __init__(self, db: Repository, config, year: int):
        super().__init__()
        self.db = db
        self.config = config
        self.year = year

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(
                f"[bold magenta]Sugerencias de Optimización - {self.year}[/bold magenta]"
            ),
            Static(id="sug-loading"),
            Static(id="sug-content"),
            id="sug-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sug-loading", Static).update("Analizando...")
        self._load_data()

    def _get_recibidas(self):
        fecha_inicio = date(self.year, 1, 1)
        fecha_fin = date(self.year + 1, 1, 1)
        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(self.db.search(
                tipo="recibida", tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                estado="Vigente", limit=5000,
            ))
        return gastos

    @work(thread=True)
    def _load_data(self) -> None:
        recibidas = self._get_recibidas()
        loading = self.query_one("#sug-loading", Static)

        if not recibidas:
            loading.update("[yellow]No hay facturas para analizar.[/yellow]")
            return

        # Calcular ingresos anuales
        ingresos = 0.0
        for month in range(1, 13):
            se = self.db.monthly_summary(self.year, month, "emitida")
            ingresos += se["ingresos"]

        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        clasificador = ClasificadorDeducciones(regimen, self.db)

        sugerencias = clasificador.generar_sugerencias(recibidas, ingresos)

        # IA opcional
        if self.config and self.config.ia and self.config.ia.api_key:
            try:
                from ..fiscal.ia_fiscal import AsistenteFiscal
                asistente = AsistenteFiscal(
                    api_key=self.config.ia.api_key,
                    regimen=regimen,
                    actividad=(
                        self.config.contribuyente.actividad
                        if self.config.contribuyente else ""
                    ),
                    model=self.config.ia.model,
                )
                resumen = clasificador.resumen_periodo(recibidas)
                ia_sugerencias = asistente.generar_sugerencias(resumen, ingresos)
                sugerencias.extend(ia_sugerencias)
            except Exception:
                pass

        loading.update("")

        if not sugerencias:
            self.query_one("#sug-content", Static).update(
                "[green]No se encontraron sugerencias adicionales.[/green]"
            )
            return

        lines = []
        for i, sug in enumerate(sugerencias, 1):
            prioridad_icon = {1: "!!!", 2: "!!", 3: "!"}.get(sug.prioridad, "")
            ahorro = ""
            if sug.ahorro_estimado:
                ahorro = f"  (ahorro estimado: {_fmt(float(sug.ahorro_estimado))})"
            lines.append(f"{prioridad_icon} {i}. {sug.titulo}")
            lines.append(f"   {sug.descripcion}{ahorro}")
            lines.append("")

        lines.append(
            "* Estas sugerencias son educativas y no sustituyen "
            "asesoría fiscal profesional."
        )
        self.query_one("#sug-content", Static).update("\n".join(lines))


class FiscalCfdiScreen(BackScreen):
    """Consultar deducibilidad de un CFDI específico."""

    def __init__(self, db: Repository, config, uuid: str):
        super().__init__()
        self.db = db
        self.config = config
        self.cfdi_uuid = uuid

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Static(id="fc-info"),
            DataTable(id="fc-table"),
            Static(id="fc-detail"),
            id="fc-scroll",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()

    @work(thread=True)
    def _load_data(self) -> None:
        cfdi = self.db.get_by_uuid(self.cfdi_uuid)
        if not cfdi:
            self.query_one("#fc-info", Static).update("[red]CFDI no encontrado[/red]")
            return

        if not cfdi.conceptos:
            self.query_one("#fc-info", Static).update(
                "[yellow]Este CFDI no tiene conceptos (datos de Metadata).[/yellow]"
            )
            return

        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        clasificador = ClasificadorDeducciones(regimen, self.db)
        resumen = clasificador.resumen_deduccion(cfdi)

        # Info panel
        self.query_one("#fc-info", Static).update(
            f"[bold]{cfdi.nombre_emisor}[/bold] -> [bold]{cfdi.nombre_receptor}[/bold]\n"
            f"Fecha: {cfdi.fecha.strftime('%d/%m/%Y')}  |  "
            f"Total: {_fmt(float(cfdi.total))}  |  "
            f"Forma pago: {cfdi.forma_pago or 'N/A'}"
        )

        # Tabla
        table = self.query_one("#fc-table", DataTable)
        table.cursor_type = "row"
        for col in ["#", "Concepto", "Clave SAT", "Categoría", "Monto", "Deducible", "%"]:
            table.add_column(col, key=col)

        for i, clas in enumerate(resumen["clasificaciones"], 1):
            table.add_row(
                str(i),
                clas.concepto_descripcion[:30],
                clas.clave_prod_serv[:10],
                clas.categoria[:18],
                _fmt(float(clas.monto_original)),
                _fmt(float(clas.monto_deducible)),
                f"{clas.porcentaje_deducible:.0f}%",
            )

        # Detail
        lines = []
        for i, clas in enumerate(resumen["clasificaciones"], 1):
            lines.append(f"\nConcepto {i}: {clas.concepto_descripcion}")
            lines.append(f"  Fundamento: {clas.fundamento_legal}")
            if clas.requisitos:
                lines.append(f"  Requisitos: {', '.join(clas.requisitos)}")
            for alerta in clas.alertas:
                lines.append(f"  ! {alerta}")

        pct = resumen["porcentaje_deducible"]
        lines.append(
            f"\nTotal: {_fmt(float(resumen['total_original']))} -> "
            f"Deducible: {_fmt(float(resumen['total_deducible']))} ({pct:.0f}%)"
        )

        if resumen["alertas"]:
            lines.append("\nAlertas del comprobante:")
            for alerta in resumen["alertas"]:
                lines.append(f"  ! {alerta}")

        self.query_one("#fc-detail", Static).update("\n".join(lines))


# ── Input Dialogs (modales) ──────────────────────────────────────────────


class YearInputScreen(ModalScreen[int | None]):
    """Pide un año al usuario."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, title: str = "Año"):
        super().__init__()
        self.title_text = title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(f"[bold]{self.title_text}[/bold]"),
            Input(
                value=str(CURRENT_YEAR),
                placeholder="Año",
                id="year-input",
                type="integer",
            ),
            id="year-dialog",
            classes="dialog",
        )

    @on(Input.Submitted, "#year-input")
    def submit(self, event: Input.Submitted) -> None:
        try:
            self.dismiss(int(event.value))
        except ValueError:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class YearMonthInputScreen(ModalScreen[tuple[int, int | None] | None]):
    """Pide año y mes al usuario."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, title: str = "Periodo", ask_month: bool = True):
        super().__init__()
        self.title_text = title
        self.ask_month = ask_month

    def compose(self) -> ComposeResult:
        widgets = [
            Static(f"[bold]{self.title_text}[/bold]"),
            Static("Año:"),
            Input(
                value=str(CURRENT_YEAR),
                placeholder="Año",
                id="ym-year",
                type="integer",
            ),
        ]
        if self.ask_month:
            widgets.extend([
                Static("Mes (0 = todo el año):"),
                Input(
                    value=str(CURRENT_MONTH),
                    placeholder="Mes",
                    id="ym-month",
                    type="integer",
                ),
            ])
        yield Vertical(*widgets, id="ym-dialog", classes="dialog")

    @on(Input.Submitted, "#ym-month")
    @on(Input.Submitted, "#ym-year")
    def submit(self, event: Input.Submitted) -> None:
        try:
            year = int(self.query_one("#ym-year", Input).value)
        except ValueError:
            self.dismiss(None)
            return

        month = None
        if self.ask_month:
            try:
                m = int(self.query_one("#ym-month", Input).value)
                if 1 <= m <= 12:
                    month = m
            except (ValueError, Exception):
                pass

        self.dismiss((year, month))

    def action_cancel(self) -> None:
        self.dismiss(None)


class UuidInputScreen(ModalScreen[str | None]):
    """Pide un UUID al usuario."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[bold]UUID del CFDI[/bold]"),
            Input(placeholder="UUID (completo o primeros caracteres)", id="uuid-input"),
            id="uuid-dialog",
            classes="dialog",
        )

    @on(Input.Submitted, "#uuid-input")
    def submit(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        self.dismiss(val if val else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DirInputScreen(ModalScreen[str | None]):
    """Pide un directorio al usuario."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[bold]Directorio con XMLs[/bold]"),
            Input(placeholder="Ruta del directorio", id="dir-input"),
            id="dir-dialog",
            classes="dialog",
        )

    @on(Input.Submitted, "#dir-input")
    def submit(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        self.dismiss(val if val else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── App Principal ────────────────────────────────────────────────────────


class SATExtractorApp(App):
    """Aplicación principal SAT CFDI Extractor."""

    TITLE = "SAT CFDI Extractor"
    SUB_TITLE = "Gestión de facturas electrónicas"

    CSS = """
    Screen {
        background: $surface;
    }

    #main-menu {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    #stats {
        margin-bottom: 1;
        text-style: italic;
        color: $text-muted;
    }

    #main-options {
        height: auto;
        max-height: 60%;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    .dialog {
        align: center middle;
        width: 50;
        max-width: 60;
        height: auto;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }

    .dialog Input {
        margin: 1 0;
    }

    DataTable {
        height: auto;
        max-height: 80%;
        margin: 1 0;
    }

    VerticalScroll {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("1", "do_download", "Descargar", show=False),
        Binding("2", "do_import", "Importar", show=False),
        Binding("d", "dashboard", "Dashboard"),
        Binding("m", "month", "Mes"),
        Binding("b", "search", "Buscar"),
        Binding("t", "top", "Top"),
        Binding("e", "export", "Excel"),
        Binding("f", "fiscal", "Fiscal"),
    ]

    def __init__(self, db_path: Path, config=None):
        super().__init__()
        self.conn = get_connection(db_path)
        self.db = Repository(self.conn)
        self.config = config
        regimen = "612"
        if config and config.contribuyente:
            regimen = config.contribuyente.regimen
        self.exporter = ExcelExporter(self.db, regimen=regimen)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(id="stats"),
            OptionList(
                "  [d] Dashboard anual",
                "  [m] Detalle mensual",
                "  [b] Buscar por RFC o nombre",
                "  [t] Top emisores / receptores",
                "  [e] Exportar a Excel",
                "  [f] Análisis Fiscal Inteligente",
                "  ────────────────────────────────",
                "  [1] Descargar CFDIs del SAT",
                "  [2] Importar XMLs desde directorio",
                "  ────────────────────────────────",
                "  [q] Salir",
                id="main-options",
            ),
            Static(id="status-bar"),
            id="main-menu",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        n_emi = self.db.count(tipo="emitida")
        n_rec = self.db.count(tipo="recibida")
        total = n_emi + n_rec
        stats = self.query_one("#stats", Static)
        if total == 0:
            stats.update("Base de datos vacía")
        else:
            stats.update(
                f"BD: {total} CFDIs ({n_emi} emitidas, {n_rec} recibidas)"
            )

    @on(OptionList.OptionSelected, "#main-options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        actions = {
            0: self.action_dashboard,
            1: self.action_month,
            2: self.action_search,
            3: self.action_top,
            4: self.action_export,
            5: self.action_fiscal,
            7: self.action_do_download,
            8: self.action_do_import,
            10: self.action_quit,
        }
        action = actions.get(idx)
        if action:
            action()

    # ── Acciones de navegación ──

    def action_dashboard(self) -> None:
        def on_year(year: int | None) -> None:
            if year:
                self.push_screen(DashboardScreen(self.db, self.config, year))

        self.push_screen(YearInputScreen("Dashboard - Año"), on_year)

    def action_month(self) -> None:
        def on_period(result: tuple | None) -> None:
            if result:
                year, month = result
                m = month if month else CURRENT_MONTH
                self.push_screen(MonthDetailScreen(self.db, year, m))

        self.push_screen(
            YearMonthInputScreen("Detalle Mensual", ask_month=True), on_period
        )

    def action_search(self) -> None:
        self.push_screen(SearchScreen(self.db))

    def action_top(self) -> None:
        def on_year(year: int | None) -> None:
            if year:
                self.push_screen(TopEntitiesScreen(self.db, year))

        self.push_screen(YearInputScreen("Top Entidades - Año"), on_year)

    def action_export(self) -> None:
        def on_period(result: tuple | None) -> None:
            if result:
                year, month = result
                self._do_export(year, month)

        self.push_screen(
            YearMonthInputScreen("Exportar Excel (mes 0 = anual)"), on_period
        )

    @work(thread=True)
    def _do_export(self, year: int, month: int | None) -> None:
        output_dir = Path("~/reportes_sat").expanduser()
        if self.config:
            output_dir = self.config.export.output_dir

        try:
            if month:
                path = self.exporter.monthly_report(year, month, output_dir)
            else:
                path = self.exporter.annual_report(year, output_dir)
            self.notify(f"Reporte guardado: {path}", title="Excel")
        except Exception as e:
            self.notify(f"Error: {e}", title="Error", severity="error")

    def action_fiscal(self) -> None:
        self.push_screen(FiscalMenuScreen(self.db, self.config))

    def action_do_download(self) -> None:
        if not self.config:
            self.notify(
                "Se requiere config.toml con FIEL para descargar",
                title="Error",
                severity="error",
            )
            return
        # Descarga SAT — simplificada, pide año+mes
        def on_period(result: tuple | None) -> None:
            if result:
                year, month = result
                self._do_download(year, month)

        self.push_screen(
            YearMonthInputScreen("Descargar del SAT"), on_period
        )

    @work(thread=True)
    def _do_download(self, year: int, month: int | None) -> None:
        try:
            from ..auth.fiel import load_fiel_interactive
            from ..download.service import SATDownloader
            from ..download.package import extract_and_process

            fiel = load_fiel_interactive(
                self.config.fiel.cer_path,
                self.config.fiel.key_path,
                password=self.config.fiel.password,
            )
            downloader = SATDownloader(fiel, self.config.sat.rfc)

            m_start = month or 1
            m_end = month or 12
            start = date(year, m_start, 1)
            today = date.today()
            if m_end == 12:
                end = date(year, 12, 31)
            else:
                from datetime import timedelta
                end = date(year, m_end + 1, 1) - timedelta(days=1)
            if end > today:
                end = today

            total_new = 0
            for tipo in ("recibida", "emitida"):
                zips = downloader.download_range(start, end, tipo, db=self.db)
                for zip_path in zips:
                    n = extract_and_process(zip_path, self.db, tipo)
                    total_new += n

            self.notify(f"{total_new} CFDIs importados", title="Descarga SAT")
            self.call_from_thread(self._refresh_stats)
        except Exception as e:
            self.notify(f"Error: {e}", title="Error", severity="error")

    def action_do_import(self) -> None:
        def on_dir(dir_path: str | None) -> None:
            if dir_path:
                self._do_import(dir_path)

        self.push_screen(DirInputScreen(), on_dir)

    @work(thread=True)
    def _do_import(self, dir_str: str) -> None:
        from ..download.package import import_xml_directory

        directory = Path(dir_str).expanduser()
        if not directory.is_dir():
            self.notify(f"No existe: {directory}", title="Error", severity="error")
            return

        rfc = None
        if self.config and hasattr(self.config, "sat") and self.config.sat:
            rfc = self.config.sat.rfc

        try:
            if rfc:
                counts = import_xml_directory(directory, self.db, rfc_propio=rfc)
            else:
                counts = import_xml_directory(directory, self.db, "recibida")

            total = counts["emitida"] + counts["recibida"]
            self.notify(
                f"{total} CFDIs: {counts['emitida']} emitidas, "
                f"{counts['recibida']} recibidas",
                title="Importación",
            )
            self.call_from_thread(self._refresh_stats)
        except Exception as e:
            self.notify(f"Error: {e}", title="Error", severity="error")


class FiscalMenuScreen(BackScreen):
    """Menú de Análisis Fiscal Inteligente."""

    BINDINGS = [
        Binding("1", "fiscal_clasificar", "Clasificar", show=False),
        Binding("2", "fiscal_categorias", "Categorías", show=False),
        Binding("3", "fiscal_impuestos", "ISR/IVA", show=False),
        Binding("4", "fiscal_sugerencias", "Sugerencias", show=False),
        Binding("5", "fiscal_cfdi", "Consultar CFDI", show=False),
    ]

    def __init__(self, db: Repository, config):
        super().__init__()
        self.db = db
        self.config = config

    def compose(self) -> ComposeResult:
        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen

        yield Header()
        yield Vertical(
            Static(
                f"[bold magenta]Análisis Fiscal Inteligente[/bold magenta]\n"
                f"Régimen: {regimen}"
            ),
            OptionList(
                "  [1] Clasificar deducciones del periodo",
                "  [2] Resumen por categoría de gasto",
                "  [3] ISR e IVA estimados a declarar",
                "  [4] Sugerencias de optimización",
                "  [5] Consultar deducibilidad de un CFDI",
                id="fiscal-options",
            ),
            id="fiscal-menu",
        )
        yield Footer()

    @on(OptionList.OptionSelected, "#fiscal-options")
    def on_fiscal_option(self, event: OptionList.OptionSelected) -> None:
        actions = {
            0: self.action_fiscal_clasificar,
            1: self.action_fiscal_categorias,
            2: self.action_fiscal_impuestos,
            3: self.action_fiscal_sugerencias,
            4: self.action_fiscal_cfdi,
        }
        action = actions.get(event.option_index)
        if action:
            action()

    def action_fiscal_clasificar(self) -> None:
        def on_period(result: tuple | None) -> None:
            if result:
                year, month = result
                self.app.push_screen(
                    FiscalClasificacionScreen(self.db, self.config, year, month)
                )

        self.app.push_screen(
            YearMonthInputScreen("Clasificar Deducciones"), on_period
        )

    def action_fiscal_categorias(self) -> None:
        def on_year(year: int | None) -> None:
            if year:
                self.app.push_screen(
                    FiscalCategoriasScreen(self.db, self.config, year)
                )

        self.app.push_screen(YearInputScreen("Resumen por Categoría - Año"), on_year)

    def action_fiscal_impuestos(self) -> None:
        def on_year(year: int | None) -> None:
            if year:
                self.app.push_screen(
                    FiscalImpuestosScreen(self.db, self.config, year)
                )

        self.app.push_screen(YearInputScreen("ISR/IVA Estimados - Año"), on_year)

    def action_fiscal_sugerencias(self) -> None:
        def on_year(year: int | None) -> None:
            if year:
                self.app.push_screen(
                    FiscalSugerenciasScreen(self.db, self.config, year)
                )

        self.app.push_screen(YearInputScreen("Sugerencias - Año"), on_year)

    def action_fiscal_cfdi(self) -> None:
        def on_uuid(uuid: str | None) -> None:
            if uuid:
                self._resolve_uuid(uuid)

        self.app.push_screen(UuidInputScreen(), on_uuid)

    def _resolve_uuid(self, prefix: str) -> None:
        prefix = prefix.upper().strip()
        rows = self.db.conn.execute(
            "SELECT uuid FROM comprobantes WHERE uuid LIKE ? LIMIT 5",
            (f"{prefix}%",),
        ).fetchall()

        if not rows:
            self.app.notify(f"No se encontró CFDI '{prefix}...'", severity="warning")
            return

        if len(rows) > 1:
            self.app.notify(
                f"Múltiples coincidencias ({len(rows)}). Usa más caracteres.",
                severity="warning",
            )
            return

        self.app.push_screen(
            FiscalCfdiScreen(self.db, self.config, rows[0]["uuid"])
        )


def run_tui(db_path: Path, config=None):
    """Punto de entrada para la TUI."""
    app = SATExtractorApp(db_path=db_path, config=config)
    app.run()
