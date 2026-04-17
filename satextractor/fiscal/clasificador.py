"""Motor de clasificación de deducciones fiscales.

Clasifica conceptos de CFDIs como deducibles/no deducibles según el régimen
fiscal del contribuyente, usando reglas locales y opcionalmente IA.
"""

import tomllib
from decimal import Decimal
from pathlib import Path

from ..db.repository import Repository
from ..models import Comprobante, Concepto, ResultadoClasificacion

_FISCAL_DIR = Path(__file__).parent

# ── Carga de reglas ──────────────────────────────────────────────────────────


def _cargar_toml(nombre: str) -> dict:
    path = _FISCAL_DIR / nombre
    with open(path, "rb") as f:
        return tomllib.load(f)


def _cargar_reglas():
    return _cargar_toml("reglas_deducciones.toml")


def _cargar_catalogo():
    return _cargar_toml("catalogo_sat.toml")


# ── Utilidades ───────────────────────────────────────────────────────────────


def _coincide_clave(clave: str, catalogo_cat: dict) -> bool:
    """Verifica si una clave_prod_serv coincide con una categoría del catálogo."""
    if not clave:
        return False
    # Coincidencia exacta
    if clave in catalogo_cat.get("claves", []):
        return True
    # Coincidencia por prefijo
    for prefijo in catalogo_cat.get("prefijos", []):
        if clave.startswith(prefijo):
            return True
    return False


# ── Clasificador principal ───────────────────────────────────────────────────


class ClasificadorDeducciones:
    """Clasifica gastos según deducibilidad fiscal por régimen."""

    def __init__(self, regimen: str, db: Repository | None = None):
        self.regimen = regimen
        self.db = db
        self.reglas = _cargar_reglas()
        self.catalogo = _cargar_catalogo()

        regimen_data = self.reglas.get("regimenes", {}).get(regimen)
        if not regimen_data:
            raise ValueError(
                f"Régimen fiscal '{regimen}' no soportado. "
                f"Disponibles: {list(self.reglas.get('regimenes', {}).keys())}"
            )
        self.regimen_data = regimen_data
        self.deducciones = regimen_data.get("deducciones", {})
        self.deducciones_personales = regimen_data.get("deducciones_personales", {})
        self.requisitos_generales = self.reglas.get("requisitos_generales", {})

    def clasificar_concepto(
        self, concepto: Concepto, comprobante: Comprobante
    ) -> ResultadoClasificacion:
        """Clasifica un concepto individual.

        Orden de evaluación:
        0. Verificar tipo_comprobante (solo I y E son gastos deducibles)
        1. Cache en BD (si disponible)
        2. Catálogo SAT → categoría → reglas de deducción
        3. Categoría por defecto con alerta
        """
        clave = concepto.clave_prod_serv
        desc = concepto.descripcion
        monto = concepto.importe
        if concepto.descuento:
            monto = monto - concepto.descuento

        # 0. Verificar que el tipo de comprobante sea gasto deducible
        tipo = comprobante.tipo_comprobante
        if tipo not in ("I", "E"):
            # N=Nómina (ingreso del receptor), P=Pago (complemento), T=Traslado
            tipo_desc = {"N": "Nómina (ingreso)", "P": "Complemento de pago",
                         "T": "Traslado de mercancías"}.get(tipo, tipo)
            return ResultadoClasificacion(
                concepto_descripcion=desc,
                clave_prod_serv=clave,
                categoria="no_deducible",
                es_deducible=False,
                porcentaje_deducible=0.0,
                monto_original=monto,
                monto_deducible=Decimal("0"),
                fundamento_legal=f"Tipo de comprobante: {tipo_desc} - no es gasto deducible",
                requisitos=[],
                alertas=[f"CFDI tipo '{tipo}' ({tipo_desc}) no aplica como deducción"],
                fuente="regla_local",
                confianza=1.0,
            )

        # 1. Buscar categoría por clave SAT
        categoria_id, categoria_data = self._buscar_categoria(clave)

        if categoria_data:
            resultado = self._aplicar_reglas(
                categoria_id, categoria_data, concepto, comprobante, monto
            )
        else:
            # 2. No clasificado - NO asumir deducible
            resultado = ResultadoClasificacion(
                concepto_descripcion=desc,
                clave_prod_serv=clave,
                categoria="no_clasificado",
                es_deducible=False,
                porcentaje_deducible=0.0,
                monto_original=monto,
                monto_deducible=Decimal("0"),
                fundamento_legal="Sin clasificar - verificar manualmente",
                requisitos=["Determinar si es gasto de negocio o consumo personal"],
                alertas=["Gasto no clasificado - no se asume deducible"],
                fuente="regla_local",
                confianza=0.3,
            )

        # Verificar requisitos generales (forma de pago, estado, etc.)
        self._verificar_requisitos_generales(resultado, comprobante)

        return resultado

    def clasificar_comprobante(
        self, comprobante: Comprobante
    ) -> list[ResultadoClasificacion]:
        """Clasifica todos los conceptos de un comprobante."""
        resultados = []
        for concepto in comprobante.conceptos:
            resultado = self.clasificar_concepto(concepto, comprobante)
            resultados.append(resultado)
        return resultados

    def resumen_deduccion(
        self, comprobante: Comprobante
    ) -> dict:
        """Calcula el resumen de deducción de un comprobante completo."""
        clasificaciones = self.clasificar_comprobante(comprobante)

        total_original = sum(c.monto_original for c in clasificaciones)
        total_deducible = sum(c.monto_deducible for c in clasificaciones)
        total_no_deducible = total_original - total_deducible
        todas_alertas = []
        for c in clasificaciones:
            todas_alertas.extend(c.alertas)

        return {
            "uuid": comprobante.uuid,
            "clasificaciones": clasificaciones,
            "total_original": total_original,
            "total_deducible": total_deducible,
            "total_no_deducible": total_no_deducible,
            "porcentaje_deducible": (
                float(total_deducible / total_original * 100)
                if total_original > 0
                else 0.0
            ),
            "alertas": list(set(todas_alertas)),
        }

    def resumen_periodo(
        self, comprobantes: list[Comprobante]
    ) -> dict:
        """Calcula el resumen de deducciones para un conjunto de comprobantes."""
        por_categoria: dict[str, dict] = {}
        total_original = Decimal("0")
        total_deducible = Decimal("0")
        todas_alertas: list[str] = []
        num_no_clasificados = 0

        for comp in comprobantes:
            for concepto in comp.conceptos:
                resultado = self.clasificar_concepto(concepto, comp)
                cat = resultado.categoria

                if cat not in por_categoria:
                    por_categoria[cat] = {
                        "nombre": self._nombre_categoria(cat),
                        "monto_original": Decimal("0"),
                        "monto_deducible": Decimal("0"),
                        "porcentaje": resultado.porcentaje_deducible,
                        "num_conceptos": 0,
                        "alertas": [],
                    }

                por_categoria[cat]["monto_original"] += resultado.monto_original
                por_categoria[cat]["monto_deducible"] += resultado.monto_deducible
                por_categoria[cat]["num_conceptos"] += 1
                por_categoria[cat]["alertas"].extend(resultado.alertas)

                total_original += resultado.monto_original
                total_deducible += resultado.monto_deducible
                todas_alertas.extend(resultado.alertas)

                if resultado.confianza < 0.5:
                    num_no_clasificados += 1

        # Deduplicar alertas por categoría
        for cat_data in por_categoria.values():
            cat_data["alertas"] = list(set(cat_data["alertas"]))

        return {
            "por_categoria": por_categoria,
            "total_original": total_original,
            "total_deducible": total_deducible,
            "total_no_deducible": total_original - total_deducible,
            "porcentaje_global": (
                float(total_deducible / total_original * 100)
                if total_original > 0
                else 0.0
            ),
            "num_comprobantes": len(comprobantes),
            "num_no_clasificados": num_no_clasificados,
            "alertas": list(set(todas_alertas)),
        }

    def generar_sugerencias(
        self, comprobantes: list[Comprobante], ingresos_anuales: float = 0
    ) -> list:
        """Genera sugerencias de optimización fiscal basadas en los gastos."""
        from ..models import Sugerencia

        sugerencias: list[Sugerencia] = []
        resumen = self.resumen_periodo(comprobantes)

        # 1. Gastos pagados en efectivo que podrían ser deducibles
        gastos_efectivo_no_ded = Decimal("0")
        for comp in comprobantes:
            if comp.forma_pago == "01":  # Efectivo
                for concepto in comp.conceptos:
                    if float(concepto.importe) > 2000:
                        gastos_efectivo_no_ded += concepto.importe

        if gastos_efectivo_no_ded > 0:
            sugerencias.append(Sugerencia(
                titulo="Pagos en efectivo mayores a $2,000",
                descripcion=(
                    f"Tienes ${float(gastos_efectivo_no_ded):,.2f} en gastos pagados en "
                    f"efectivo que superan $2,000. Estos NO son deducibles. "
                    f"Usa transferencia o tarjeta para hacerlos deducibles."
                ),
                ahorro_estimado=gastos_efectivo_no_ded * Decimal("0.30"),
                categoria="forma_pago",
                prioridad=1,
            ))

        # 2. Restaurantes sin pago bancarizado
        restaurantes_efectivo = Decimal("0")
        for comp in comprobantes:
            if comp.forma_pago in ("01", None):
                for concepto in comp.conceptos:
                    cat_id, _ = self._buscar_categoria(concepto.clave_prod_serv)
                    if cat_id == "alimentos_restaurante":
                        restaurantes_efectivo += concepto.importe

        if restaurantes_efectivo > 0:
            ahorro = restaurantes_efectivo * Decimal("0.915") * Decimal("0.30")
            sugerencias.append(Sugerencia(
                titulo="Restaurantes pagados en efectivo",
                descripcion=(
                    f"Tienes ${float(restaurantes_efectivo):,.2f} en restaurantes pagados "
                    f"en efectivo. Si pagas con tarjeta, el 91.5% sería deducible. "
                    f"Ahorro potencial en ISR: ~${float(ahorro):,.2f}"
                ),
                ahorro_estimado=ahorro,
                categoria="deducciones",
                prioridad=1,
            ))

        # 3. Verificar si hay deducciones personales
        cats_personales = {"servicios_medicos", "educacion", "gastos_funerarios"}
        tiene_personales = any(
            cat in resumen["por_categoria"] for cat in cats_personales
        )

        if not tiene_personales:
            sugerencias.append(Sugerencia(
                titulo="Sin deducciones personales registradas",
                descripcion=(
                    "No se encontraron gastos médicos, colegiaturas ni otras "
                    "deducciones personales (Art. 151 LISR). Recuerda que puedes "
                    "deducir: honorarios médicos/dentales, colegiaturas, primas de "
                    "seguros médicos, gastos funerarios, intereses hipotecarios y "
                    "aportaciones a retiro."
                ),
                categoria="personal",
                prioridad=2,
            ))

        # 4. Proporción gastos/ingresos
        if ingresos_anuales > 0:
            ratio = float(resumen["total_deducible"]) / ingresos_anuales
            if ratio < 0.20:
                sugerencias.append(Sugerencia(
                    titulo="Bajo nivel de deducciones",
                    descripcion=(
                        f"Tus deducciones representan solo {ratio*100:.1f}% de tus "
                        f"ingresos. Revisa si hay gastos de operación que no estás "
                        f"facturando: renta, servicios, software, equipo, etc."
                    ),
                    categoria="general",
                    prioridad=2,
                ))

        # 5. Gastos no clasificados
        if resumen["num_no_clasificados"] > 0:
            sugerencias.append(Sugerencia(
                titulo=f"{resumen['num_no_clasificados']} gastos sin clasificar",
                descripcion=(
                    f"Hay {resumen['num_no_clasificados']} conceptos que no se "
                    f"pudieron clasificar automáticamente. Configura la IA en "
                    f"config.toml para mejorar la clasificación, o revísalos "
                    f"manualmente."
                ),
                categoria="general",
                prioridad=3,
            ))

        # Ordenar por prioridad
        sugerencias.sort(key=lambda s: s.prioridad)
        return sugerencias

    # ── Métodos internos ─────────────────────────────────────────────────────

    def _buscar_categoria(self, clave: str) -> tuple[str, dict | None]:
        """Busca la categoría fiscal de una clave_prod_serv en el catálogo.

        Orden de prioridad (más específico gana):
        1. Coincidencia exacta de código completo
        2. Prefijo más largo que coincida
        """
        if not clave:
            return "", None

        categorias = self.catalogo.get("categorias", {})

        # 1. Coincidencia exacta (máxima prioridad)
        for cat_id, cat_data in categorias.items():
            if cat_id.startswith("_"):
                continue
            if clave in cat_data.get("claves", []):
                return cat_id, cat_data

        # 2. Prefijo más largo que coincida
        best_match: tuple[str, dict] | None = None
        best_prefix_len = 0
        for cat_id, cat_data in categorias.items():
            if cat_id.startswith("_"):
                continue
            for prefijo in cat_data.get("prefijos", []):
                if clave.startswith(prefijo) and len(prefijo) > best_prefix_len:
                    best_match = (cat_id, cat_data)
                    best_prefix_len = len(prefijo)

        if best_match:
            return best_match

        return "", None

    def _nombre_categoria(self, categoria_id: str) -> str:
        """Obtiene el nombre legible de una categoría."""
        cat = self.catalogo.get("categorias", {}).get(categoria_id, {})
        if cat:
            return cat.get("descripcion", categoria_id)
        # Buscar en deducciones del régimen
        ded = self.deducciones.get(categoria_id, {})
        if ded:
            return ded.get("nombre", categoria_id)
        return categoria_id

    def _aplicar_reglas(
        self,
        categoria_id: str,
        categoria_data: dict,
        concepto: Concepto,
        comprobante: Comprobante,
        monto: Decimal,
    ) -> ResultadoClasificacion:
        """Aplica las reglas de deducción para una categoría identificada."""
        # Determinar si es deducción empresarial o personal
        deduccion_id = categoria_data.get("deduccion", "")
        deduccion_personal_id = categoria_data.get("deduccion_personal", "")

        alertas: list[str] = []
        requisitos: list[str] = []

        if deduccion_id:
            # Buscar regla de deducción empresarial
            regla = self.deducciones.get(deduccion_id, {})
            porcentaje = regla.get("porcentaje", 100)
            fundamento = regla.get("fundamento", "Art. 103 LISR")
            requisitos = list(regla.get("requisitos", []))

            # Verificar forma de pago requerida
            formas_req = regla.get("forma_pago_requerida", [])
            if formas_req and comprobante.forma_pago:
                if comprobante.forma_pago not in formas_req:
                    alertas.append(
                        f"Forma de pago '{comprobante.forma_pago}' no válida para "
                        f"esta deducción. Requiere: {', '.join(formas_req)}"
                    )
                    porcentaje = 0  # No deducible sin forma de pago correcta

            # Verificar límite de monto
            limite = regla.get("limite_monto")
            if limite and float(monto) > limite:
                alertas.append(
                    f"Monto ${float(monto):,.2f} excede el límite deducible "
                    f"de ${limite:,.2f}"
                )
                monto_deducible = Decimal(str(limite)) * Decimal(str(porcentaje / 100))
            else:
                monto_deducible = monto * Decimal(str(porcentaje / 100))

            # Si es inversión, marcar para depreciación
            tipo_inv = categoria_data.get("tipo_inversion", "")
            if tipo_inv:
                dep = self.reglas.get("depreciacion", {}).get(tipo_inv, {})
                tasa = dep.get("tasa_anual", 10)
                alertas.append(
                    f"Inversión: deducible por depreciación al {tasa}% anual "
                    f"({dep.get('fundamento', 'Art. 34 LISR')})"
                )
                # Para inversiones, el monto deducible es la depreciación anual
                monto_deducible = monto * Decimal(str(tasa / 100))

        elif deduccion_personal_id:
            # Deducción personal
            regla_personal = self.deducciones_personales.get(deduccion_personal_id, {})
            if isinstance(regla_personal, dict):
                porcentaje = regla_personal.get("porcentaje", 100)
                fundamento = regla_personal.get("fundamento", "Art. 151 LISR")
                requisitos = list(regla_personal.get("requisitos", []))

                # Verificar forma de pago requerida
                formas_req = regla_personal.get("forma_pago_requerida", [])
                if formas_req and comprobante.forma_pago:
                    if comprobante.forma_pago not in formas_req:
                        alertas.append(
                            f"Deducción personal requiere pago electrónico. "
                            f"Forma de pago actual: '{comprobante.forma_pago}'"
                        )
                        porcentaje = 0
            else:
                porcentaje = 100
                fundamento = "Art. 151 LISR"

            monto_deducible = monto * Decimal(str(porcentaje / 100))
            alertas.append("Deducción personal - aplica en declaración anual")
        else:
            # Sin regla específica, asumir gasto de operación
            porcentaje = 100
            fundamento = "Art. 103 Fracc. III LISR"
            monto_deducible = monto

        es_deducible = porcentaje > 0

        return ResultadoClasificacion(
            concepto_descripcion=concepto.descripcion,
            clave_prod_serv=concepto.clave_prod_serv,
            categoria=categoria_id,
            es_deducible=es_deducible,
            porcentaje_deducible=float(porcentaje),
            monto_original=monto,
            monto_deducible=monto_deducible,
            fundamento_legal=fundamento,
            requisitos=requisitos,
            alertas=alertas,
            fuente="regla_local",
            confianza=0.8 if categoria_data else 0.3,
        )

    def _verificar_requisitos_generales(
        self, resultado: ResultadoClasificacion, comprobante: Comprobante
    ):
        """Verifica requisitos generales de deducción (Art. 27 LISR)."""
        # Verificar pago bancarizado para montos > $2,000
        pago_banc = self.requisitos_generales.get("pago_bancarizado", {})
        limite_efectivo = pago_banc.get("limite_efectivo", 2000)
        formas_validas = pago_banc.get("formas_pago_validas", [])

        if float(resultado.monto_original) > limite_efectivo:
            if comprobante.forma_pago == "01":  # Efectivo
                resultado.alertas.append(
                    f"Pago en efectivo de ${float(resultado.monto_original):,.2f} "
                    f"(> ${limite_efectivo:,.2f}). NO deducible por Art. 27 Fracc. III LISR"
                )
                resultado.es_deducible = False
                resultado.porcentaje_deducible = 0
                resultado.monto_deducible = Decimal("0")

        # Verificar CFDI vigente
        if comprobante.estado != "Vigente":
            resultado.alertas.append("CFDI cancelado - NO deducible")
            resultado.es_deducible = False
            resultado.porcentaje_deducible = 0
            resultado.monto_deducible = Decimal("0")

    # ── Cache en BD (reservado para clasificaciones de IA) ────────────────────
    # El cache de reglas locales fue eliminado porque la deducibilidad depende
    # del contexto del comprobante (forma_pago, estado, tipo_comprobante) y no
    # solo de la clave SAT. Las reglas locales son rápidas y no necesitan cache.
    # La tabla 'clasificaciones' se mantiene para futuro uso con IA.
