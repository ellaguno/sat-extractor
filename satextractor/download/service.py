"""Orquestador de descarga masiva de CFDIs del SAT."""

import base64
import calendar
import io
import time
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import mkdtemp

from rich.console import Console
from rich.progress import Progress

from ..auth.fiel import get_auth_token
from ..db.repository import Repository
from ..models import Comprobante

console = Console()

# Estados de solicitud del SAT
STATUS_TERMINADA = 3
STATUS_ERROR = 4
STATUS_RECHAZADA = 5
STATUS_VENCIDA = 6

MAX_POLL_ATTEMPTS = 30
INITIAL_POLL_DELAY = 10

# Mapeo de EfectoComprobante en Metadata a TipoDeComprobante
EFECTO_TO_TIPO = {
    "I": "I",  # Ingreso
    "E": "E",  # Egreso
    "T": "T",  # Traslado
    "P": "P",  # Pago
    "N": "N",  # Nómina
}


class SATDownloader:
    def __init__(self, fiel, rfc: str):
        self.fiel = fiel
        self.rfc = rfc

    def download_range(
        self,
        start: date,
        end: date,
        tipo: str = "recibida",
        output_dir: Path | None = None,
        db: Repository | None = None,
    ) -> list[Path]:
        from cfdiclient import (
            DescargaMasiva,
            SolicitaDescargaEmitidos,
            SolicitaDescargaRecibidos,
            VerificaSolicitudDescarga,
        )

        if output_dir is None:
            output_dir = Path(mkdtemp(prefix="sat_"))

        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded_zips = []

        chunks = _monthly_chunks(start, end)

        with Progress(console=console) as progress:
            task = progress.add_task(
                f"Descargando {tipo}s...", total=len(chunks)
            )

            for chunk_start, chunk_end in chunks:
                progress.update(
                    task,
                    description=f"[cyan]{tipo}s {chunk_start} → {chunk_end}",
                )

                try:
                    if tipo == "recibida":
                        solicita = SolicitaDescargaRecibidos(self.fiel)
                    else:
                        solicita = SolicitaDescargaEmitidos(self.fiel)

                    # Intentar primero con CFDI (XMLs completos)
                    # Si falla (común en recibidas para personas físicas),
                    # usar Metadata como fallback
                    zips = self._download_chunk(
                        chunk_start, chunk_end, tipo, output_dir,
                        solicita,
                        VerificaSolicitudDescarga(self.fiel),
                        DescargaMasiva(self.fiel),
                        tipo_solicitud="CFDI",
                    )
                    downloaded_zips.extend(zips)
                except RuntimeError as e:
                    if "cancelados" in str(e).lower() or "no es válida" in str(e).lower():
                        # Fallback a Metadata
                        console.print(
                            f"  [yellow]CFDI no disponible, usando Metadata...[/yellow]"
                        )
                        try:
                            if tipo == "recibida":
                                solicita = SolicitaDescargaRecibidos(self.fiel)
                            else:
                                solicita = SolicitaDescargaEmitidos(self.fiel)

                            n = self._download_metadata(
                                chunk_start, chunk_end, tipo, db,
                                solicita,
                                VerificaSolicitudDescarga(self.fiel),
                                DescargaMasiva(self.fiel),
                            )
                            console.print(f"  [green]{n} CFDI(s) desde Metadata[/green]")
                        except Exception as e2:
                            console.print(
                                f"[red]Error Metadata {chunk_start}-{chunk_end}: {e2}"
                            )
                    else:
                        console.print(
                            f"[red]Error descargando {chunk_start}-{chunk_end}: {e}"
                        )
                except Exception as e:
                    console.print(
                        f"[red]Error descargando {chunk_start}-{chunk_end}: {e}"
                    )

                progress.advance(task)

        return downloaded_zips

    def _download_chunk(
        self,
        start: date,
        end: date,
        tipo: str,
        output_dir: Path,
        solicita,
        verifica,
        descarga,
        tipo_solicitud: str = "CFDI",
    ) -> list[Path]:
        token = get_auth_token(self.fiel)

        dt_start = datetime(start.year, start.month, start.day, 0, 0, 0)
        dt_end = datetime(end.year, end.month, end.day, 23, 59, 59)

        if tipo == "recibida":
            result = solicita.solicitar_descarga(
                token, self.rfc, dt_start, dt_end,
                rfc_receptor=self.rfc, tipo_solicitud=tipo_solicitud,
            )
        else:
            result = solicita.solicitar_descarga(
                token, self.rfc, dt_start, dt_end,
                rfc_emisor=self.rfc, tipo_solicitud=tipo_solicitud,
            )

        id_solicitud = result.get("id_solicitud", "")

        if not id_solicitud:
            raise RuntimeError(
                f"SAT no aceptó la solicitud: {result.get('mensaje', result.get('cod_estatus'))}"
            )

        console.print(f"  Solicitud: {id_solicitud}")

        package_ids = self._poll_until_ready(verifica, id_solicitud)

        # Descargar paquetes
        zips = []
        for pkg_id in package_ids:
            token = get_auth_token(self.fiel)
            pkg_result = descarga.descargar_paquete(token, self.rfc, pkg_id)
            paquete_b64 = pkg_result.get("paquete_b64", "")

            if paquete_b64:
                zip_bytes = base64.b64decode(paquete_b64)
                zip_path = output_dir / f"{pkg_id}.zip"
                zip_path.write_bytes(zip_bytes)
                zips.append(zip_path)
                console.print(f"  Descargado: {zip_path.name}")

        return zips

    def _download_metadata(
        self,
        start: date,
        end: date,
        tipo: str,
        db: Repository | None,
        solicita,
        verifica,
        descarga,
    ) -> int:
        """Descarga Metadata (CSV) del SAT y lo inserta en la BD."""
        token = get_auth_token(self.fiel)

        dt_start = datetime(start.year, start.month, start.day, 0, 0, 0)
        dt_end = datetime(end.year, end.month, end.day, 23, 59, 59)

        if tipo == "recibida":
            result = solicita.solicitar_descarga(
                token, self.rfc, dt_start, dt_end,
                rfc_receptor=self.rfc, tipo_solicitud="Metadata",
            )
        else:
            result = solicita.solicitar_descarga(
                token, self.rfc, dt_start, dt_end,
                rfc_emisor=self.rfc, tipo_solicitud="Metadata",
            )

        id_solicitud = result.get("id_solicitud", "")
        if not id_solicitud:
            raise RuntimeError(
                f"SAT no aceptó la solicitud: {result.get('mensaje', '')}"
            )

        console.print(f"  Solicitud Metadata: {id_solicitud}")

        package_ids = self._poll_until_ready(verifica, id_solicitud)

        count = 0
        for pkg_id in package_ids:
            token = get_auth_token(self.fiel)
            pkg_result = descarga.descargar_paquete(token, self.rfc, pkg_id)
            paquete_b64 = pkg_result.get("paquete_b64", "")

            if paquete_b64 and db:
                zip_bytes = base64.b64decode(paquete_b64)
                count += _parse_metadata_zip(zip_bytes, tipo, db)

        return count

    def _poll_until_ready(self, verifica, id_solicitud: str) -> list[str]:
        delay = INITIAL_POLL_DELAY

        for attempt in range(MAX_POLL_ATTEMPTS):
            time.sleep(delay)
            token = get_auth_token(self.fiel)

            verify_result = verifica.verificar_descarga(
                token, self.rfc, id_solicitud
            )
            estado = int(verify_result.get("estado_solicitud", 0))

            if estado == STATUS_TERMINADA:
                package_ids = verify_result.get("paquetes", [])
                num_cfdis = verify_result.get("numero_cfdis", "?")
                console.print(
                    f"  Listos: {len(package_ids)} paquete(s), {num_cfdis} CFDI(s)"
                )
                return package_ids
            elif estado == STATUS_RECHAZADA:
                console.print(
                    f"  [yellow]Solicitud rechazada, reintentando en {delay}s...[/yellow]"
                )
            elif estado in (STATUS_ERROR, STATUS_VENCIDA):
                raise RuntimeError(
                    f"Solicitud fallida (estado={estado}): "
                    f"{verify_result.get('mensaje', '')}"
                )

            delay = min(int(delay * 1.5), 60)

        raise TimeoutError(
            f"La solicitud {id_solicitud} no terminó después de "
            f"{MAX_POLL_ATTEMPTS} intentos."
        )


def _parse_metadata_zip(zip_bytes: bytes, tipo: str, db: Repository) -> int:
    """Parsea un ZIP de Metadata del SAT (CSV con separador ~) e inserta en BD."""
    count = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            # Ignorar archivo de terceros
            if "tercero" in name.lower():
                continue
            if not name.endswith(".txt"):
                continue

            content = zf.read(name).decode("utf-8", errors="replace")
            lines = content.strip().split("\n")

            if len(lines) < 2:
                continue

            # Primera línea es el header
            # Uuid~RfcEmisor~NombreEmisor~RfcReceptor~NombreReceptor~PacCertifico~
            # FechaEmision~FechaCertificacionSat~Monto~EfectoComprobante~Estatus~FechaCancelacion
            for line in lines[1:]:
                fields = line.strip().split("~")
                if len(fields) < 11:
                    continue

                uuid = fields[0].upper()
                rfc_emisor = fields[1]
                nombre_emisor = fields[2]
                rfc_receptor = fields[3]
                nombre_receptor = fields[4]
                fecha_emision = fields[6]
                fecha_certificacion = fields[7]
                monto = fields[8]
                efecto = fields[9]
                estatus = fields[10]  # 1=Vigente, 0=Cancelado

                # Parsear fecha
                try:
                    fecha = datetime.strptime(fecha_emision, "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    try:
                        fecha = datetime.fromisoformat(fecha_emision)
                    except (ValueError, IndexError):
                        fecha = datetime.now()

                try:
                    fecha_timbrado = datetime.strptime(fecha_certificacion, "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    fecha_timbrado = None

                try:
                    total = Decimal(monto)
                except Exception:
                    total = Decimal("0")

                estado = "Vigente" if estatus == "1" else "Cancelado"
                tipo_comprobante = EFECTO_TO_TIPO.get(efecto, efecto)

                comprobante = Comprobante(
                    uuid=uuid,
                    fecha=fecha,
                    rfc_emisor=rfc_emisor,
                    nombre_emisor=nombre_emisor,
                    regimen_emisor="",
                    rfc_receptor=rfc_receptor,
                    nombre_receptor=nombre_receptor,
                    uso_cfdi="",
                    subtotal=total,
                    total=total,
                    tipo_comprobante=tipo_comprobante,
                    tipo=tipo,
                    estado=estado,
                    fecha_timbrado=fecha_timbrado,
                )

                if uuid:
                    db.upsert_comprobante(comprobante)
                    count += 1

    return count


def _monthly_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks = []
    current = start

    while current <= end:
        last_day = calendar.monthrange(current.year, current.month)[1]
        chunk_end = min(date(current.year, current.month, last_day), end)
        chunks.append((current, chunk_end))

        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return chunks
