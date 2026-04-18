"""Cálculo de impuestos provisionales multi-régimen."""

from datetime import date
from decimal import Decimal

from ..db.repository import Repository

# ── Tabla mensual Art. 96 LISR (PF, vigente 2024-2025) ───────────────────
# (límite_inferior, límite_superior, cuota_fija, porcentaje_excedente)
_ISR_TABLA_MENSUAL = [
    (0.01,       746.04,       0.00,   1.92),
    (746.05,     6_332.05,     14.32,  6.40),
    (6_332.06,   11_128.01,    371.83, 10.88),
    (11_128.02,  12_935.82,    893.63, 16.00),
    (12_935.83,  15_487.71,    1_182.88, 17.92),
    (15_487.72,  31_236.49,    1_640.18, 21.36),
    (31_236.50,  49_233.00,    5_004.12, 23.52),
    (49_233.01,  93_993.90,    8_231.27, 30.00),
    (93_993.91,  125_325.20,   21_659.54, 32.00),
    (125_325.21, 375_975.61,   31_665.96, 34.00),
    (375_975.62, float("inf"), 116_886.90, 35.00),
]

# ── Tabla mensual RESICO Art. 113-E LISR ──────────────────────────────────
# (límite_inferior, límite_superior, tasa %)
_RESICO_TABLA_MENSUAL = [
    (0.01,       25_000.00,    1.00),
    (25_000.01,  50_000.00,    1.10),
    (50_000.01,  83_333.33,    1.50),
    (83_333.34,  208_333.33,   2.00),
    (208_333.34, 3_500_000.00, 2.50),
]

# ── Tasas retención plataformas (Art. 113-A LISR) ─────────────────────────
_PLATAFORMAS_TASAS = {
    "transporte": 2.1,
    "alimentos": 2.1,
    "hospedaje": 4.0,
    "venta_bienes": 1.0,
    "otros": 2.1,
}
_PLATAFORMAS_IVA_RETENCION = 8.0  # % retención IVA servicios digitales

# ── Mapa de régimen a tipo de cálculo ─────────────────────────────────────
_TIPO_REGIMEN = {
    "601": "pm_flat",
    "603": "exenta",
    "612": "pf_art96",
    "625": "plataformas",
    "626": "resico",
}

_PM_TASA_ISR = 30.0  # Art. 9 LISR Título II


def isr_label(regimen: str) -> str:
    """Retorna etiqueta descriptiva del método ISR para el régimen."""
    labels = {
        "601": "ISR 30% flat (Art. 9 LISR)",
        "603": "Exenta de ISR (Art. 79 LISR)",
        "612": "ISR s/tarifa Art. 96 LISR",
        "625": "ISR retención plataformas (Art. 113-A LISR)",
        "626": "ISR RESICO (Art. 113-E LISR)",
    }
    return labels.get(regimen, f"ISR régimen {regimen}")


def _calcular_isr_art96(base_gravable: float, num_meses: int) -> float:
    """Aplica la tarifa del Art. 96 LISR escalada al periodo acumulado."""
    if base_gravable <= 0:
        return 0.0

    for li, ls, cuota, pct in _ISR_TABLA_MENSUAL:
        li_p = li * num_meses
        ls_p = ls * num_meses
        cuota_p = cuota * num_meses

        if base_gravable <= ls_p or ls == float("inf"):
            excedente = base_gravable - li_p
            return cuota_p + excedente * (pct / 100.0)

    return 0.0


def _calcular_isr_resico(ingresos_mes: float) -> float:
    """Calcula ISR mensual RESICO (Art. 113-E). Tasa fija sobre ingreso bruto."""
    if ingresos_mes <= 0:
        return 0.0

    for li, ls, tasa in _RESICO_TABLA_MENSUAL:
        if ingresos_mes <= ls:
            return ingresos_mes * (tasa / 100.0)

    # Excede límite RESICO — usar tasa máxima
    return ingresos_mes * (2.5 / 100.0)


def _calcular_isr_pm(ingresos_acum: float, coeficiente: float) -> float:
    """ISR provisional PM (Art. 14 LISR). Ingreso × coeficiente × 30%."""
    if ingresos_acum <= 0 or coeficiente <= 0:
        return 0.0
    utilidad_estimada = ingresos_acum * coeficiente
    return utilidad_estimada * (_PM_TASA_ISR / 100.0)


def _calcular_isr_plataformas(ingresos_mes: float, actividad: str) -> float:
    """ISR retención por plataforma según actividad."""
    tasa = _PLATAFORMAS_TASAS.get(actividad, _PLATAFORMAS_TASAS["otros"])
    return ingresos_mes * (tasa / 100.0)


def _next_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


def calcular_impuestos_mensuales(
    db: Repository, year: int, regimen: str = "612", config=None
) -> list[dict]:
    """Calcula IVA a pagar e ISR provisional para cada mes del año.

    Adapta el cálculo según el régimen fiscal:
    - 612 (PFAE): Art. 96 progresiva sobre utilidad acumulada
    - 626 (RESICO): Art. 113-E tasa fija sobre ingreso bruto mensual
    - 601 (PM): 30% flat sobre ingreso × coeficiente de utilidad
    - 603 (PM no lucro): Exenta de ISR, solo IVA
    - 625 (Plataformas): Retención por actividad
    """
    from .clasificador import ClasificadorDeducciones

    tipo = _TIPO_REGIMEN.get(regimen, "pf_art96")
    permite_deducciones = tipo in ("pf_art96", "pm_flat")

    clasificador = ClasificadorDeducciones(regimen, db)

    # Parámetros específicos del régimen
    coeficiente = 0.0
    actividad_plat = "otros"
    if config and hasattr(config, "contribuyente") and config.contribuyente:
        coeficiente = config.contribuyente.coeficiente_utilidad
        actividad_plat = config.contribuyente.actividad_plataforma or "otros"

    resultados = []
    ingresos_acum = 0.0
    deducciones_acum = 0.0
    isr_retenido_acum = 0.0
    pagos_prov_anteriores = 0.0

    for month in range(1, 13):
        se = db.monthly_summary(year, month, "emitida")

        # ── IVA mensual ──
        iva_cobrado = se["iva_trasladado"]
        iva_retenido = se["iva_retenido"]

        # ── Obtener recibidas del mes (gastos) ──
        fecha_inicio = date(year, month, 1)
        fecha_fin = _next_month(year, month)

        gastos = []
        for tipo_comp in ("I", "E"):
            gastos.extend(db.search(
                tipo="recibida",
                tipo_comprobante=tipo_comp,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                estado="Vigente",
                limit=10000,
            ))

        # ── Clasificar deducciones y calcular IVA acreditable ──
        # IMPORTANTE: Solo deducciones empresariales (Art. 103 LISR) aplican
        # en pagos provisionales mensuales. Las deducciones personales
        # (Art. 151 LISR) solo aplican en la declaración anual (Art. 152).
        deducciones_mes = 0.0
        deducciones_brutas = 0.0
        deducciones_no_ded = 0.0
        deducciones_personales_mes = 0.0
        iva_acreditable = 0.0

        for comp in gastos:
            iva_comp = float(comp.iva_trasladado) if comp.iva_trasladado else 0.0
            subtotal_comp = float(comp.subtotal) if comp.subtotal else 0.0

            # Nota de crédito (E) recibida = te devuelven dinero → resta gastos
            signo = -1.0 if comp.tipo_comprobante == "E" else 1.0

            if comp.conceptos:
                total_deducible_empresarial = Decimal("0")
                total_deducible_personal = Decimal("0")
                total_original = Decimal("0")
                for concepto in comp.conceptos:
                    resultado = clasificador.clasificar_concepto(concepto, comp)
                    total_original += resultado.monto_original
                    if resultado.tipo_deduccion == "personal":
                        total_deducible_personal += resultado.monto_deducible
                    elif resultado.tipo_deduccion == "empresarial":
                        total_deducible_empresarial += resultado.monto_deducible

                total_ded_all = total_deducible_empresarial + total_deducible_personal
                pct_deducible = (
                    float(total_ded_all / total_original)
                    if total_original > 0 else 0.0
                )
                # Solo empresariales reducen base gravable mensual
                deducciones_mes += float(total_deducible_empresarial) * signo
                deducciones_personales_mes += float(total_deducible_personal) * signo
                deducciones_brutas += float(total_original) * signo
                no_ded = float(total_original - total_ded_all)
                deducciones_no_ded += no_ded * signo
                # IVA acreditable: solo de gastos con deducción empresarial
                pct_empresarial = (
                    float(total_deducible_empresarial / total_original)
                    if total_original > 0 else 0.0
                )
                iva_acreditable += iva_comp * pct_empresarial * signo
            else:
                deducciones_brutas += subtotal_comp * signo

        # ── IVA a pagar ──
        if tipo == "plataformas":
            # Plataformas: IVA retenido por la plataforma (8% del ingreso)
            iva_retenido_plat = se["ingresos"] * (_PLATAFORMAS_IVA_RETENCION / 100.0)
            iva_a_pagar = iva_cobrado - iva_acreditable - iva_retenido - iva_retenido_plat
        else:
            iva_a_pagar = iva_cobrado - iva_acreditable - iva_retenido

        # ── ISR provisional ──
        ingresos_mes = se["ingresos"]
        ingresos_acum += ingresos_mes
        isr_retenido_acum += se["isr_retenido"]

        if permite_deducciones:
            deducciones_acum += deducciones_mes
        # RESICO, Plataformas, Exenta: deducciones_acum queda en 0

        base_gravable = ingresos_acum - deducciones_acum

        if tipo == "pf_art96":
            isr_tarifa = _calcular_isr_art96(base_gravable, month)
            isr_provisional = isr_tarifa - isr_retenido_acum - pagos_prov_anteriores
        elif tipo == "resico":
            isr_tarifa = _calcular_isr_resico(ingresos_mes)
            isr_provisional = isr_tarifa  # RESICO es mensual, no acumulativo
        elif tipo == "pm_flat":
            isr_tarifa = _calcular_isr_pm(ingresos_acum, coeficiente)
            isr_provisional = isr_tarifa - pagos_prov_anteriores
        elif tipo == "plataformas":
            isr_tarifa = _calcular_isr_plataformas(ingresos_mes, actividad_plat)
            isr_provisional = isr_tarifa  # Retención mensual directa
        elif tipo == "exenta":
            isr_tarifa = 0.0
            isr_provisional = 0.0
        else:
            isr_tarifa = _calcular_isr_art96(base_gravable, month)
            isr_provisional = isr_tarifa - isr_retenido_acum - pagos_prov_anteriores

        if isr_provisional < 0:
            isr_provisional = 0.0

        resultados.append({
            "mes": month,
            "iva_cobrado": iva_cobrado,
            "iva_acreditable": round(iva_acreditable, 2),
            "iva_retenido": iva_retenido,
            "iva_a_pagar": round(iva_a_pagar, 2),
            "ingresos_mes": ingresos_mes,
            "ingresos_acum": ingresos_acum,
            "deducciones_mes": round(deducciones_mes, 2),
            "deducciones_acum": round(deducciones_acum, 2),
            "deducciones_brutas": round(deducciones_brutas, 2),
            "deducciones_no_deducibles": round(deducciones_no_ded, 2),
            "deducciones_personales_mes": round(deducciones_personales_mes, 2),
            "base_gravable": round(base_gravable, 2),
            "isr_tarifa": round(isr_tarifa, 2),
            "isr_retenido_acum": isr_retenido_acum,
            "isr_provisional": round(isr_provisional, 2),
            "pagos_prov_anteriores": pagos_prov_anteriores,
        })

        # Acumular pagos provisionales (no aplica para RESICO/plataformas mensuales)
        if tipo not in ("resico", "plataformas"):
            pagos_prov_anteriores += isr_provisional

    return resultados
