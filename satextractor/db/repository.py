"""Operaciones CRUD y consultas sobre la base de datos."""

import sqlite3
from datetime import date, datetime
from decimal import Decimal

from ..models import Comprobante, Concepto


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_comprobante(self, c: Comprobante) -> bool:
        cursor = self.conn.execute(
            """INSERT INTO comprobantes (
                uuid, fecha, rfc_emisor, nombre_emisor, regimen_emisor,
                rfc_receptor, nombre_receptor, uso_cfdi,
                subtotal, descuento, total, tipo_comprobante,
                metodo_pago, forma_pago, moneda, tipo_cambio,
                lugar_expedicion, iva_trasladado, isr_retenido, iva_retenido,
                fecha_timbrado, estado, tipo, xml_raw
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            ) ON CONFLICT(uuid) DO UPDATE SET
                fecha=COALESCE(excluded.fecha, fecha),
                rfc_emisor=COALESCE(excluded.rfc_emisor, rfc_emisor),
                nombre_emisor=COALESCE(excluded.nombre_emisor, nombre_emisor),
                regimen_emisor=COALESCE(excluded.regimen_emisor, regimen_emisor),
                rfc_receptor=COALESCE(excluded.rfc_receptor, rfc_receptor),
                nombre_receptor=COALESCE(excluded.nombre_receptor, nombre_receptor),
                uso_cfdi=COALESCE(excluded.uso_cfdi, uso_cfdi),
                subtotal=COALESCE(excluded.subtotal, subtotal),
                descuento=COALESCE(excluded.descuento, descuento),
                total=COALESCE(excluded.total, total),
                tipo_comprobante=COALESCE(excluded.tipo_comprobante, tipo_comprobante),
                metodo_pago=COALESCE(excluded.metodo_pago, metodo_pago),
                forma_pago=COALESCE(excluded.forma_pago, forma_pago),
                moneda=COALESCE(excluded.moneda, moneda),
                tipo_cambio=COALESCE(excluded.tipo_cambio, tipo_cambio),
                lugar_expedicion=COALESCE(excluded.lugar_expedicion, lugar_expedicion),
                iva_trasladado=COALESCE(excluded.iva_trasladado, iva_trasladado),
                isr_retenido=COALESCE(excluded.isr_retenido, isr_retenido),
                iva_retenido=COALESCE(excluded.iva_retenido, iva_retenido),
                fecha_timbrado=COALESCE(excluded.fecha_timbrado, fecha_timbrado),
                estado=COALESCE(excluded.estado, estado),
                xml_raw=COALESCE(excluded.xml_raw, xml_raw)
            """,
            (
                c.uuid, c.fecha.isoformat(), c.rfc_emisor, c.nombre_emisor,
                c.regimen_emisor, c.rfc_receptor, c.nombre_receptor, c.uso_cfdi,
                float(c.subtotal), _to_float(c.descuento), float(c.total),
                c.tipo_comprobante, c.metodo_pago, c.forma_pago,
                c.moneda, _to_float(c.tipo_cambio), c.lugar_expedicion,
                _to_float(c.iva_trasladado), _to_float(c.isr_retenido),
                _to_float(c.iva_retenido),
                c.fecha_timbrado.isoformat() if c.fecha_timbrado else None,
                c.estado, c.tipo, c.xml_raw,
            ),
        )
        inserted = cursor.rowcount > 0

        if c.conceptos:
            self.conn.execute("DELETE FROM conceptos WHERE uuid = ?", (c.uuid,))
            self.conn.executemany(
                """INSERT INTO conceptos
                   (uuid, clave_prod_serv, cantidad, clave_unidad,
                    descripcion, valor_unitario, importe, descuento)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (c.uuid, con.clave_prod_serv, float(con.cantidad),
                     con.clave_unidad, con.descripcion, float(con.valor_unitario),
                     float(con.importe), _to_float(con.descuento))
                    for con in c.conceptos
                ],
            )

        self.conn.commit()
        return inserted

    def get_by_uuid(self, uuid: str) -> Comprobante | None:
        row = self.conn.execute(
            "SELECT * FROM comprobantes WHERE uuid = ?", (uuid,)
        ).fetchone()
        if not row:
            return None
        conceptos = self.conn.execute(
            "SELECT * FROM conceptos WHERE uuid = ?", (uuid,)
        ).fetchall()
        return _row_to_comprobante(row, conceptos)

    def search(
        self,
        *,
        rfc: str | None = None,
        tipo: str | None = None,
        tipo_comprobante: str | None = None,
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
        estado: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Comprobante]:
        conditions = []
        params: list = []

        if rfc:
            conditions.append("(rfc_emisor = ? OR rfc_receptor = ?)")
            params.extend([rfc, rfc])
        if tipo:
            conditions.append("tipo = ?")
            params.append(tipo)
        if tipo_comprobante:
            conditions.append("tipo_comprobante = ?")
            params.append(tipo_comprobante)
        if fecha_inicio:
            conditions.append("fecha >= ?")
            params.append(fecha_inicio.isoformat())
        if fecha_fin:
            conditions.append("fecha < ?")
            params.append(fecha_fin.isoformat())
        if estado:
            conditions.append("estado = ?")
            params.append(estado)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM comprobantes WHERE {where} ORDER BY fecha DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            conceptos = self.conn.execute(
                "SELECT * FROM conceptos WHERE uuid = ?", (r["uuid"],)
            ).fetchall()
            results.append(_row_to_comprobante(r, conceptos if conceptos else None))
        return results

    def count(
        self,
        *,
        tipo: str | None = None,
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
    ) -> int:
        conditions = []
        params: list = []
        if tipo:
            conditions.append("tipo = ?")
            params.append(tipo)
        if fecha_inicio:
            conditions.append("fecha >= ?")
            params.append(fecha_inicio.isoformat())
        if fecha_fin:
            conditions.append("fecha < ?")
            params.append(fecha_fin.isoformat())
        where = " AND ".join(conditions) if conditions else "1=1"
        row = self.conn.execute(
            f"SELECT COUNT(*) FROM comprobantes WHERE {where}", params
        ).fetchone()
        return row[0]

    def monthly_summary(self, year: int, month: int, tipo: str | None = None) -> dict:
        fecha_inicio = f"{year:04d}-{month:02d}-01"
        if month == 12:
            fecha_fin = f"{year + 1:04d}-01-01"
        else:
            fecha_fin = f"{year:04d}-{month + 1:02d}-01"

        conditions = ["fecha >= ? AND fecha < ?"]
        params: list = [fecha_inicio, fecha_fin]
        if tipo:
            conditions.append("tipo = ?")
            params.append(tipo)

        where = " AND ".join(conditions)

        row = self.conn.execute(
            f"""SELECT
                COUNT(*) as num_cfdis,
                COALESCE(SUM(CASE WHEN tipo_comprobante='I' THEN total ELSE 0 END), 0) as ingresos,
                COALESCE(SUM(CASE WHEN tipo_comprobante='E' THEN total ELSE 0 END), 0) as egresos,
                COALESCE(SUM(CASE WHEN tipo_comprobante='P' THEN total ELSE 0 END), 0) as pagos,
                COALESCE(SUM(CASE WHEN tipo_comprobante='N' THEN total ELSE 0 END), 0) as nomina,
                COALESCE(SUM(iva_trasladado), 0) as iva_trasladado,
                COALESCE(SUM(isr_retenido), 0) as isr_retenido,
                COALESCE(SUM(iva_retenido), 0) as iva_retenido,
                COALESCE(SUM(subtotal), 0) as subtotal_total,
                COALESCE(SUM(total), 0) as total_total
            FROM comprobantes WHERE {where}""",
            params,
        ).fetchone()

        return {
            "año": year,
            "mes": month,
            "num_cfdis": row[0],
            "ingresos": row[1],
            "egresos": row[2],
            "pagos": row[3],
            "nomina": row[4],
            "iva_trasladado": row[5],
            "isr_retenido": row[6],
            "iva_retenido": row[7],
            "subtotal": row[8],
            "total": row[9],
        }

    def annual_summary(self, year: int, tipo: str | None = None) -> list[dict]:
        return [self.monthly_summary(year, m, tipo) for m in range(1, 13)]

    def update_estado(self, uuid: str, estado: str) -> bool:
        """Actualiza el estado de un CFDI (Vigente/Cancelado)."""
        cursor = self.conn.execute(
            "UPDATE comprobantes SET estado = ? WHERE uuid = ?",
            (estado, uuid),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_comprobante(self, uuid: str) -> bool:
        """Elimina un CFDI y sus conceptos de la base de datos."""
        self.conn.execute("DELETE FROM conceptos WHERE uuid = ?", (uuid,))
        cursor = self.conn.execute(
            "DELETE FROM comprobantes WHERE uuid = ?", (uuid,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_downloaded(
        self, start: date, end: date, tipo: str,
        id_solicitud: str, num_cfdis: int, status: str = "ok",
    ):
        self.conn.execute(
            """INSERT INTO descargas (fecha_inicio, fecha_fin, tipo, id_solicitud, num_cfdis, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (start.isoformat(), end.isoformat(), tipo, id_solicitud, num_cfdis, status),
        )
        self.conn.commit()


def _to_float(val: Decimal | None) -> float | None:
    return float(val) if val is not None else None


def _row_to_comprobante(
    row: sqlite3.Row, conceptos_rows: list | None = None
) -> Comprobante:
    conceptos = []
    if conceptos_rows:
        conceptos = [
            Concepto(
                clave_prod_serv=cr["clave_prod_serv"] or "",
                cantidad=Decimal(str(cr["cantidad"])) if cr["cantidad"] else Decimal("0"),
                clave_unidad=cr["clave_unidad"] or "",
                descripcion=cr["descripcion"] or "",
                valor_unitario=Decimal(str(cr["valor_unitario"])) if cr["valor_unitario"] else Decimal("0"),
                importe=Decimal(str(cr["importe"])) if cr["importe"] else Decimal("0"),
                descuento=Decimal(str(cr["descuento"])) if cr["descuento"] else None,
            )
            for cr in conceptos_rows
        ]

    def _dec(val) -> Decimal | None:
        return Decimal(str(val)) if val is not None else None

    return Comprobante(
        uuid=row["uuid"],
        fecha=datetime.fromisoformat(row["fecha"]),
        rfc_emisor=row["rfc_emisor"],
        nombre_emisor=row["nombre_emisor"] or "",
        regimen_emisor=row["regimen_emisor"] or "",
        rfc_receptor=row["rfc_receptor"],
        nombre_receptor=row["nombre_receptor"] or "",
        uso_cfdi=row["uso_cfdi"] or "",
        subtotal=Decimal(str(row["subtotal"])),
        descuento=_dec(row["descuento"]),
        total=Decimal(str(row["total"])),
        tipo_comprobante=row["tipo_comprobante"],
        metodo_pago=row["metodo_pago"],
        forma_pago=row["forma_pago"],
        moneda=row["moneda"] or "MXN",
        tipo_cambio=_dec(row["tipo_cambio"]),
        lugar_expedicion=row["lugar_expedicion"],
        iva_trasladado=_dec(row["iva_trasladado"]),
        isr_retenido=_dec(row["isr_retenido"]),
        iva_retenido=_dec(row["iva_retenido"]),
        fecha_timbrado=datetime.fromisoformat(row["fecha_timbrado"]) if row["fecha_timbrado"] else None,
        estado=row["estado"] or "Vigente",
        tipo=row["tipo"],
        conceptos=conceptos,
        xml_raw=row["xml_raw"],
    )
