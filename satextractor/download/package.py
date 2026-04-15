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
) -> int:
    """Importa todos los XMLs de un directorio a la BD.

    Returns:
        Cantidad de CFDIs importados.
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

    count = 0
    errors = 0

    for xml_path in unique_files:
        try:
            comprobante = parse_cfdi(xml_path.read_bytes(), tipo)
            if comprobante.uuid:
                db.upsert_comprobante(comprobante)
                count += 1
        except Exception as e:
            console.print(f"[yellow]  Advertencia: {xml_path.name}: {e}")
            errors += 1

    if errors:
        console.print(f"[yellow]  {errors} archivo(s) con errores")

    return count
