"""Parser de XMLs CFDI 4.0 y 3.3."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from ..models import Comprobante, Concepto

NS_V4 = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}

NS_V3 = {
    "cfdi": "http://www.sat.gob.mx/cfd/3",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
}


def parse_cfdi_file(path: Path, tipo: str = "recibida") -> Comprobante:
    xml_bytes = path.read_bytes()
    return parse_cfdi(xml_bytes, tipo)


def parse_cfdi(xml_bytes: bytes, tipo: str = "recibida") -> Comprobante:
    root = etree.fromstring(xml_bytes)
    version = root.get("Version") or root.get("version", "")
    ns = NS_V4 if version == "4.0" else NS_V3

    # Emisor
    emisor = root.find("cfdi:Emisor", ns)
    rfc_emisor = _attr(emisor, "Rfc")
    nombre_emisor = _attr(emisor, "Nombre")
    regimen_emisor = _attr(emisor, "RegimenFiscal")

    # Receptor
    receptor = root.find("cfdi:Receptor", ns)
    rfc_receptor = _attr(receptor, "Rfc")
    nombre_receptor = _attr(receptor, "Nombre")
    uso_cfdi = _attr(receptor, "UsoCFDI")

    # Impuestos globales
    impuestos_node = root.find("cfdi:Impuestos", ns)
    iva_trasladado = None
    isr_retenido = None
    iva_retenido = None

    if impuestos_node is not None:
        iva_trasladado = _dec(impuestos_node.get("TotalImpuestosTrasladados"))

        retenciones = impuestos_node.find("cfdi:Retenciones", ns)
        if retenciones is not None:
            for ret in retenciones.findall("cfdi:Retencion", ns):
                impuesto = ret.get("Impuesto", "")
                importe = _dec(ret.get("Importe"))
                if impuesto == "001":  # ISR
                    isr_retenido = (isr_retenido or Decimal("0")) + (importe or Decimal("0"))
                elif impuesto == "002":  # IVA
                    iva_retenido = (iva_retenido or Decimal("0")) + (importe or Decimal("0"))

    # TimbreFiscalDigital
    uuid = ""
    fecha_timbrado = None
    complemento = root.find("cfdi:Complemento", ns)
    if complemento is not None:
        tfd = complemento.find("tfd:TimbreFiscalDigital", ns)
        if tfd is not None:
            uuid = (tfd.get("UUID") or "").upper()
            ft = tfd.get("FechaTimbrado")
            if ft:
                fecha_timbrado = datetime.fromisoformat(ft)

    # Conceptos
    conceptos = []
    conceptos_node = root.find("cfdi:Conceptos", ns)
    if conceptos_node is not None:
        for concepto_el in conceptos_node.findall("cfdi:Concepto", ns):
            conceptos.append(Concepto(
                clave_prod_serv=concepto_el.get("ClaveProdServ", ""),
                cantidad=_dec(concepto_el.get("Cantidad")) or Decimal("1"),
                clave_unidad=concepto_el.get("ClaveUnidad", ""),
                descripcion=concepto_el.get("Descripcion", ""),
                valor_unitario=_dec(concepto_el.get("ValorUnitario")) or Decimal("0"),
                importe=_dec(concepto_el.get("Importe")) or Decimal("0"),
                descuento=_dec(concepto_el.get("Descuento")),
            ))

    fecha_str = root.get("Fecha", "")
    fecha = datetime.fromisoformat(fecha_str) if fecha_str else datetime.now()

    return Comprobante(
        uuid=uuid,
        fecha=fecha,
        rfc_emisor=rfc_emisor,
        nombre_emisor=nombre_emisor,
        regimen_emisor=regimen_emisor,
        rfc_receptor=rfc_receptor,
        nombre_receptor=nombre_receptor,
        uso_cfdi=uso_cfdi,
        subtotal=_dec(root.get("SubTotal")) or Decimal("0"),
        descuento=_dec(root.get("Descuento")),
        total=_dec(root.get("Total")) or Decimal("0"),
        tipo_comprobante=root.get("TipoDeComprobante", "I"),
        metodo_pago=root.get("MetodoPago"),
        forma_pago=root.get("FormaPago"),
        moneda=root.get("Moneda", "MXN"),
        tipo_cambio=_dec(root.get("TipoCambio")),
        lugar_expedicion=root.get("LugarExpedicion"),
        iva_trasladado=iva_trasladado,
        isr_retenido=isr_retenido,
        iva_retenido=iva_retenido,
        fecha_timbrado=fecha_timbrado,
        tipo=tipo,
        conceptos=conceptos,
        xml_raw=xml_bytes,
    )


def _attr(element, name: str, default: str = "") -> str:
    if element is None:
        return default
    return element.get(name, default) or default


def _dec(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None
