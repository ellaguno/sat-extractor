"""Cálculo de impuestos provisionales para Persona Física con Actividad Empresarial."""

from datetime import date
from decimal import Decimal

from ..db.repository import Repository

# Tabla mensual Art. 96 LISR (vigente 2024-2025)
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


def _calcular_isr_tarifa(base_gravable: float, num_meses: int) -> float:
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


def _next_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


def calcular_impuestos_mensuales(
    db: Repository, year: int, regimen: str = "612"
) -> list[dict]:
    """Calcula IVA a pagar e ISR provisional para cada mes del año.

    Usa el clasificador de deducciones para determinar qué gastos son
    realmente deducibles y qué IVA es acreditable.

    Retorna lista de 12 dicts con:
        mes, iva_a_pagar, isr_provisional, ingresos_acum, deducciones_acum,
        base_gravable, iva_cobrado, iva_acreditable, iva_retenido,
        isr_retenido_acum, pagos_provisionales_anteriores,
        deducciones_brutas, deducciones_no_deducibles
    """
    from .clasificador import ClasificadorDeducciones

    clasificador = ClasificadorDeducciones(regimen, db)

    resultados = []
    ingresos_acum = 0.0
    deducciones_acum = 0.0
    isr_retenido_acum = 0.0
    pagos_prov_anteriores = 0.0

    for month in range(1, 13):
        se = db.monthly_summary(year, month, "emitida")

        # ── IVA mensual ──
        # IVA cobrado = IVA trasladado en emitidas
        iva_cobrado = se["iva_trasladado"]
        # IVA retenido = lo que mis clientes me retuvieron
        iva_retenido = se["iva_retenido"]

        # ── Obtener recibidas tipo I/E del mes (gastos) ──
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

        # ── Clasificar deducciones y calcular IVA acreditable real ──
        deducciones_mes = 0.0
        deducciones_brutas = 0.0
        deducciones_no_ded = 0.0
        iva_acreditable = 0.0

        for comp in gastos:
            iva_comp = float(comp.iva_trasladado) if comp.iva_trasladado else 0.0
            subtotal_comp = float(comp.subtotal) if comp.subtotal else 0.0

            # Clasificar conceptos del comprobante
            if comp.conceptos:
                total_deducible = Decimal("0")
                total_original = Decimal("0")
                for concepto in comp.conceptos:
                    resultado = clasificador.clasificar_concepto(concepto, comp)
                    total_deducible += resultado.monto_deducible
                    total_original += resultado.monto_original

                pct_deducible = (
                    float(total_deducible / total_original)
                    if total_original > 0 else 0.0
                )
                deducciones_mes += float(total_deducible)
                deducciones_brutas += float(total_original)
                deducciones_no_ded += float(total_original - total_deducible)
                # IVA acreditable en proporción a lo deducible
                iva_acreditable += iva_comp * pct_deducible
            else:
                # Sin conceptos, usar subtotal bruto (fallback conservador)
                deducciones_brutas += subtotal_comp

        # ── IVA a pagar ──
        iva_a_pagar = iva_cobrado - iva_acreditable - iva_retenido

        # ── ISR provisional (acumulativo) ──
        ingresos_mes = se["ingresos"]
        ingresos_acum += ingresos_mes
        deducciones_acum += deducciones_mes
        isr_retenido_acum += se["isr_retenido"]

        base_gravable = ingresos_acum - deducciones_acum
        isr_tarifa = _calcular_isr_tarifa(base_gravable, month)

        # ISR a pagar = tarifa - retenciones acumuladas - pagos anteriores
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
            "base_gravable": round(base_gravable, 2),
            "isr_tarifa": round(isr_tarifa, 2),
            "isr_retenido_acum": isr_retenido_acum,
            "isr_provisional": round(isr_provisional, 2),
            "pagos_prov_anteriores": pagos_prov_anteriores,
        })

        # El ISR provisional de este mes se vuelve pago anterior
        pagos_prov_anteriores += isr_provisional

    return resultados
