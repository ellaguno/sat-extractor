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
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ..db.connection import get_connection
from ..db.repository import Repository
from ..export.excel import ExcelExporter, MESES
from ..fiscal import calcular_impuestos_mensuales, isr_label
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


# ── Pantalla de Configuración ────────────────────────────────────────────


def _regimenes_disponibles() -> list[tuple[str, str]]:
    """Carga regímenes disponibles desde el TOML de reglas fiscales."""
    try:
        from ..fiscal.clasificador import _cargar_reglas
        reglas = _cargar_reglas()
        result = []
        for code, data in reglas.get("regimenes", {}).items():
            nombre = data.get("nombre", code)
            result.append((code, f"{code} — {nombre}"))
        result.sort(key=lambda x: x[0])
        return result
    except Exception:
        return [
            ("601", "601 — General de Ley Personas Morales"),
            ("603", "603 — PM con Fines no Lucrativos"),
            ("612", "612 — PFAE"),
            ("625", "625 — Plataformas Tecnológicas"),
            ("626", "626 — RESICO"),
        ]


_ACTIVIDADES_PLATAFORMA = [
    ("transporte", "Transporte (Uber, Didi, etc.)"),
    ("alimentos", "Entrega de alimentos (Rappi, UberEats, etc.)"),
    ("hospedaje", "Hospedaje (Airbnb, Booking, etc.)"),
    ("venta_bienes", "Venta de bienes (MercadoLibre, Amazon, etc.)"),
    ("otros", "Otros servicios"),
]


class ConfigScreen(Screen):
    """Pantalla para editar la configuración de la aplicación."""

    BINDINGS = [
        Binding("escape", "go_back", "Volver"),
    ]

    CSS = """
    #config-container {
        padding: 1 2;
    }
    .config-field {
        margin-bottom: 1;
    }
    .config-label {
        color: $text-muted;
        margin-bottom: 0;
    }
    #btn-guardar {
        margin-top: 1;
        width: 30;
    }
    """

    def __init__(self, config):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        cfg = self.config

        regimenes = _regimenes_disponibles()
        reg_options = [(label, code) for code, label in regimenes]
        reg_default = cfg.contribuyente.regimen if cfg.contribuyente else "612"

        act_plat_options = [(label, code) for code, label in _ACTIVIDADES_PLATAFORMA]
        act_plat_default = (
            cfg.contribuyente.actividad_plataforma
            if cfg.contribuyente and cfg.contribuyente.actividad_plataforma
            else "otros"
        )

        yield Header()
        with VerticalScroll(id="config-container"):
            yield Static("[bold]Configuración[/bold]\n")

            with TabbedContent():
                with TabPane("Contribuyente", id="tab-contrib"):
                    yield Static("Nombre / Razón social:", classes="config-label")
                    yield Input(
                        value=cfg.contribuyente.nombre if cfg.contribuyente else "",
                        placeholder="Ej: Juan Pérez López",
                        id="cfg-nombre",
                    )
                    yield Static("Régimen fiscal:", classes="config-label")
                    yield Select(
                        reg_options,
                        value=reg_default,
                        id="cfg-regimen",
                        allow_blank=False,
                    )
                    yield Static("Actividad económica:", classes="config-label")
                    yield Input(
                        value=cfg.contribuyente.actividad if cfg.contribuyente else "",
                        placeholder="Ej: Desarrollo de software",
                        id="cfg-actividad",
                    )
                    yield Static("Coeficiente de utilidad (solo PM 601):", classes="config-label")
                    yield Input(
                        value=str(cfg.contribuyente.coeficiente_utilidad) if cfg.contribuyente and cfg.contribuyente.coeficiente_utilidad else "",
                        placeholder="Ej: 0.35",
                        id="cfg-coeficiente",
                    )
                    yield Static("Actividad plataforma (solo 625):", classes="config-label")
                    yield Select(
                        act_plat_options,
                        value=act_plat_default,
                        id="cfg-act-plataforma",
                        allow_blank=False,
                    )

                with TabPane("SAT / FIEL", id="tab-fiel"):
                    yield Static("RFC:", classes="config-label")
                    yield Input(
                        value=cfg.sat.rfc if cfg.sat else "",
                        placeholder="Ej: XAXX010101000",
                        id="cfg-rfc",
                    )
                    yield Static("Ruta certificado (.cer):", classes="config-label")
                    yield Input(
                        value=str(cfg.fiel.cer_path) if cfg.fiel and str(cfg.fiel.cer_path) else "",
                        placeholder="/ruta/a/certificado.cer",
                        id="cfg-cer",
                    )
                    yield Static("Ruta llave privada (.key):", classes="config-label")
                    yield Input(
                        value=str(cfg.fiel.key_path) if cfg.fiel and str(cfg.fiel.key_path) else "",
                        placeholder="/ruta/a/llave.key",
                        id="cfg-key",
                    )
                    yield Static("Contraseña FIEL:", classes="config-label")
                    yield Input(
                        value=cfg.fiel.password or "" if cfg.fiel else "",
                        placeholder="Contraseña de la llave privada",
                        password=True,
                        id="cfg-password",
                    )

                with TabPane("Directorios", id="tab-dirs"):
                    yield Static("Base de datos:", classes="config-label")
                    yield Input(
                        value=str(cfg.database.path) if cfg.database else "~/satextractor.db",
                        placeholder="~/satextractor.db",
                        id="cfg-db-path",
                    )
                    yield Static("Directorio exportación Excel:", classes="config-label")
                    yield Input(
                        value=str(cfg.export.output_dir) if cfg.export else "~/reportes_sat",
                        placeholder="~/reportes_sat",
                        id="cfg-export-dir",
                    )

                with TabPane("IA (opcional)", id="tab-ia"):
                    yield Static("Proveedor:", classes="config-label")
                    yield Select(
                        [
                            ("Anthropic (Claude)", "anthropic"),
                            ("DeepSeek", "deepseek"),
                            ("OpenRouter (multi-modelo)", "openrouter"),
                        ],
                        value=cfg.ia.provider if cfg.ia else "anthropic",
                        id="cfg-provider",
                        allow_blank=False,
                    )
                    yield Static("API Key:", classes="config-label")
                    yield Input(
                        value=cfg.ia.api_key if cfg.ia else "",
                        placeholder="sk-ant-... / sk-or-... / sk-...",
                        password=True,
                        id="cfg-api-key",
                    )
                    yield Static("Modelo:", classes="config-label")
                    yield Input(
                        value=cfg.ia.model if cfg.ia else "claude-sonnet-4-6",
                        placeholder="claude-sonnet-4-6 / deepseek-chat / anthropic/claude-sonnet-4-6",
                        id="cfg-model",
                    )
                    yield Static("URL base (solo OpenRouter/custom):", classes="config-label")
                    yield Input(
                        value=cfg.ia.base_url if cfg.ia else "",
                        placeholder="https://openrouter.ai/api/v1",
                        id="cfg-base-url",
                    )
                    yield Static("Días de caché clasificaciones:", classes="config-label")
                    yield Input(
                        value=str(cfg.ia.cache_dias) if cfg.ia else "90",
                        placeholder="90",
                        id="cfg-cache-dias",
                        type="integer",
                    )

            yield Button("Guardar configuración", id="btn-guardar", variant="success")

        yield Footer()

    @on(Button.Pressed, "#btn-guardar")
    def on_save(self, event: Button.Pressed) -> None:
        """Guarda la configuración editada."""
        from ..config import (
            Config, FielConfig, SATConfig, DatabaseConfig,
            ExportConfig, ContribuyenteConfig, IAConfig,
        )

        try:
            regimen = self.query_one("#cfg-regimen", Select).value
            if regimen is Select.BLANK:
                regimen = "612"

            act_plat = self.query_one("#cfg-act-plataforma", Select).value
            if act_plat is Select.BLANK:
                act_plat = "otros"

            coef_str = self.query_one("#cfg-coeficiente", Input).value.strip()
            coeficiente = float(coef_str) if coef_str else 0.0

            cer_path_str = self.query_one("#cfg-cer", Input).value.strip()
            key_path_str = self.query_one("#cfg-key", Input).value.strip()

            new_config = Config(
                fiel=FielConfig(
                    cer_path=Path(cer_path_str).expanduser() if cer_path_str else Path(""),
                    key_path=Path(key_path_str).expanduser() if key_path_str else Path(""),
                    password=self.query_one("#cfg-password", Input).value or None,
                ),
                sat=SATConfig(
                    rfc=self.query_one("#cfg-rfc", Input).value.strip().upper(),
                ),
                database=DatabaseConfig(
                    path=Path(self.query_one("#cfg-db-path", Input).value.strip() or "~/satextractor.db").expanduser(),
                ),
                export=ExportConfig(
                    output_dir=Path(self.query_one("#cfg-export-dir", Input).value.strip() or "~/reportes_sat").expanduser(),
                ),
                contribuyente=ContribuyenteConfig(
                    nombre=self.query_one("#cfg-nombre", Input).value.strip(),
                    regimen=str(regimen),
                    actividad=self.query_one("#cfg-actividad", Input).value.strip(),
                    coeficiente_utilidad=coeficiente,
                    actividad_plataforma=str(act_plat),
                ),
                ia=IAConfig(
                    provider=str(self.query_one("#cfg-provider", Select).value or "anthropic"),
                    api_key=self.query_one("#cfg-api-key", Input).value.strip(),
                    model=self.query_one("#cfg-model", Input).value.strip() or "claude-sonnet-4-6",
                    base_url=self.query_one("#cfg-base-url", Input).value.strip(),
                    cache_dias=int(self.query_one("#cfg-cache-dias", Input).value or 90),
                ),
                _config_path=self.config._config_path,
            )

            saved_path = new_config.save()

            # Actualizar config en vivo en la app
            self.app.config = new_config

            # Recrear exporter con nuevo régimen
            new_regimen = new_config.contribuyente.regimen
            self.app.exporter = ExcelExporter(
                self.app.db, regimen=new_regimen, config=new_config,
            )

            self.notify(
                f"Configuración guardada en {saved_path}",
                title="Guardado",
                timeout=6,
            )
        except Exception as e:
            self.notify(f"Error: {e}", title="Error", severity="error", timeout=8)

    def action_go_back(self) -> None:
        self.app.pop_screen()


# ── App Principal ────────────────────────────────────────────────────────


class SATExtractorApp(App):
    """Aplicación principal SAT CFDI Extractor."""

    TITLE = "SAT CFDI Extractor"
    SUB_TITLE = "Gestión de facturas electrónicas"

    CSS = """
    Screen {
        background: $surface;
    }

    #info-bar {
        width: 100%;
        height: 1;
        padding: 0 1;
        background: $primary-background;
        color: $text;
    }

    #menu-bar {
        width: 100%;
        height: 1;
        padding: 0;
        background: $panel;
    }

    .menu-btn {
        min-width: 8;
        height: 1;
        margin: 0;
        padding: 0 1;
        border: none;
    }

    #content-scroll {
        height: 1fr;
    }

    #content-title {
        margin: 0 1;
        text-style: bold;
        color: $accent;
    }

    #content-notes {
        color: $text-muted;
        margin: 0 1;
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
        margin: 0 1;
    }

    VerticalScroll {
        height: 100%;
    }

    .inline-input {
        margin: 0 1;
    }

    .inline-label {
        margin: 0 1;
        color: $text-muted;
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
        Binding("c", "config", "Config"),
        Binding("left", "menu_prev", "←", show=False),
        Binding("right", "menu_next", "→", show=False),
    ]

    _MENU_IDS = [
        "btn-dashboard", "btn-month", "btn-search", "btn-top",
        "btn-export", "btn-fiscal", "btn-download", "btn-import",
        "btn-config", "btn-quit",
    ]

    def __init__(self, db_path: Path, config=None):
        super().__init__()
        self.conn = get_connection(db_path)
        self.db = Repository(self.conn)
        self.config = config
        regimen = "612"
        if config and config.contribuyente:
            regimen = config.contribuyente.regimen
        self.exporter = ExcelExporter(self.db, regimen=regimen, config=config)
        self._current_view = None  # track active view for row handlers
        self._view_year = CURRENT_YEAR
        self._month_uuids_emi: list[str] = []
        self._month_uuids_rec: list[str] = []
        self._search_uuids: list[str] = []
        self._fiscal_uuids: list[str] = []

    def _build_info_text(self) -> str:
        """Construye la línea de info: nombre │ RFC │ fecha │ BD stats."""
        parts = []
        if self.config:
            nombre = self.config.contribuyente.nombre if self.config.contribuyente else ""
            rfc = self.config.sat.rfc if self.config.sat else ""
            if nombre:
                parts.append(f"[bold]{nombre}[/bold]")
            parts.append(f"RFC: {rfc or '---'}")
        else:
            parts.append("RFC: ---")
        parts.append(date.today().strftime("%d/%m/%Y"))
        n_emi = self.db.count(tipo="emitida")
        n_rec = self.db.count(tipo="recibida")
        total = n_emi + n_rec
        if total == 0:
            parts.append("BD vacía")
        else:
            parts.append(f"BD: {total} CFDIs ({n_emi} E, {n_rec} R)")
        return "  │  ".join(parts)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._build_info_text(), id="info-bar")

        with Horizontal(id="menu-bar"):
            yield Button("Dashboard", id="btn-dashboard", variant="primary", classes="menu-btn")
            yield Button("Mes", id="btn-month", classes="menu-btn")
            yield Button("Buscar", id="btn-search", classes="menu-btn")
            yield Button("Top", id="btn-top", classes="menu-btn")
            yield Button("Excel", id="btn-export", classes="menu-btn")
            yield Button("Fiscal", id="btn-fiscal", classes="menu-btn")
            yield Button("Descargar", id="btn-download", classes="menu-btn")
            yield Button("Importar", id="btn-import", classes="menu-btn")
            yield Button("Config", id="btn-config", classes="menu-btn")
            yield Button("Salir", id="btn-quit", variant="error", classes="menu-btn")

        yield VerticalScroll(id="content-scroll")
        yield Static(id="status-bar")

    async def on_mount(self) -> None:
        is_configured = (
            self.config
            and self.config.sat
            and self.config.sat.rfc
        )
        if is_configured:
            await self._show_dashboard(CURRENT_YEAR)
        else:
            self.push_screen(ConfigScreen(self.config))

    def _refresh_info_bar(self) -> None:
        """Actualiza la línea de info tras cambio de configuración."""
        try:
            self.query_one("#info-bar", Static).update(self._build_info_text())
        except Exception:
            pass

    async def _clear_content(self) -> None:
        """Limpia el content area para nueva vista."""
        scroll = self.query_one("#content-scroll", VerticalScroll)
        await scroll.remove_children()

    # ── Navegación de menú con flechas ──

    def action_menu_prev(self) -> None:
        self._move_menu_focus(-1)

    def action_menu_next(self) -> None:
        self._move_menu_focus(1)

    def _move_menu_focus(self, direction: int) -> None:
        focused = self.focused
        if focused and focused.id in self._MENU_IDS:
            idx = self._MENU_IDS.index(focused.id)
            new_idx = (idx + direction) % len(self._MENU_IDS)
        elif direction > 0:
            new_idx = 0
        else:
            new_idx = len(self._MENU_IDS) - 1
        try:
            self.query_one(f"#{self._MENU_IDS[new_idx]}", Button).focus()
        except Exception:
            pass

    @on(Button.Pressed, "#menu-bar Button")
    def on_menu_button(self, event: Button.Pressed) -> None:
        btn_actions = {
            "btn-dashboard": self.action_dashboard,
            "btn-month": self.action_month,
            "btn-search": self.action_search,
            "btn-top": self.action_top,
            "btn-export": self.action_export,
            "btn-fiscal": self.action_fiscal,
            "btn-download": self.action_do_download,
            "btn-import": self.action_do_import,
            "btn-config": self.action_config,
            "btn-quit": self.exit,
        }
        action = btn_actions.get(event.button.id)
        if action:
            action()

    # ── Vistas inline en content area ──

    async def _show_dashboard(self, year: int) -> None:
        """Dashboard anual inline."""
        await self._clear_content()
        self._current_view = "dashboard"
        self._view_year = year
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static(f"[bold blue]Dashboard {year}[/bold blue]", id="content-title"))
        scroll.mount(DataTable(id="content-table"))
        scroll.mount(Static(id="content-notes"))
        self._load_dashboard_data(year)

    @work(thread=True)
    def _load_dashboard_data(self, year: int) -> None:
        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        fiscal = calcular_impuestos_mensuales(self.db, year, regimen, config=self.config)

        table = self.query_one("#content-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True

        for label in ["Mes", "Emitidas", "Facturado", "Recibidas", "Gastos",
                       "IVA x Pagar", "ISR Prov.", "Balance"]:
            table.add_column(label, key=label)

        grand_emi = grand_rec = grand_iva = grand_isr = 0.0

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
                key=str(month),
            )

        table.add_row(
            "TOTAL", "", _fmt(grand_emi), "", _fmt(grand_rec),
            _fmt(grand_iva), _fmt(grand_isr), _fmt(grand_emi - grand_rec),
            key="total",
        )

        self.query_one("#content-notes", Static).update(
            f"IVA x Pagar = cobrado - acreditable - retenido  │  {isr_label(regimen)}  │  "
            "[dim]Enter en un mes → detalle[/dim]"
        )

    async def _show_month(self, year: int, month: int) -> None:
        """Detalle mensual inline."""
        await self._clear_content()
        self._current_view = "month"
        self._view_year = year
        self._month_uuids_emi = []
        self._month_uuids_rec = []
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static(
            f"[bold blue]{MESES[month]} {year}[/bold blue]",
            id="content-title",
        ))
        scroll.mount(Static(id="month-summary"))
        scroll.mount(DataTable(id="month-emitidas"))
        scroll.mount(DataTable(id="month-recibidas"))
        self._load_month_data(year, month)

    @work(thread=True)
    def _load_month_data(self, year: int, month: int) -> None:
        fecha_inicio = date(year, month, 1)
        fecha_fin = _next_month(year, month)

        se = self.db.monthly_summary(year, month, "emitida")
        sr = self.db.monthly_summary(year, month, "recibida")

        self.query_one("#month-summary", Static).update(
            f"Emitidas: {se['num_cfdis']}  {_fmt(se['total'])}    "
            f"Recibidas: {sr['num_cfdis']}  {_fmt(sr['total'])}  "
            "[dim]Enter → detalle CFDI[/dim]"
        )

        emitidas = self.db.search(
            tipo="emitida", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, limit=500,
        )
        self._month_uuids_emi = [c.uuid for c in emitidas]
        self._fill_cfdi_table("#month-emitidas", emitidas, "Emitidas")

        recibidas = self.db.search(
            tipo="recibida", fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, limit=500,
        )
        self._month_uuids_rec = [c.uuid for c in recibidas]
        self._fill_cfdi_table("#month-recibidas", recibidas, "Recibidas")

    def _fill_cfdi_table(self, table_id: str, cfdis: list, label: str) -> None:
        table = self.query_one(table_id, DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        for col in ["#", "Fecha", "Contraparte", "Concepto", "Total", "Estado", "UUID"]:
            table.add_column(col, key=f"{table_id}_{col}")

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
                str(i), c.fecha.strftime("%d/%m/%Y"),
                (contraparte or "")[:30], concepto[:35],
                _fmt(monto), c.estado[:3], c.uuid[:8],
            )

        table.add_row("", "", "", f"{len(cfdis)} CFDIs", _fmt(total_monto), "", "")

    async def _show_search(self) -> None:
        """Búsqueda inline."""
        await self._clear_content()
        self._current_view = "search"
        self._search_uuids = []
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static("[bold]Buscar CFDIs[/bold]", id="content-title"))
        scroll.mount(Input(
            placeholder="RFC o nombre (mín. 3 caracteres) — Enter para buscar",
            id="search-input", classes="inline-input",
        ))
        scroll.mount(Static(id="search-status"))
        scroll.mount(DataTable(id="search-results"))

    async def _show_top(self, year: int) -> None:
        """Top entidades inline."""
        await self._clear_content()
        self._current_view = "top"
        self._view_year = year
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static(
            f"[bold blue]Top Entidades - {year}[/bold blue]", id="content-title",
        ))
        scroll.mount(DataTable(id="top-proveedores"))
        scroll.mount(DataTable(id="top-clientes"))
        self._load_top_data(year)

    @work(thread=True)
    def _load_top_data(self, year: int) -> None:
        fecha_inicio = date(year, 1, 1)
        fecha_fin = date(year + 1, 1, 1)
        conn = self.db.conn

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
            t_prov.add_column(col, key=f"p_{col}")
        for i, r in enumerate(rows, 1):
            t_prov.add_row(
                str(i), r["rfc_emisor"], (r["nombre_emisor"] or "")[:35],
                str(r["n"]), _fmt(r["total"]),
            )

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

    async def _show_fiscal_menu(self) -> None:
        """Submenú fiscal inline."""
        await self._clear_content()
        self._current_view = "fiscal_menu"
        scroll = self.query_one("#content-scroll", VerticalScroll)
        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        scroll.mount(Static(
            f"[bold magenta]Análisis Fiscal Inteligente[/bold magenta]  │  "
            f"Régimen: {regimen} — {isr_label(regimen)}",
            id="content-title",
        ))
        scroll.mount(Button("1. Clasificar deducciones del periodo", id="fiscal-btn-1", classes="menu-btn"))
        scroll.mount(Button("2. Resumen por categoría de gasto", id="fiscal-btn-2", classes="menu-btn"))
        scroll.mount(Button("3. ISR e IVA estimados a declarar", id="fiscal-btn-3", classes="menu-btn"))
        scroll.mount(Button("4. Sugerencias de optimización", id="fiscal-btn-4", classes="menu-btn"))
        scroll.mount(Button("5. Consultar deducibilidad de un CFDI", id="fiscal-btn-5", classes="menu-btn"))

    async def _show_fiscal_impuestos(self, year: int) -> None:
        """ISR/IVA estimados inline."""
        await self._clear_content()
        self._current_view = "fiscal_impuestos"
        self._view_year = year
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static(
            f"[bold magenta]Impuestos Provisionales - {year}[/bold magenta]",
            id="content-title",
        ))
        scroll.mount(Static("Calculando...", id="imp-loading"))
        scroll.mount(DataTable(id="imp-table"))
        scroll.mount(Static(id="imp-detail"))
        scroll.mount(Static(id="imp-notes"))
        self._load_fiscal_impuestos(year)

    @work(thread=True)
    def _load_fiscal_impuestos(self, year: int) -> None:
        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        fiscal = calcular_impuestos_mensuales(self.db, year, regimen, config=self.config)

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

            if ingresos <= 0 and ded_reales <= 0:
                table.add_row(MESES[m], "-", "-", "-", "-", "-", "-")
                continue

            table.add_row(
                MESES[m], _fmt(ingresos), _fmt(ded_reales), _fmt(no_ded),
                _fmt(iva_pagar), _fmt(isr_prov), _fmt(total_pagar),
            )

        grand_total = grand["iva"] + grand["isr"]
        table.add_row(
            "TOTAL", _fmt(grand["ing"]), _fmt(grand["ded"]), _fmt(grand["no_ded"]),
            _fmt(grand["iva"]), _fmt(grand["isr"]), _fmt(grand_total),
        )

        self.query_one("#imp-loading", Static).update("")

        last_fi = None
        for fi in reversed(fiscal):
            if fi["ingresos_mes"] > 0 or fi["deducciones_mes"] > 0:
                last_fi = fi
                break

        if last_fi:
            m = last_fi["mes"]
            detail = (
                f"\nDetalle {MESES[m]} {year}:\n"
                f"  IVA cobrado:            {_fmt(last_fi['iva_cobrado']):>14}\n"
                f"  IVA acreditable:        {_fmt(last_fi['iva_acreditable']):>14}  (solo de gastos deducibles)\n"
                f"  IVA retenido:           {_fmt(last_fi['iva_retenido']):>14}\n"
                f"  IVA a pagar:            {_fmt(last_fi['iva_a_pagar']):>14}\n\n"
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
            "* IVA acreditable = solo IVA de gastos clasificados como deducibles\n"
            "* ISR = Art.96 LISR sobre (ingresos acum. - deducciones reales acum.)\n"
            "* No incluye depreciaciones de inversiones, PTU ni pérdidas anteriores"
        )

    async def _show_fiscal_clasificacion(self, year: int, month: int | None) -> None:
        """Clasificación de deducciones inline."""
        await self._clear_content()
        self._current_view = "fiscal_clasificacion"
        self._fiscal_uuids = []
        scroll = self.query_one("#content-scroll", VerticalScroll)
        titulo = f"{MESES[month]} {year}" if month else str(year)
        scroll.mount(Static(
            f"[bold magenta]Deducciones - {titulo}[/bold magenta]",
            id="content-title",
        ))
        scroll.mount(Static("Clasificando...", id="fiscal-loading"))
        scroll.mount(DataTable(id="fiscal-table"))
        scroll.mount(Static(id="fiscal-totals"))
        self._load_fiscal_clasificacion(year, month)

    @work(thread=True)
    def _load_fiscal_clasificacion(self, year: int, month: int | None) -> None:
        if month:
            fecha_inicio = date(year, month, 1)
            fecha_fin = _next_month(year, month)
        else:
            fecha_inicio = date(year, 1, 1)
            fecha_fin = date(year + 1, 1, 1)

        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(self.db.search(
                tipo="recibida", tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                estado="Vigente", limit=5000,
            ))

        loading = self.query_one("#fiscal-loading", Static)
        if not gastos:
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

        total_original = total_deducible = 0.0
        i = 0
        for comp in gastos:
            if not comp.conceptos:
                continue
            signo = -1.0 if comp.tipo_comprobante == "E" else 1.0
            clasificaciones = clasificador.clasificar_comprobante(comp)
            for clas in clasificaciones:
                i += 1
                monto_orig = float(clas.monto_original) * signo
                monto_ded = float(clas.monto_deducible) * signo
                total_original += monto_orig
                total_deducible += monto_ded

                if comp.tipo_comprobante == "E":
                    indicator = "NC"
                elif not clas.es_deducible:
                    indicator = "X"
                elif clas.alertas:
                    indicator = "!"
                else:
                    indicator = "V"

                table.add_row(
                    str(i), comp.fecha.strftime("%d/%m"),
                    clas.concepto_descripcion[:30], clas.categoria[:20],
                    _fmt(monto_orig), _fmt(monto_ded),
                    f"{clas.porcentaje_deducible:.0f}%", indicator,
                )
                self._fiscal_uuids.append(comp.uuid)
                if i >= 200:
                    break
            if i >= 200:
                break

        loading.update("")
        pct = (total_deducible / total_original * 100) if total_original > 0 else 0
        self.query_one("#fiscal-totals", Static).update(
            f"Deducible: {_fmt(total_deducible)} ({pct:.0f}%)  │  "
            f"No deducible: {_fmt(total_original - total_deducible)}  │  "
            f"{i} conceptos  │  V=deducible  !=alertas  X=no ded.  NC=nota crédito"
        )

    async def _show_fiscal_categorias(self, year: int) -> None:
        """Resumen por categoría inline."""
        await self._clear_content()
        self._current_view = "fiscal_categorias"
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static(
            f"[bold magenta]Deducciones por Categoría - {year}[/bold magenta]",
            id="content-title",
        ))
        scroll.mount(Static("Analizando...", id="cat-loading"))
        scroll.mount(DataTable(id="cat-table"))
        scroll.mount(Static(id="cat-totals"))
        scroll.mount(Static(id="cat-alertas"))
        self._load_fiscal_categorias(year)

    @work(thread=True)
    def _load_fiscal_categorias(self, year: int) -> None:
        fecha_inicio = date(year, 1, 1)
        fecha_fin = date(year + 1, 1, 1)
        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(self.db.search(
                tipo="recibida", tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                estado="Vigente", limit=5000,
            ))

        loading = self.query_one("#cat-loading", Static)
        if not gastos:
            loading.update("[yellow]No hay facturas recibidas.[/yellow]")
            return

        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        clasificador = ClasificadorDeducciones(regimen, self.db)
        resumen = clasificador.resumen_periodo(gastos)

        table = self.query_one("#cat-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        for col in ["Categoría", "Conceptos", "Monto Total", "Deducible", "%", "Alertas"]:
            table.add_column(col, key=col)

        cats_sorted = sorted(
            resumen["por_categoria"].items(),
            key=lambda x: float(x[1]["monto_deducible"]), reverse=True,
        )
        for cat_id, cat_data in cats_sorted:
            table.add_row(
                cat_data["nombre"][:30], str(cat_data["num_conceptos"]),
                _fmt(float(cat_data["monto_original"])),
                _fmt(float(cat_data["monto_deducible"])),
                f"{cat_data['porcentaje']:.0f}%",
                str(len(cat_data["alertas"])) if cat_data["alertas"] else "-",
            )

        loading.update("")
        self.query_one("#cat-totals", Static).update(
            f"Total: {_fmt(float(resumen['total_original']))}  │  "
            f"Deducible: {_fmt(float(resumen['total_deducible']))} ({resumen['porcentaje_global']:.0f}%)  │  "
            f"No deducible: {_fmt(float(resumen['total_no_deducible']))}"
        )
        if resumen["alertas"]:
            self.query_one("#cat-alertas", Static).update(
                "Alertas: " + " │ ".join(resumen["alertas"][:5])
            )

    async def _show_fiscal_sugerencias(self, year: int) -> None:
        """Sugerencias de optimización inline."""
        await self._clear_content()
        self._current_view = "fiscal_sugerencias"
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.mount(Static(
            f"[bold magenta]Sugerencias de Optimización - {year}[/bold magenta]",
            id="content-title",
        ))
        scroll.mount(Static("Analizando...", id="sug-loading"))
        scroll.mount(Static(id="sug-content"))
        self._load_fiscal_sugerencias(year)

    @work(thread=True)
    def _load_fiscal_sugerencias(self, year: int) -> None:
        fecha_inicio = date(year, 1, 1)
        fecha_fin = date(year + 1, 1, 1)
        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(self.db.search(
                tipo="recibida", tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                estado="Vigente", limit=5000,
            ))

        loading = self.query_one("#sug-loading", Static)
        if not gastos:
            loading.update("[yellow]No hay facturas para analizar.[/yellow]")
            return

        ingresos = 0.0
        for month in range(1, 13):
            se = self.db.monthly_summary(year, month, "emitida")
            ingresos += se["ingresos"]

        regimen = "612"
        if self.config and self.config.contribuyente:
            regimen = self.config.contribuyente.regimen
        clasificador = ClasificadorDeducciones(regimen, self.db)
        sugerencias = clasificador.generar_sugerencias(gastos, ingresos)

        if self.config and self.config.ia and self.config.ia.api_key:
            try:
                from ..fiscal.ia_fiscal import AsistenteFiscal
                asistente = AsistenteFiscal(
                    api_key=self.config.ia.api_key, regimen=regimen,
                    actividad=(self.config.contribuyente.actividad
                               if self.config.contribuyente else ""),
                    model=self.config.ia.model, provider=self.config.ia.provider,
                    base_url=self.config.ia.base_url,
                )
                resumen = clasificador.resumen_periodo(gastos)
                sugerencias.extend(asistente.generar_sugerencias(resumen, ingresos))
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
        lines.append("* Sugerencias educativas, no sustituyen asesoría fiscal profesional.")
        self.query_one("#sug-content", Static).update("\n".join(lines))

    # ── Event handlers para DataTable rows en vistas inline ──

    @on(DataTable.RowSelected, "#content-table")
    async def on_content_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._current_view != "dashboard":
            return
        row_key = event.row_key.value
        if row_key and row_key != "total":
            try:
                month = int(row_key)
                await self._show_month(self._view_year, month)
            except ValueError:
                pass

    @on(DataTable.RowSelected, "#month-emitidas")
    def on_emi_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._month_uuids_emi):
            self.push_screen(CfdiDetailScreen(self.db, self._month_uuids_emi[idx]))

    @on(DataTable.RowSelected, "#month-recibidas")
    def on_rec_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._month_uuids_rec):
            self.push_screen(CfdiDetailScreen(self.db, self._month_uuids_rec[idx]))

    @on(Input.Submitted, "#search-input")
    def on_search_submit(self, event: Input.Submitted) -> None:
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
        self._search_uuids = []

        if not results:
            status.update("[yellow]No se encontraron resultados.[/yellow]")
            return

        status.update(f"[green]{len(results)} resultado(s)[/green]")
        table.cursor_type = "row"
        for col in ["#", "Fecha", "Tipo", "Contraparte", "Concepto", "Total", "UUID"]:
            table.add_column(col, key=col)

        self._search_uuids = [c.uuid for c in results]
        for i, c in enumerate(results, 1):
            contraparte = (
                c.nombre_receptor or c.rfc_receptor
                if c.tipo == "emitida"
                else c.nombre_emisor or c.rfc_emisor
            )
            concepto = c.conceptos[0].descripcion[:30] if c.conceptos else ""
            monto = float(c.total) if c.total else 0
            table.add_row(
                str(i), c.fecha.strftime("%d/%m"),
                c.tipo[:3].upper(), (contraparte or "")[:28],
                concepto, _fmt(monto), c.uuid[:8],
            )

    @on(DataTable.RowSelected, "#search-results")
    def on_search_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._search_uuids):
            self.push_screen(CfdiDetailScreen(self.db, self._search_uuids[idx]))

    @on(DataTable.RowSelected, "#fiscal-table")
    def on_fiscal_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._fiscal_uuids):
            self.push_screen(CfdiDetailScreen(self.db, self._fiscal_uuids[idx]))

    # ── Fiscal sub-menu button handlers ──

    @on(Button.Pressed, "#fiscal-btn-1")
    def on_fiscal_1(self, event: Button.Pressed) -> None:
        async def on_period(result):
            if result:
                year, month = result
                await self._show_fiscal_clasificacion(year, month)
        self.push_screen(YearMonthInputScreen("Clasificar Deducciones"), on_period)

    @on(Button.Pressed, "#fiscal-btn-2")
    def on_fiscal_2(self, event: Button.Pressed) -> None:
        async def on_year(year):
            if year:
                await self._show_fiscal_categorias(year)
        self.push_screen(YearInputScreen("Resumen por Categoría - Año"), on_year)

    @on(Button.Pressed, "#fiscal-btn-3")
    def on_fiscal_3(self, event: Button.Pressed) -> None:
        async def on_year(year):
            if year:
                await self._show_fiscal_impuestos(year)
        self.push_screen(YearInputScreen("ISR/IVA Estimados - Año"), on_year)

    @on(Button.Pressed, "#fiscal-btn-4")
    def on_fiscal_4(self, event: Button.Pressed) -> None:
        async def on_year(year):
            if year:
                await self._show_fiscal_sugerencias(year)
        self.push_screen(YearInputScreen("Sugerencias - Año"), on_year)

    @on(Button.Pressed, "#fiscal-btn-5")
    def on_fiscal_5(self, event: Button.Pressed) -> None:
        def on_uuid(uuid):
            if uuid:
                self._resolve_fiscal_uuid(uuid)
        self.push_screen(UuidInputScreen(), on_uuid)

    def _resolve_fiscal_uuid(self, prefix: str) -> None:
        prefix = prefix.upper().strip()
        rows = self.db.conn.execute(
            "SELECT uuid FROM comprobantes WHERE uuid LIKE ? LIMIT 5",
            (f"{prefix}%",),
        ).fetchall()
        if not rows:
            self.notify(f"No se encontró CFDI '{prefix}...'", severity="warning")
            return
        if len(rows) > 1:
            self.notify(f"Múltiples coincidencias ({len(rows)}). Usa más caracteres.", severity="warning")
            return
        self.push_screen(FiscalCfdiScreen(self.db, self.config, rows[0]["uuid"]))

    # ── Acciones de navegación ──

    def action_dashboard(self) -> None:
        async def on_year(year: int | None) -> None:
            if year:
                await self._show_dashboard(year)
        self.push_screen(YearInputScreen("Dashboard - Año"), on_year)

    def action_month(self) -> None:
        async def on_period(result: tuple | None) -> None:
            if result:
                year, month = result
                m = month if month else CURRENT_MONTH
                await self._show_month(year, m)
        self.push_screen(
            YearMonthInputScreen("Detalle Mensual", ask_month=True), on_period
        )

    async def action_search(self) -> None:
        await self._show_search()

    def action_top(self) -> None:
        async def on_year(year: int | None) -> None:
            if year:
                await self._show_top(year)
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
        import subprocess

        output_dir = Path("~/reportes_sat").expanduser()
        if self.config:
            output_dir = self.config.export.output_dir

        try:
            if month:
                path = self.exporter.monthly_report(year, month, output_dir)
            else:
                path = self.exporter.annual_report(year, output_dir)
            self.notify(f"Reporte guardado: {path}", title="Excel", timeout=8)
            try:
                subprocess.Popen(
                    ["xdg-open", str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass
        except Exception as e:
            self.notify(f"Error: {e}", title="Error", severity="error")

    async def action_fiscal(self) -> None:
        await self._show_fiscal_menu()

    def action_config(self) -> None:
        def on_config_close() -> None:
            self._refresh_info_bar()
        self.push_screen(ConfigScreen(self.config), on_config_close)

    def _set_status(self, text: str) -> None:
        """Actualiza la barra de estado desde cualquier hilo."""
        try:
            bar = self.query_one("#status-bar", Static)
            bar.update(text)
        except Exception:
            pass

    def action_do_download(self) -> None:
        if not self.config:
            self.notify(
                "Se requiere config.toml con FIEL para descargar",
                title="Error",
                severity="error",
            )
            return
        # Validar que exista configuración de FIEL
        if not getattr(self.config, "fiel", None):
            self.notify(
                "Falta sección [fiel] en config.toml",
                title="Error",
                severity="error",
            )
            return
        if not self.config.fiel.password:
            self.notify(
                "Falta password de FIEL en config.toml (requerido en TUI)",
                title="Error",
                severity="error",
            )
            return

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

            periodo = f"{year}/{month:02d}" if month else f"{year} completo"
            self.call_from_thread(self._set_status, f"Descargando CFDIs {periodo}...")
            self.notify(f"Iniciando descarga {periodo}...", title="SAT")

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
                self.call_from_thread(
                    self._set_status, f"Descargando {tipo}s {periodo}..."
                )
                zips = downloader.download_range(start, end, tipo, db=self.db)
                for zip_path in zips:
                    n = extract_and_process(zip_path, self.db, tipo)
                    total_new += n

            self.call_from_thread(self._set_status, "")
            self.notify(
                f"{total_new} CFDIs importados", title="Descarga SAT",
                timeout=8,
            )
            self.call_from_thread(self._refresh_info_bar)
        except Exception as e:
            self.call_from_thread(self._set_status, "")
            self.notify(
                f"Error: {e}", title="Error descarga", severity="error",
                timeout=10,
            )

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
            self.call_from_thread(self._refresh_info_bar)
        except Exception as e:
            self.notify(f"Error: {e}", title="Error", severity="error")




def run_tui(db_path: Path, config=None):
    """Punto de entrada para la TUI."""
    app = SATExtractorApp(db_path=db_path, config=config)
    app.run()
