"""Carga y validación de la FIEL para autenticación con el SAT."""

import getpass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_der_private_key,
)
from cryptography.x509 import load_der_x509_certificate


def _decrypt_key_der(key_der: bytes, password: str) -> bytes:
    """Desencripta la llave privada .key del SAT (PKCS#8 DER encriptado)
    y retorna la llave en formato DER sin encriptar.

    La librería cryptography soporta los formatos de encriptación que
    pycryptodome (usada por cfdiclient) no maneja.
    Re-exporta como TraditionalOpenSSL (PKCS#1) que es lo que pycryptodome espera.
    """
    private_key = load_der_private_key(key_der, password.encode("utf-8"))
    # Re-exportar como PKCS#1 DER (TraditionalOpenSSL) — formato que pycryptodome soporta
    return private_key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )


def load_fiel_interactive(cer_path: Path, key_path: Path, password: str | None = None):
    """Carga la FIEL, usando password del config o solicitándolo interactivamente.

    Retorna un objeto cfdiclient.Fiel listo para usar.
    """
    from cfdiclient import Fiel

    if not cer_path.exists():
        raise FileNotFoundError(f"No se encontró el certificado: {cer_path}")
    if not key_path.exists():
        raise FileNotFoundError(f"No se encontró la llave privada: {key_path}")

    cer_der = cer_path.read_bytes()
    key_der_encrypted = key_path.read_bytes()

    # Validar certificado
    cert_info = validate_certificate(cer_der)
    print(f"  Certificado: {cert_info['rfc']}")
    print(f"  Vigencia: {cert_info['not_before'].date()} - {cert_info['not_after'].date()}")

    if cert_info["expired"]:
        raise ValueError(
            f"El certificado expiró el {cert_info['not_after'].date()}. "
            "Renueva tu FIEL en el portal del SAT."
        )

    if not password:
        password = getpass.getpass("Contraseña de la llave privada FIEL: ")

    # Desencriptar con cryptography (soporta más formatos que pycryptodome)
    # y pasar la llave ya desencriptada a cfdiclient
    try:
        key_der = _decrypt_key_der(key_der_encrypted, password)
    except Exception as e:
        raise ValueError(
            f"No se pudo desencriptar la llave privada: {type(e).__name__}: {e}"
        ) from e

    # Pasar llave desencriptada (passphrase vacío ya que está sin encriptar)
    try:
        fiel = Fiel(cer_der, key_der, "")
    except Exception as e:
        raise ValueError(
            f"Error al cargar la FIEL en cfdiclient: {type(e).__name__}: {e}"
        ) from e

    return fiel


def validate_certificate(cer_der: bytes) -> dict:
    cert = load_der_x509_certificate(cer_der)
    subject = cert.subject

    # Extraer RFC del subject (OID 2.5.4.45 = UniqueIdentifier, contiene RFC + nombre)
    rfc = ""
    for attr in subject:
        oid = attr.oid.dotted_string
        # serialNumber (2.5.4.5) suele tener el RFC en certificados del SAT
        if oid == "2.5.4.5":
            rfc = attr.value.strip()
            break
    # Fallback: buscar en UniqueIdentifier
    if not rfc:
        for attr in subject:
            if attr.oid.dotted_string == "2.5.4.45":
                val = attr.value.strip()
                if len(val) >= 12:
                    rfc = val[:13] if len(val) >= 13 else val[:12]
                    break

    now = datetime.now(timezone.utc)
    return {
        "rfc": rfc,
        "not_before": cert.not_valid_before_utc,
        "not_after": cert.not_valid_after_utc,
        "expired": now > cert.not_valid_after_utc,
        "serial": cert.serial_number,
    }


def get_auth_token(fiel):
    """Obtiene un token de autenticación del web service del SAT."""
    from cfdiclient import Autenticacion

    auth = Autenticacion(fiel)
    token = auth.obtener_token()
    return token
