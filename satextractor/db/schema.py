"""Definición del esquema SQLite."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS comprobantes (
    uuid TEXT PRIMARY KEY,
    fecha TEXT NOT NULL,
    rfc_emisor TEXT NOT NULL,
    nombre_emisor TEXT,
    regimen_emisor TEXT,
    rfc_receptor TEXT NOT NULL,
    nombre_receptor TEXT,
    uso_cfdi TEXT,
    subtotal REAL NOT NULL,
    descuento REAL,
    total REAL NOT NULL,
    tipo_comprobante TEXT NOT NULL,
    metodo_pago TEXT,
    forma_pago TEXT,
    moneda TEXT DEFAULT 'MXN',
    tipo_cambio REAL,
    lugar_expedicion TEXT,
    iva_trasladado REAL,
    isr_retenido REAL,
    iva_retenido REAL,
    fecha_timbrado TEXT,
    estado TEXT DEFAULT 'Vigente',
    tipo TEXT NOT NULL,
    xml_raw BLOB,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conceptos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL REFERENCES comprobantes(uuid) ON DELETE CASCADE,
    clave_prod_serv TEXT,
    cantidad REAL,
    clave_unidad TEXT,
    descripcion TEXT,
    valor_unitario REAL,
    importe REAL,
    descuento REAL
);

CREATE TABLE IF NOT EXISTS descargas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_inicio TEXT NOT NULL,
    fecha_fin TEXT NOT NULL,
    tipo TEXT NOT NULL,
    id_solicitud TEXT,
    num_cfdis INTEGER,
    status TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_comprobantes_fecha ON comprobantes(fecha);
CREATE INDEX IF NOT EXISTS idx_comprobantes_rfc_emisor ON comprobantes(rfc_emisor);
CREATE INDEX IF NOT EXISTS idx_comprobantes_rfc_receptor ON comprobantes(rfc_receptor);
CREATE INDEX IF NOT EXISTS idx_comprobantes_tipo ON comprobantes(tipo);
CREATE INDEX IF NOT EXISTS idx_comprobantes_tipo_comprobante ON comprobantes(tipo_comprobante);
CREATE INDEX IF NOT EXISTS idx_conceptos_uuid ON conceptos(uuid);

CREATE TABLE IF NOT EXISTS clasificaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave_prod_serv TEXT NOT NULL,
    descripcion_hash TEXT NOT NULL,
    regimen TEXT NOT NULL,
    categoria TEXT,
    es_deducible INTEGER NOT NULL DEFAULT 0,
    porcentaje REAL NOT NULL DEFAULT 0,
    fundamento TEXT,
    requisitos TEXT,
    alertas TEXT,
    fuente TEXT NOT NULL DEFAULT 'regla_local',
    confianza REAL NOT NULL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(clave_prod_serv, descripcion_hash, regimen)
);

CREATE INDEX IF NOT EXISTS idx_clasificaciones_clave
    ON clasificaciones(clave_prod_serv, regimen);
"""
