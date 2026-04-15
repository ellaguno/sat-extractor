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
