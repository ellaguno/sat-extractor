"""Extracción de paquetes ZIP descargados del SAT."""

import zipfile
from pathlib import Path

from rich.console import Console

from ..db.repository import Repository
from ..parser.cfdi import parse_cfdi

console = Console()


def extract_and_process(
    zip_path: Path,
    db: Repository,
    tipo: str = "recibida",
) -> int:
    """Extrae un ZIP del SAT, parsea los XMLs e inserta en la BD.

    Returns:
        Cantidad de CFDIs nuevos insertados.
    """
    count = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]

        for name in xml_names:
            try:
                xml_bytes = zf.read(name)
                comprobante = parse_cfdi(xml_bytes, tipo)
                if comprobante.uuid:
                    db.upsert_comprobante(comprobante)
                    count += 1
            except Exception as e:
                console.print(f"[yellow]  Advertencia: Error procesando {name}: {e}")

    return count


def import_xml_directory(
    directory: Path,
    db: Repository,
    tipo: str = "recibida",
    rfc_propio: str | None = None,
) -> dict[str, int]:
    """Importa todos los XMLs de un directorio a la BD.

    Si rfc_propio se proporciona, auto-detecta si cada CFDI es
    emitida o recibida comparando el RFC del emisor.

    Returns:
        Dict con conteos: {"emitida": n, "recibida": n, "errors": n}
    """
    if not directory.is_dir():
        raise NotADirectoryError(f"No es un directorio: {directory}")

    xml_files = list(directory.glob("**/*.xml")) + list(directory.glob("**/*.XML"))
    # Eliminar duplicados por nombre (case-insensitive)
    seen = set()
    unique_files = []
    for f in xml_files:
        key = str(f).lower()
        if key not in seen:
            seen.add(key)
            unique_files.append(f)

    counts = {"emitida": 0, "recibida": 0, "errors": 0}

    for xml_path in unique_files:
        try:
            # Parsear primero sin tipo para detectar
            comprobante = parse_cfdi(xml_path.read_bytes(), tipo)

            # Auto-detectar tipo si tenemos el RFC
            if rfc_propio:
                if comprobante.rfc_emisor.upper() == rfc_propio.upper():
                    comprobante.tipo = "emitida"
                else:
                    comprobante.tipo = "recibida"

            if comprobante.uuid:
                db.upsert_comprobante(comprobante)
                counts[comprobante.tipo] += 1
        except Exception as e:
            console.print(f"[yellow]  Advertencia: {xml_path.name}: {e}")
            counts["errors"] += 1

    if counts["errors"]:
        console.print(f"[yellow]  {counts['errors']} archivo(s) con errores")

    return counts
