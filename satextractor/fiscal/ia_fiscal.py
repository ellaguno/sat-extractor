"""Asistente fiscal con IA para clasificación de gastos y sugerencias.

Usa la API de Claude para clasificar conceptos ambiguos y generar
recomendaciones fiscales personalizadas.
"""

import json
import os
from decimal import Decimal

from ..models import Comprobante, Concepto, ResultadoClasificacion, Sugerencia

_SYSTEM_PROMPT_CLASIFICACION = """\
Eres un asistente fiscal experto en la Ley del Impuesto Sobre la Renta (LISR) \
de México, especializado en el régimen {regimen_nombre} ({regimen_clave}).

Tu tarea es clasificar conceptos de facturas (CFDIs) y determinar si son \
deducibles fiscalmente.

Reglas clave para este régimen:
- Fundamento: {fundamento}
- Las deducciones deben ser estrictamente indispensables para la actividad
- Los pagos > $2,000 MXN deben ser bancarizados (Art. 27 Fracc. III LISR)
- Consumo en restaurantes: deducible al 91.5% solo con pago con tarjeta
- Combustibles: solo deducibles con pago electrónico
- Inversiones: se deducen por depreciación (Art. 31-38 LISR)
- Deducciones personales: Art. 151 LISR (médicos, colegiaturas, etc.)

La actividad del contribuyente es: {actividad}

IMPORTANTE: Responde SIEMPRE en formato JSON válido con esta estructura exacta:
{{
    "categoria": "nombre_categoria",
    "es_deducible": true/false,
    "porcentaje_deducible": 0-100,
    "fundamento_legal": "Artículo de la LISR",
    "requisitos": ["requisito1", "requisito2"],
    "alertas": ["alerta1"],
    "confianza": 0.0-1.0,
    "explicacion": "Explicación breve"
}}
"""

_PROMPT_CONCEPTO = """\
Clasifica el siguiente concepto de CFDI:

- Descripción: {descripcion}
- Clave producto/servicio SAT: {clave_prod_serv}
- Importe: ${importe:,.2f} MXN
- Forma de pago: {forma_pago}
- Emisor: {emisor} (RFC: {rfc_emisor})
- Uso CFDI: {uso_cfdi}

¿Es deducible para el contribuyente en el régimen {regimen}? \
¿Qué porcentaje? ¿Qué requisitos debe cumplir?
"""

_SYSTEM_PROMPT_SUGERENCIAS = """\
Eres un asesor fiscal experto en México especializado en optimización \
tributaria para personas físicas con actividad empresarial.

Analiza el resumen fiscal del contribuyente y genera sugerencias prácticas \
y específicas para reducir su carga fiscal de manera legal.

Responde en formato JSON como una lista de sugerencias:
[
    {{
        "titulo": "Título corto",
        "descripcion": "Explicación detallada con montos y artículos de ley",
        "ahorro_estimado": 0.00,
        "categoria": "deducciones|forma_pago|personal|inversiones|general",
        "prioridad": 1-3
    }}
]
"""


class AsistenteFiscal:
    """Asistente de IA para clasificación fiscal y sugerencias."""

    def __init__(
        self,
        api_key: str = "",
        regimen: str = "612",
        actividad: str = "",
        model: str = "claude-sonnet-4-6",
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.regimen = regimen
        self.actividad = actividad
        self.model = model
        self._client = None

        # Cargar datos del régimen
        from .clasificador import _cargar_reglas
        reglas = _cargar_reglas()
        regimen_data = reglas.get("regimenes", {}).get(regimen, {})
        self.regimen_nombre = regimen_data.get("nombre", regimen)
        self.fundamento = regimen_data.get("fundamento", "LISR")

    @property
    def disponible(self) -> bool:
        """Indica si la IA está disponible (tiene API key)."""
        return bool(self.api_key)

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "Instala el SDK de Anthropic: pip install anthropic"
                )
        return self._client

    def clasificar_concepto(
        self, concepto: Concepto, comprobante: Comprobante
    ) -> ResultadoClasificacion:
        """Clasifica un concepto usando Claude."""
        if not self.disponible:
            raise RuntimeError("API key de Anthropic no configurada")

        system = _SYSTEM_PROMPT_CLASIFICACION.format(
            regimen_nombre=self.regimen_nombre,
            regimen_clave=self.regimen,
            fundamento=self.fundamento,
            actividad=self.actividad or "No especificada",
        )

        user_msg = _PROMPT_CONCEPTO.format(
            descripcion=concepto.descripcion,
            clave_prod_serv=concepto.clave_prod_serv,
            importe=float(concepto.importe),
            forma_pago=comprobante.forma_pago or "No especificada",
            emisor=comprobante.nombre_emisor,
            rfc_emisor=comprobante.rfc_emisor,
            uso_cfdi=comprobante.uso_cfdi,
            regimen=self.regimen_nombre,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )

        # Parsear respuesta JSON
        text = response.content[0].text
        # Extraer JSON si viene envuelto en markdown
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())

        monto = concepto.importe
        if concepto.descuento:
            monto = monto - concepto.descuento
        porcentaje = data.get("porcentaje_deducible", 0)

        return ResultadoClasificacion(
            concepto_descripcion=concepto.descripcion,
            clave_prod_serv=concepto.clave_prod_serv,
            categoria=data.get("categoria", "ia_clasificado"),
            es_deducible=data.get("es_deducible", False),
            porcentaje_deducible=porcentaje,
            monto_original=monto,
            monto_deducible=monto * Decimal(str(porcentaje / 100)),
            fundamento_legal=data.get("fundamento_legal", ""),
            requisitos=data.get("requisitos", []),
            alertas=data.get("alertas", []),
            fuente="ia",
            confianza=data.get("confianza", 0.7),
        )

    def generar_sugerencias(
        self, resumen: dict, ingresos_anuales: float
    ) -> list[Sugerencia]:
        """Genera sugerencias de optimización fiscal con IA."""
        if not self.disponible:
            return []

        # Preparar resumen para el prompt
        cats_resumen = {}
        for cat_id, cat_data in resumen.get("por_categoria", {}).items():
            cats_resumen[cat_id] = {
                "nombre": cat_data["nombre"],
                "monto_original": float(cat_data["monto_original"]),
                "monto_deducible": float(cat_data["monto_deducible"]),
                "porcentaje": cat_data["porcentaje"],
                "num_conceptos": cat_data["num_conceptos"],
            }

        user_msg = json.dumps({
            "regimen": self.regimen_nombre,
            "actividad": self.actividad,
            "ingresos_anuales": ingresos_anuales,
            "total_gastos": float(resumen.get("total_original", 0)),
            "total_deducible": float(resumen.get("total_deducible", 0)),
            "porcentaje_deduccion": resumen.get("porcentaje_global", 0),
            "gastos_por_categoria": cats_resumen,
            "alertas_existentes": resumen.get("alertas", []),
        }, ensure_ascii=False, indent=2)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT_SUGERENCIAS,
            messages=[{"role": "user", "content": user_msg}],
        )

        text = response.content[0].text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        items = json.loads(text.strip())
        sugerencias = []
        for item in items:
            sugerencias.append(Sugerencia(
                titulo=item.get("titulo", ""),
                descripcion=item.get("descripcion", ""),
                ahorro_estimado=(
                    Decimal(str(item["ahorro_estimado"]))
                    if item.get("ahorro_estimado")
                    else None
                ),
                categoria=item.get("categoria", "general"),
                prioridad=item.get("prioridad", 2),
            ))

        sugerencias.sort(key=lambda s: s.prioridad)
        return sugerencias

    def explicar_deduccion(self, resultado: ResultadoClasificacion) -> str:
        """Explica en lenguaje sencillo por qué algo es/no es deducible."""
        if not self.disponible:
            # Explicación básica sin IA
            if resultado.es_deducible:
                return (
                    f"Este gasto es deducible al {resultado.porcentaje_deducible}% "
                    f"según {resultado.fundamento_legal}."
                )
            else:
                return (
                    f"Este gasto NO es deducible. "
                    f"Alertas: {'; '.join(resultado.alertas)}"
                )

        prompt = (
            f"Explica en lenguaje sencillo (2-3 oraciones) por qué el gasto "
            f"'{resultado.concepto_descripcion}' "
            f"{'ES' if resultado.es_deducible else 'NO es'} deducible "
            f"al {resultado.porcentaje_deducible}% para una persona física "
            f"con actividad empresarial.\n"
            f"Fundamento: {resultado.fundamento_legal}\n"
            f"Alertas: {resultado.alertas}"
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
