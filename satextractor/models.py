"""Modelos de datos para CFDIs."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class Concepto:
    clave_prod_serv: str
    cantidad: Decimal
    clave_unidad: str
    descripcion: str
    valor_unitario: Decimal
    importe: Decimal
    descuento: Decimal | None = None


@dataclass
class Comprobante:
    uuid: str
    fecha: datetime
    rfc_emisor: str
    nombre_emisor: str
    regimen_emisor: str
    rfc_receptor: str
    nombre_receptor: str
    uso_cfdi: str
    subtotal: Decimal
    total: Decimal
    tipo_comprobante: str  # I=Ingreso, E=Egreso, T=Traslado, P=Pago, N=Nómina
    tipo: str  # "emitida" o "recibida"
    moneda: str = "MXN"
    descuento: Decimal | None = None
    tipo_cambio: Decimal | None = None
    metodo_pago: str | None = None
    forma_pago: str | None = None
    lugar_expedicion: str | None = None
    iva_trasladado: Decimal | None = None
    isr_retenido: Decimal | None = None
    iva_retenido: Decimal | None = None
    fecha_timbrado: datetime | None = None
    estado: str = "Vigente"
    conceptos: list[Concepto] = field(default_factory=list)
    xml_raw: bytes | None = None


TIPO_COMPROBANTE = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "P": "Pago",
    "N": "Nómina",
}


@dataclass
class ResultadoClasificacion:
    """Resultado de clasificar un concepto como deducible o no."""

    concepto_descripcion: str
    clave_prod_serv: str
    categoria: str  # "alimentos_restaurante", "combustible", etc.
    es_deducible: bool
    porcentaje_deducible: float  # 0-100
    monto_original: Decimal
    monto_deducible: Decimal
    fundamento_legal: str  # "Art. 103 Fracc. I LISR"
    requisitos: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    fuente: str = "regla_local"  # "regla_local" | "ia" | "cache"
    confianza: float = 1.0  # 0-1
    tipo_deduccion: str = "empresarial"  # "empresarial" | "personal" | "no_deducible"


@dataclass
class Sugerencia:
    """Sugerencia de optimización fiscal."""

    titulo: str
    descripcion: str
    ahorro_estimado: Decimal | None = None
    categoria: str = "general"  # "general", "deducciones", "forma_pago", "personal"
    prioridad: int = 1  # 1=alta, 2=media, 3=baja
