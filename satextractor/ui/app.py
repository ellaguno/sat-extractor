"""UI de terminal con Rich."""

from datetime import date, datetime
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from ..db.connection import get_connection
from ..db.repository import Repository
from ..download.package import import_xml_directory
from ..export.excel import ExcelExporter, MESES
from ..fiscal import calcular_impuestos_mensuales
from ..fiscal.clasificador import ClasificadorDeducciones
from ..models import TIPO_COMPROBANTE

console = Console()

CURRENT_YEAR = datetime.now().year
CURRENT_MONTH = datetime.now().month


class App:
    def __init__(self, db_path: Path, config=None):
        self.conn = get_connection(db_path)
        self.db = Repository(self.conn)
        self.config = config
        regimen = "612"
        if config and config.contribuyente:
            regimen = config.contribuyente.regimen
        self.exporter = ExcelExporter(self.db, regimen=regimen)

    def run(self):
        console.clear()
        console.print(
            Panel.fit(
                "[bold blue]SAT CFDI Extractor[/bold blue]\n"
                "Gestión de facturas electrónicas",
                border_style="blue",
            )
        )

        while True:
            console.print()
            self._show_db_stats()
            console.print()
            console.print("[bold]Menú Principal[/bold]")
            console.print("  [1] Descargar CFDIs del SAT")
            console.print("  [2] Importar XMLs desde directorio")
            console.print("  [3] Visualizar datos")
            console.print("  [4] Exportar a Excel")
            console.print("  [5] Análisis Fiscal Inteligente")
            console.print("  [0] Salir")
            console.print()

            try:
                option = IntPrompt.ask("Opción", default=0)
            except (KeyboardInterrupt, EOFError):
                break

            if option == 0:
                console.print("[dim]Hasta luego.[/dim]")
                break
            elif option == 1:
                self._menu_download()
            elif option == 2:
                self._menu_import()
            elif option == 3:
                self._menu_viewer()
            elif option == 4:
                self._menu_export()
            elif option == 5:
                self._menu_fiscal()
            else:
                console.print("[red]Opción no válida[/red]")

        self.conn.close()

    # ── Stats ──────────────────────────────────────────────────────────

    def _show_db_stats(self):
        n_emi = self.db.count(tipo="emitida")
        n_rec = self.db.count(tipo="recibida")
        total = n_emi + n_rec
        if total == 0:
            console.print("[dim]Base de datos vacía[/dim]")
        else:
            console.print(
                f"[dim]BD: {total} CFDIs ({n_emi} emitidas, {n_rec} recibidas)[/dim]"
            )

    # ── Viewer ─────────────────────────────────────────────────────────

    def _menu_viewer(self):
        while True:
            console.print()
            console.print("[bold]Visualizar Datos[/bold]")
            console.print("  [1] Dashboard anual")
            console.print("  [2] Detalle mensual")
            console.print("  [3] Buscar por RFC o nombre")
            console.print("  [4] Ver detalle de un CFDI")
            console.print("  [5] Top emisores / receptores")
            console.print("  [0] Volver")
            console.print()

            try:
                opt = IntPrompt.ask("Opción", default=0)
            except (KeyboardInterrupt, EOFError):
                break

            if opt == 0:
                break
            elif opt == 1:
                self._view_dashboard()
            elif opt == 2:
                self._view_month_detail()
            elif opt == 3:
                self._view_search()
            elif opt == 4:
                self._view_cfdi_detail()
            elif opt == 5:
                self._view_top_entities()

    def _view_dashboard(self):
        year = IntPrompt.ask("Año", default=CURRENT_YEAR)
        console.print()

        # Calcular impuestos provisionales
        fiscal = calcular_impuestos_mensuales(self.db, year)

        # ── Tabla resumen anual ──
        table = Table(
            title=f"Dashboard {year}",
            title_style="bold blue",
            border_style="blue",
            show_lines=True,
        )
        table.add_column("Mes", style="bold", width=12)
        table.add_column("Emitidas", justify="center", width=10)
        table.add_column("Facturado", justify="right", width=16, style="green")
        table.add_column("Recibidas", justify="center", width=10)
        table.add_column("Gastos", justify="right", width=16, style="cyan")
        table.add_column("IVA x Pagar", justify="right", width=14)
        table.add_column("ISR Prov.", justify="right", width=14)
        table.add_column("Balance", justify="right", width=16)

        grand_emi = 0.0
        grand_rec = 0.0
        grand_iva_pagar = 0.0
        grand_isr_prov = 0.0

        for month in range(1, 13):
            se = self.db.monthly_summary(year, month, "emitida")
            sr = self.db.monthly_summary(year, month, "recibida")
            fi = fiscal[month - 1]

            total_emi = se["total"]
            total_rec = sr["total"]
            iva_pagar = fi["iva_a_pagar"]
            isr_prov = fi["isr_provisional"]
            balance = total_emi - total_rec

            grand_emi += total_emi
            grand_rec += total_rec
            grand_iva_pagar += iva_pagar
            grand_isr_prov += isr_prov

            # Resaltar meses con datos
            n_total = se["num_cfdis"] + sr["num_cfdis"]
            mes_style = "bold" if n_total > 0 else "dim"
            balance_style = "green" if balance >= 0 else "red"
            iva_style = "red" if iva_pagar > 0 else "green" if iva_pagar < 0 else "dim"
            isr_style = "red" if isr_prov > 0 else "dim"

            table.add_row(
                f"[{mes_style}]{MESES[month]}[/{mes_style}]",
                str(se["num_cfdis"]) if se["num_cfdis"] else "[dim]-[/dim]",
                f"${total_emi:,.2f}" if total_emi else "[dim]$0.00[/dim]",
                str(sr["num_cfdis"]) if sr["num_cfdis"] else "[dim]-[/dim]",
                f"${total_rec:,.2f}" if total_rec else "[dim]$0.00[/dim]",
                f"[{iva_style}]${iva_pagar:,.2f}[/{iva_style}]" if n_total else "[dim]-[/dim]",
                f"[{isr_style}]${isr_prov:,.2f}[/{isr_style}]" if n_total else "[dim]-[/dim]",
                f"[{balance_style}]${balance:,.2f}[/{balance_style}]" if n_total else "[dim]-[/dim]",
            )

        # Fila totales
        grand_balance = grand_emi - grand_rec
        bal_style = "bold green" if grand_balance >= 0 else "bold red"
        table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            f"[bold]${grand_emi:,.2f}[/bold]",
            "",
            f"[bold]${grand_rec:,.2f}[/bold]",
            f"[bold]${grand_iva_pagar:,.2f}[/bold]",
            f"[bold]${grand_isr_prov:,.2f}[/bold]",
            f"[{bal_style}]${grand_balance:,.2f}[/{bal_style}]",
            end_section=True,
        )

        console.print(table)
        console.print(
            "[dim]* IVA x Pagar = IVA cobrado - IVA acreditable - IVA retenido[/dim]\n"
            "[dim]* ISR Prov. = Art.96 LISR sobre (ingresos - deducciones) - ISR retenido - pagos prev. (no incluye depreciaciones ni pérdidas ant.)[/dim]"
        )

        # Prompt para ver detalle de un mes
        console.print()
        mes = IntPrompt.ask("Ver detalle del mes (0 = volver)", default=0)
        if 1 <= mes <= 12:
            self._show_month(year, mes)

    def _view_month_detail(self):
        year = IntPrompt.ask("Año", default=CURRENT_YEAR)
        month = IntPrompt.ask("Mes", default=CURRENT_MONTH)
        self._show_month(year, month)

    def _show_month(self, year: int, month: int):
        """Muestra el detalle de un mes: emitidas arriba, recibidas abajo."""
        console.print()
        fecha_inicio = date(year, month, 1)
        fecha_fin = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)

        # Resumen rápido
        se = self.db.monthly_summary(year, month, "emitida")
        sr = self.db.monthly_summary(year, month, "recibida")

        summary = Table.grid(padding=(0, 3))
        summary.add_column()
        summary.add_column(justify="right")
        summary.add_column()
        summary.add_column(justify="right")
        summary.add_row(
            "[bold green]Emitidas:[/bold green]", f"{se['num_cfdis']} CFDIs  ${se['total']:,.2f}",
            "[bold cyan]Recibidas:[/bold cyan]", f"{sr['num_cfdis']} CFDIs  ${sr['total']:,.2f}",
        )
        console.print(Panel(
            summary,
            title=f"[bold]{MESES[month]} {year}[/bold]",
            border_style="blue",
        ))

        # Emitidas
        emitidas = self.db.search(
            tipo="emitida", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
            limit=500,
        )
        if emitidas:
            console.print()
            self._print_cfdi_table(emitidas, f"Emitidas - {MESES[month]}", "green")

        # Recibidas
        recibidas = self.db.search(
            tipo="recibida", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
            limit=500,
        )
        if recibidas:
            console.print()
            self._print_cfdi_table(recibidas, f"Recibidas - {MESES[month]}", "cyan")

        if not emitidas and not recibidas:
            console.print("[yellow]No hay datos para este mes.[/yellow]")
            return

        # Opción de ver detalle
        console.print()
        uuid_prefix = Prompt.ask(
            "UUID para ver detalle (Enter para volver)", default=""
        )
        if uuid_prefix:
            self._show_cfdi_by_prefix(uuid_prefix)

    def _print_cfdi_table(self, cfdis, title: str, color: str):
        """Imprime una tabla de CFDIs con concepto."""
        table = Table(
            title=title,
            title_style=f"bold {color}",
            border_style=color,
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("#", width=3, style="dim")
        table.add_column("Fecha", width=10)
        table.add_column("Emisor / Receptor", width=30, no_wrap=True)
        table.add_column("Concepto", width=35, no_wrap=True)
        table.add_column("Total", justify="right", width=14)
        table.add_column("Estado", width=8)
        table.add_column("UUID", width=10, style="dim")

        total_monto = 0.0
        for i, c in enumerate(cfdis, 1):
            # Determinar contraparte
            if c.tipo == "emitida":
                contraparte = c.nombre_receptor or c.rfc_receptor
            else:
                contraparte = c.nombre_emisor or c.rfc_emisor

            # Concepto
            concepto = ""
            if c.conceptos:
                concepto = c.conceptos[0].descripcion
                if len(c.conceptos) > 1:
                    concepto += f" (+{len(c.conceptos) - 1})"

            estado_style = "green" if c.estado == "Vigente" else "red"
            monto = float(c.total) if c.total else 0
            total_monto += monto

            table.add_row(
                str(i),
                c.fecha.strftime("%d/%m/%Y"),
                contraparte[:30],
                concepto[:35],
                f"${monto:,.2f}",
                f"[{estado_style}]{c.estado[:3]}[/{estado_style}]",
                c.uuid[:8],
            )

        # Fila total
        table.add_row(
            "", "", "", f"[bold]{len(cfdis)} CFDIs[/bold]",
            f"[bold]${total_monto:,.2f}[/bold]", "", "",
            end_section=True,
        )
        console.print(table)

    def _view_search(self):
        console.print("\n[bold]Buscar CFDIs[/bold]")
        query = Prompt.ask("RFC o nombre (parcial)")

        if not query or len(query) < 3:
            console.print("[yellow]Ingresa al menos 3 caracteres.[/yellow]")
            return

        # Buscar por RFC
        results = self.db.search(rfc=query.upper(), limit=50)

        # Si no hay resultados por RFC, buscar por nombre
        if not results:
            results = self._search_by_name(query)

        if not results:
            console.print("[yellow]No se encontraron resultados.[/yellow]")
            return

        console.print(f"\n[green]{len(results)} resultado(s)[/green]")
        self._print_cfdi_table(results, f"Búsqueda: {query}", "yellow")

        console.print()
        uuid_prefix = Prompt.ask(
            "UUID para ver detalle (Enter para volver)", default=""
        )
        if uuid_prefix:
            self._show_cfdi_by_prefix(uuid_prefix)

    def _search_by_name(self, name: str) -> list:
        """Busca por nombre de emisor o receptor en la BD."""
        rows = self.conn.execute(
            """SELECT * FROM comprobantes
               WHERE nombre_emisor LIKE ? OR nombre_receptor LIKE ?
               ORDER BY fecha DESC LIMIT 50""",
            (f"%{name}%", f"%{name}%"),
        ).fetchall()
        from ..db.repository import _row_to_comprobante
        return [_row_to_comprobante(r) for r in rows]

    def _view_cfdi_detail(self):
        uuid_input = Prompt.ask("UUID (completo o primeros caracteres)")
        if uuid_input:
            self._show_cfdi_by_prefix(uuid_input)

    def _show_cfdi_by_prefix(self, prefix: str):
        """Busca y muestra el detalle de un CFDI por prefijo de UUID."""
        prefix = prefix.upper().strip()

        # Buscar por prefijo
        rows = self.conn.execute(
            "SELECT uuid FROM comprobantes WHERE uuid LIKE ? LIMIT 5",
            (f"{prefix}%",),
        ).fetchall()

        if not rows:
            console.print(f"[yellow]No se encontró CFDI con UUID '{prefix}...'[/yellow]")
            return

        if len(rows) > 1:
            console.print("[yellow]Múltiples coincidencias:[/yellow]")
            for r in rows:
                console.print(f"  {r['uuid']}")
            return

        cfdi = self.db.get_by_uuid(rows[0]["uuid"])
        if not cfdi:
            return

        # Panel principal
        tipo_label = "EMITIDA" if cfdi.tipo == "emitida" else "RECIBIDA"
        tipo_color = "green" if cfdi.tipo == "emitida" else "cyan"
        estado_color = "green" if cfdi.estado == "Vigente" else "red"

        info = Table.grid(padding=(0, 2))
        info.add_column(style="bold", width=20)
        info.add_column(width=50)

        info.add_row("UUID", cfdi.uuid)
        info.add_row("Fecha", cfdi.fecha.strftime("%d/%m/%Y %H:%M"))
        info.add_row("Tipo", f"[{tipo_color}]{tipo_label}[/{tipo_color}] - {TIPO_COMPROBANTE.get(cfdi.tipo_comprobante, cfdi.tipo_comprobante)}")
        info.add_row("Estado", f"[{estado_color}]{cfdi.estado}[/{estado_color}]")
        info.add_row("", "")
        info.add_row("Emisor RFC", cfdi.rfc_emisor)
        info.add_row("Emisor Nombre", cfdi.nombre_emisor)
        info.add_row("Régimen Fiscal", cfdi.regimen_emisor or "-")
        info.add_row("", "")
        info.add_row("Receptor RFC", cfdi.rfc_receptor)
        info.add_row("Receptor Nombre", cfdi.nombre_receptor)
        info.add_row("Uso CFDI", cfdi.uso_cfdi or "-")
        info.add_row("", "")
        info.add_row("SubTotal", f"${float(cfdi.subtotal):,.2f}" if cfdi.subtotal else "-")
        if cfdi.descuento:
            info.add_row("Descuento", f"${float(cfdi.descuento):,.2f}")
        info.add_row("Total", f"[bold]${float(cfdi.total):,.2f}[/bold]")
        info.add_row("Moneda", cfdi.moneda)
        if cfdi.tipo_cambio:
            info.add_row("Tipo Cambio", f"{float(cfdi.tipo_cambio):,.4f}")
        info.add_row("", "")
        info.add_row("IVA Trasladado", f"${float(cfdi.iva_trasladado):,.2f}" if cfdi.iva_trasladado else "-")
        info.add_row("ISR Retenido", f"${float(cfdi.isr_retenido):,.2f}" if cfdi.isr_retenido else "-")
        info.add_row("IVA Retenido", f"${float(cfdi.iva_retenido):,.2f}" if cfdi.iva_retenido else "-")
        info.add_row("", "")
        info.add_row("Método Pago", cfdi.metodo_pago or "-")
        info.add_row("Forma Pago", cfdi.forma_pago or "-")
        info.add_row("Lugar Expedición", cfdi.lugar_expedicion or "-")
        if cfdi.fecha_timbrado:
            info.add_row("Fecha Timbrado", cfdi.fecha_timbrado.strftime("%d/%m/%Y %H:%M"))

        console.print(Panel(
            info,
            title=f"[bold]CFDI {cfdi.uuid[:8]}...[/bold]",
            border_style=tipo_color,
        ))

        # Conceptos
        if cfdi.conceptos:
            console.print()
            table = Table(
                title="Conceptos",
                border_style="dim",
                show_lines=True,
            )
            table.add_column("#", width=3, style="dim")
            table.add_column("Clave", width=10)
            table.add_column("Descripción", width=45)
            table.add_column("Cant.", justify="right", width=6)
            table.add_column("P. Unit.", justify="right", width=14)
            table.add_column("Importe", justify="right", width=14)

            for i, con in enumerate(cfdi.conceptos, 1):
                table.add_row(
                    str(i),
                    con.clave_prod_serv,
                    con.descripcion,
                    f"{float(con.cantidad):g}",
                    f"${float(con.valor_unitario):,.2f}",
                    f"${float(con.importe):,.2f}",
                )

            console.print(table)
        else:
            console.print("[dim]  (Sin conceptos - datos de Metadata)[/dim]")

        # Acciones sobre el CFDI
        console.print()
        console.print("[dim]Acciones:[/dim]")
        if cfdi.estado == "Vigente":
            console.print("  \\[c] Marcar como Cancelado")
        else:
            console.print("  \\[v] Marcar como Vigente")
        console.print("  \\[x] Eliminar de la base de datos")
        console.print("  \\[Enter] Volver")

        action = Prompt.ask("Acción", default="")
        action = action.strip().lower()

        if action == "c" and cfdi.estado == "Vigente":
            if Confirm.ask(
                f"¿Marcar CFDI {cfdi.uuid[:8]}... como [red]Cancelado[/red]?",
                default=False,
            ):
                self.db.update_estado(cfdi.uuid, "Cancelado")
                console.print("[red]CFDI marcado como Cancelado.[/red]")
        elif action == "v" and cfdi.estado != "Vigente":
            if Confirm.ask(
                f"¿Marcar CFDI {cfdi.uuid[:8]}... como [green]Vigente[/green]?",
                default=False,
            ):
                self.db.update_estado(cfdi.uuid, "Vigente")
                console.print("[green]CFDI marcado como Vigente.[/green]")
        elif action == "x":
            console.print(
                f"[bold red]Esto eliminará permanentemente el CFDI "
                f"{cfdi.uuid[:8]}... (${float(cfdi.total):,.2f})[/bold red]"
            )
            if Confirm.ask("¿Estás seguro?", default=False):
                self.db.delete_comprobante(cfdi.uuid)
                console.print("[red]CFDI eliminado.[/red]")

    def _view_top_entities(self):
        year = IntPrompt.ask("Año", default=CURRENT_YEAR)
        fecha_inicio = date(year, 1, 1)
        fecha_fin = date(year + 1, 1, 1)

        console.print()

        # Top emisores (facturas recibidas - a quién le compramos más)
        rows = self.conn.execute(
            """SELECT rfc_emisor, nombre_emisor, COUNT(*) as n, SUM(total) as total
               FROM comprobantes
               WHERE tipo = 'recibida' AND fecha >= ? AND fecha < ?
               GROUP BY rfc_emisor
               ORDER BY total DESC LIMIT 15""",
            (fecha_inicio.isoformat(), fecha_fin.isoformat()),
        ).fetchall()

        if rows:
            table = Table(
                title=f"Top Proveedores (Recibidas) - {year}",
                title_style="bold cyan",
                border_style="cyan",
            )
            table.add_column("#", width=3, style="dim")
            table.add_column("RFC", width=14)
            table.add_column("Nombre", width=35, no_wrap=True)
            table.add_column("CFDIs", justify="right", width=7)
            table.add_column("Total", justify="right", width=16)

            for i, r in enumerate(rows, 1):
                table.add_row(
                    str(i),
                    r["rfc_emisor"],
                    (r["nombre_emisor"] or "")[:35],
                    str(r["n"]),
                    f"${r['total']:,.2f}",
                )
            console.print(table)

        # Top receptores (facturas emitidas - a quién le facturamos más)
        rows = self.conn.execute(
            """SELECT rfc_receptor, nombre_receptor, COUNT(*) as n, SUM(total) as total
               FROM comprobantes
               WHERE tipo = 'emitida' AND fecha >= ? AND fecha < ?
               GROUP BY rfc_receptor
               ORDER BY total DESC LIMIT 15""",
            (fecha_inicio.isoformat(), fecha_fin.isoformat()),
        ).fetchall()

        if rows:
            console.print()
            table = Table(
                title=f"Top Clientes (Emitidas) - {year}",
                title_style="bold green",
                border_style="green",
            )
            table.add_column("#", width=3, style="dim")
            table.add_column("RFC", width=14)
            table.add_column("Nombre", width=35, no_wrap=True)
            table.add_column("CFDIs", justify="right", width=7)
            table.add_column("Total", justify="right", width=16)

            for i, r in enumerate(rows, 1):
                table.add_row(
                    str(i),
                    r["rfc_receptor"],
                    (r["nombre_receptor"] or "")[:35],
                    str(r["n"]),
                    f"${r['total']:,.2f}",
                )
            console.print(table)

        if not rows:
            console.print("[yellow]No hay datos para este año.[/yellow]")

    # ── Download ───────────────────────────────────────────────────────

    def _menu_download(self):
        if not self.config:
            console.print(
                "[red]Se requiere config.toml con datos de FIEL para descargar del SAT.[/red]"
            )
            return

        console.print("\n[bold]Descargar CFDIs del SAT[/bold]")
        console.print("  [1] Recibidas")
        console.print("  [2] Emitidas")
        console.print("  [3] Ambas")
        opcion = IntPrompt.ask("Tipo", default=3)

        year = IntPrompt.ask("Año", default=CURRENT_YEAR)
        month_start = IntPrompt.ask("Mes inicio", default=1)
        month_end = IntPrompt.ask("Mes fin", default=CURRENT_MONTH)

        start = date(year, month_start, 1)
        today = date.today()
        if month_end == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month_end + 1, 1)
            from datetime import timedelta
            end = end - timedelta(days=1)
        if end > today:
            end = today
        if start > today:
            console.print("[red]La fecha de inicio es futura.[/red]")
            return

        tipos = []
        if opcion in (1, 3):
            tipos.append("recibida")
        if opcion in (2, 3):
            tipos.append("emitida")

        try:
            from ..auth.fiel import load_fiel_interactive
            from ..download.service import SATDownloader
            from ..download.package import extract_and_process

            console.print("\n[bold]Autenticando con FIEL...[/bold]")
            fiel = load_fiel_interactive(
                self.config.fiel.cer_path,
                self.config.fiel.key_path,
                password=self.config.fiel.password,
            )

            downloader = SATDownloader(fiel, self.config.sat.rfc)

            for tipo in tipos:
                console.print(f"\n[cyan]Descargando {tipo}s: {start} → {end}[/cyan]")
                zips = downloader.download_range(start, end, tipo, db=self.db)

                total_new = 0
                for zip_path in zips:
                    n = extract_and_process(zip_path, self.db, tipo)
                    total_new += n

                if total_new > 0:
                    console.print(f"[green]{total_new} CFDI(s) {tipo}s importados desde XML[/green]")

        except ImportError as e:
            if "cfdiclient" in str(e):
                console.print(
                    "[red]Instala cfdiclient: pip install cfdiclient[/red]"
                )
            else:
                console.print(f"[red]Error de importación: {e}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    def _menu_import(self):
        console.print("\n[bold]Importar XMLs desde directorio[/bold]")
        dir_str = Prompt.ask("Directorio con XMLs")
        directory = Path(dir_str).expanduser()

        if not directory.is_dir():
            console.print(f"[red]No existe el directorio: {directory}[/red]")
            return

        # Auto-detectar tipo si tenemos RFC en config
        rfc = None
        if self.config and hasattr(self.config, "sat") and self.config.sat:
            rfc = self.config.sat.rfc

        if rfc:
            console.print(f"  Auto-detectando tipo (emitida/recibida) por RFC: {rfc}")
            counts = import_xml_directory(directory, self.db, rfc_propio=rfc)
        else:
            console.print("  [1] Recibidas")
            console.print("  [2] Emitidas")
            tipo_opt = IntPrompt.ask("Tipo de facturas", default=1)
            tipo = "recibida" if tipo_opt == 1 else "emitida"
            counts = import_xml_directory(directory, self.db, tipo)

        total = counts["emitida"] + counts["recibida"]
        console.print(
            f"[green]{total} CFDI(s) importados: "
            f"{counts['emitida']} emitida(s), {counts['recibida']} recibida(s)[/green]"
        )

    # ── Export ─────────────────────────────────────────────────────────

    def _menu_export(self):
        console.print("\n[bold]Exportar a Excel[/bold]")
        console.print("  [1] Reporte mensual")
        console.print("  [2] Reporte anual")
        opcion = IntPrompt.ask("Tipo", default=1)

        output_dir = Path("~/reportes_sat").expanduser()
        if self.config:
            output_dir = self.config.export.output_dir

        if opcion == 1:
            year = IntPrompt.ask("Año", default=CURRENT_YEAR)
            month = IntPrompt.ask("Mes", default=CURRENT_MONTH)
            n_rec = self.db.count(tipo="recibida", fecha_inicio=date(year, month, 1),
                                  fecha_fin=date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1))
            n_emi = self.db.count(tipo="emitida", fecha_inicio=date(year, month, 1),
                                  fecha_fin=date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1))
            console.print(f"  Registros: {n_rec} recibidas, {n_emi} emitidas")
            if n_rec == 0 and n_emi == 0:
                console.print("[yellow]  No hay datos para este período.[/yellow]")
                if not Confirm.ask("¿Generar de todos modos?", default=False):
                    return
            path = self.exporter.monthly_report(year, month, output_dir)
            console.print(f"[green]Reporte guardado en: {path}[/green]")
        elif opcion == 2:
            year = IntPrompt.ask("Año", default=CURRENT_YEAR)
            n_rec = self.db.count(tipo="recibida", fecha_inicio=date(year, 1, 1), fecha_fin=date(year + 1, 1, 1))
            n_emi = self.db.count(tipo="emitida", fecha_inicio=date(year, 1, 1), fecha_fin=date(year + 1, 1, 1))
            console.print(f"  Registros: {n_rec} recibidas, {n_emi} emitidas")
            path = self.exporter.annual_report(year, output_dir)
            console.print(f"[green]Reporte guardado en: {path}[/green]")

    # ── Análisis Fiscal Inteligente ────────────────────────────────────

    def _get_regimen(self) -> str:
        """Obtiene el régimen fiscal de la configuración o pregunta."""
        if self.config and self.config.contribuyente:
            return self.config.contribuyente.regimen
        return "612"

    def _get_clasificador(self) -> ClasificadorDeducciones:
        regimen = self._get_regimen()
        return ClasificadorDeducciones(regimen, self.db)

    def _menu_fiscal(self):
        while True:
            console.print()
            console.print("[bold magenta]Análisis Fiscal Inteligente[/bold magenta]")
            regimen = self._get_regimen()
            console.print(f"[dim]Régimen: {regimen}[/dim]")
            console.print()
            console.print("  [1] Clasificar deducciones del periodo")
            console.print("  [2] Resumen por categoría de gasto")
            console.print("  [3] Sugerencias de optimización")
            console.print("  [4] Consultar deducibilidad de un CFDI")
            console.print("  [0] Volver")
            console.print()

            try:
                opt = IntPrompt.ask("Opción", default=0)
            except (KeyboardInterrupt, EOFError):
                break

            if opt == 0:
                break
            elif opt == 1:
                self._fiscal_clasificar_periodo()
            elif opt == 2:
                self._fiscal_resumen_categorias()
            elif opt == 3:
                self._fiscal_sugerencias()
            elif opt == 4:
                self._fiscal_consultar_cfdi()

    def _fiscal_get_recibidas(self, year: int, month: int | None = None):
        """Obtiene facturas recibidas del periodo."""
        if month:
            fecha_inicio = date(year, month, 1)
            fecha_fin = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
        else:
            fecha_inicio = date(year, 1, 1)
            fecha_fin = date(year + 1, 1, 1)

        return self.db.search(
            tipo="recibida",
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            limit=5000,
        )

    def _fiscal_clasificar_periodo(self):
        console.print("\n[bold]Clasificar Deducciones[/bold]")
        year = IntPrompt.ask("Año", default=CURRENT_YEAR)
        console.print("  Mes (0 = todo el año)")
        month_input = IntPrompt.ask("Mes", default=0)
        month = month_input if 1 <= month_input <= 12 else None

        recibidas = self._fiscal_get_recibidas(year, month)
        if not recibidas:
            console.print("[yellow]No hay facturas recibidas en este periodo.[/yellow]")
            return

        clasificador = self._get_clasificador()
        periodo_label = f"{MESES[month]} {year}" if month else str(year)

        console.print(f"\n[dim]Clasificando {len(recibidas)} facturas recibidas...[/dim]")

        # Tabla de clasificación por concepto
        table = Table(
            title=f"Deducciones - {periodo_label}",
            title_style="bold magenta",
            border_style="magenta",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("#", width=3, style="dim")
        table.add_column("Fecha", width=10)
        table.add_column("Concepto", width=30, no_wrap=True)
        table.add_column("Categoría", width=20, no_wrap=True)
        table.add_column("Monto", justify="right", width=12)
        table.add_column("Ded.", justify="right", width=12)
        table.add_column("%", justify="right", width=6)
        table.add_column("", width=3)  # Alertas indicator

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

                # Estilo según deducibilidad
                if not clas.es_deducible:
                    ded_style = "red"
                    indicator = "[red]X[/red]"
                elif clas.confianza < 0.5:
                    ded_style = "yellow"
                    indicator = "[yellow]?[/yellow]"
                elif clas.alertas:
                    ded_style = "yellow"
                    indicator = "[yellow]![/yellow]"
                else:
                    ded_style = "green"
                    indicator = "[green]V[/green]"

                table.add_row(
                    str(i),
                    comp.fecha.strftime("%d/%m"),
                    clas.concepto_descripcion[:30],
                    clas.categoria[:20],
                    f"${monto_orig:,.2f}",
                    f"[{ded_style}]${monto_ded:,.2f}[/{ded_style}]",
                    f"{clas.porcentaje_deducible:.0f}%",
                    indicator,
                )

                if i >= 200:  # Limitar a 200 filas
                    break
            if i >= 200:
                break

        # Totales
        pct = (total_deducible / total_original * 100) if total_original > 0 else 0
        no_ded = total_original - total_deducible
        table.add_row(
            "", "", "", f"[bold]{i} conceptos[/bold]",
            f"[bold]${total_original:,.2f}[/bold]",
            f"[bold green]${total_deducible:,.2f}[/bold green]",
            f"[bold]{pct:.0f}%[/bold]",
            "",
            end_section=True,
        )
        console.print(table)

        console.print(
            f"\n  [green]Deducible:[/green]     ${total_deducible:,.2f}"
            f"\n  [red]No deducible:[/red]  ${no_ded:,.2f}"
            f"\n  [dim]V=deducible  !=alertas  ?=baja confianza  X=no deducible[/dim]"
        )

    def _fiscal_resumen_categorias(self):
        console.print("\n[bold]Resumen por Categoría de Gasto[/bold]")
        year = IntPrompt.ask("Año", default=CURRENT_YEAR)

        recibidas = self._fiscal_get_recibidas(year)
        if not recibidas:
            console.print("[yellow]No hay facturas recibidas en este año.[/yellow]")
            return

        clasificador = self._get_clasificador()

        console.print(f"[dim]Analizando {len(recibidas)} facturas...[/dim]")
        resumen = clasificador.resumen_periodo(recibidas)

        # Tabla resumen por categoría
        table = Table(
            title=f"Deducciones por Categoría - {year}",
            title_style="bold magenta",
            border_style="magenta",
            show_lines=True,
        )
        table.add_column("Categoría", width=30)
        table.add_column("Conceptos", justify="center", width=10)
        table.add_column("Monto Total", justify="right", width=14)
        table.add_column("Deducible", justify="right", width=14)
        table.add_column("%", justify="right", width=7)
        table.add_column("Alertas", width=4, justify="center")

        # Ordenar por monto deducible descendente
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

            if pct >= 100:
                pct_style = "green"
            elif pct > 0:
                pct_style = "yellow"
            else:
                pct_style = "red"

            table.add_row(
                cat_data["nombre"][:30],
                str(cat_data["num_conceptos"]),
                f"${monto_orig:,.2f}",
                f"[{pct_style}]${monto_ded:,.2f}[/{pct_style}]",
                f"[{pct_style}]{pct:.0f}%[/{pct_style}]",
                f"[yellow]{n_alertas}[/yellow]" if n_alertas else "[dim]-[/dim]",
            )

        # Totales
        total_orig = float(resumen["total_original"])
        total_ded = float(resumen["total_deducible"])
        total_no_ded = float(resumen["total_no_deducible"])
        pct_global = resumen["porcentaje_global"]

        table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            f"[bold]${total_orig:,.2f}[/bold]",
            f"[bold green]${total_ded:,.2f}[/bold green]",
            f"[bold]{pct_global:.0f}%[/bold]",
            "",
            end_section=True,
        )
        console.print(table)

        console.print(f"\n  [red]No deducible:[/red] ${total_no_ded:,.2f}")

        if resumen["num_no_clasificados"] > 0:
            console.print(
                f"  [yellow]{resumen['num_no_clasificados']} conceptos con baja "
                f"confianza de clasificación[/yellow]"
            )

        # Mostrar alertas principales
        if resumen["alertas"]:
            console.print("\n[bold yellow]Alertas:[/bold yellow]")
            for alerta in resumen["alertas"][:5]:
                console.print(f"  [yellow]![/yellow] {alerta}")

    def _fiscal_sugerencias(self):
        console.print("\n[bold]Sugerencias de Optimización Fiscal[/bold]")
        year = IntPrompt.ask("Año", default=CURRENT_YEAR)

        recibidas = self._fiscal_get_recibidas(year)
        if not recibidas:
            console.print("[yellow]No hay facturas recibidas para analizar.[/yellow]")
            return

        # Calcular ingresos anuales
        ingresos = 0.0
        for month in range(1, 13):
            se = self.db.monthly_summary(year, month, "emitida")
            ingresos += se["ingresos"]

        clasificador = self._get_clasificador()

        console.print(f"[dim]Analizando {len(recibidas)} facturas...[/dim]")
        sugerencias = clasificador.generar_sugerencias(recibidas, ingresos)

        # Intentar sugerencias de IA si está configurada
        if self.config and self.config.ia and self.config.ia.api_key:
            try:
                from ..fiscal.ia_fiscal import AsistenteFiscal
                asistente = AsistenteFiscal(
                    api_key=self.config.ia.api_key,
                    regimen=self._get_regimen(),
                    actividad=(
                        self.config.contribuyente.actividad
                        if self.config.contribuyente else ""
                    ),
                    model=self.config.ia.model,
                )
                resumen = clasificador.resumen_periodo(recibidas)
                ia_sugerencias = asistente.generar_sugerencias(resumen, ingresos)
                sugerencias.extend(ia_sugerencias)
            except Exception as e:
                console.print(f"[dim]IA no disponible: {e}[/dim]")

        if not sugerencias:
            console.print("[green]No se encontraron sugerencias adicionales.[/green]")
            return

        console.print()
        for i, sug in enumerate(sugerencias, 1):
            prioridad_color = {1: "red", 2: "yellow", 3: "dim"}.get(sug.prioridad, "dim")
            ahorro_text = ""
            if sug.ahorro_estimado:
                ahorro_text = f" [green](ahorro estimado: ${float(sug.ahorro_estimado):,.2f})[/green]"

            console.print(Panel(
                f"{sug.descripcion}{ahorro_text}",
                title=f"[{prioridad_color}]{i}. {sug.titulo}[/{prioridad_color}]",
                border_style=prioridad_color,
                width=80,
            ))

        console.print(
            "\n[dim]* Estas sugerencias son educativas y no sustituyen "
            "asesoría fiscal profesional.[/dim]"
        )

    def _fiscal_consultar_cfdi(self):
        uuid_input = Prompt.ask("UUID del CFDI a analizar")
        if not uuid_input:
            return

        prefix = uuid_input.upper().strip()
        rows = self.conn.execute(
            "SELECT uuid FROM comprobantes WHERE uuid LIKE ? LIMIT 5",
            (f"{prefix}%",),
        ).fetchall()

        if not rows:
            console.print(f"[yellow]No se encontró CFDI con UUID '{prefix}...'[/yellow]")
            return
        if len(rows) > 1:
            console.print("[yellow]Múltiples coincidencias:[/yellow]")
            for r in rows:
                console.print(f"  {r['uuid']}")
            return

        cfdi = self.db.get_by_uuid(rows[0]["uuid"])
        if not cfdi:
            return

        if not cfdi.conceptos:
            console.print("[yellow]Este CFDI no tiene conceptos (datos de Metadata).[/yellow]")
            return

        clasificador = self._get_clasificador()
        resumen = clasificador.resumen_deduccion(cfdi)

        # Mostrar info del CFDI
        tipo_color = "green" if cfdi.tipo == "emitida" else "cyan"
        console.print(Panel(
            f"[bold]{cfdi.nombre_emisor}[/bold] → [bold]{cfdi.nombre_receptor}[/bold]\n"
            f"Fecha: {cfdi.fecha.strftime('%d/%m/%Y')}  |  "
            f"Total: [bold]${float(cfdi.total):,.2f}[/bold]  |  "
            f"Forma pago: {cfdi.forma_pago or 'N/A'}",
            title=f"CFDI {cfdi.uuid[:8]}...",
            border_style=tipo_color,
        ))

        # Tabla de conceptos con clasificación
        table = Table(
            title="Análisis de Deducibilidad",
            title_style="bold magenta",
            border_style="magenta",
            show_lines=True,
        )
        table.add_column("#", width=3, style="dim")
        table.add_column("Concepto", width=30)
        table.add_column("Clave SAT", width=10)
        table.add_column("Categoría", width=18)
        table.add_column("Monto", justify="right", width=12)
        table.add_column("Deducible", justify="right", width=12)
        table.add_column("%", justify="right", width=6)

        for i, clas in enumerate(resumen["clasificaciones"], 1):
            ded_style = "green" if clas.es_deducible else "red"
            table.add_row(
                str(i),
                clas.concepto_descripcion[:30],
                clas.clave_prod_serv[:10],
                clas.categoria[:18],
                f"${float(clas.monto_original):,.2f}",
                f"[{ded_style}]${float(clas.monto_deducible):,.2f}[/{ded_style}]",
                f"{clas.porcentaje_deducible:.0f}%",
            )

        pct = resumen["porcentaje_deducible"]
        table.add_row(
            "", "", "", "[bold]TOTAL[/bold]",
            f"[bold]${float(resumen['total_original']):,.2f}[/bold]",
            f"[bold green]${float(resumen['total_deducible']):,.2f}[/bold green]",
            f"[bold]{pct:.0f}%[/bold]",
            end_section=True,
        )
        console.print(table)

        # Detalle de cada clasificación
        for i, clas in enumerate(resumen["clasificaciones"], 1):
            console.print(f"\n  [bold]Concepto {i}:[/bold] {clas.concepto_descripcion}")
            console.print(f"    Fundamento: {clas.fundamento_legal}")
            if clas.requisitos:
                console.print(f"    Requisitos: {', '.join(clas.requisitos)}")
            for alerta in clas.alertas:
                console.print(f"    [yellow]! {alerta}[/yellow]")

        # Alertas generales
        if resumen["alertas"]:
            console.print("\n[bold yellow]Alertas del comprobante:[/bold yellow]")
            for alerta in resumen["alertas"]:
                console.print(f"  [yellow]![/yellow] {alerta}")
