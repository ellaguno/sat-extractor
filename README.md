# SAT Extractor

Herramienta de línea de comandos para descargar, almacenar y analizar facturas electrónicas (CFDIs) del SAT mexicano usando tu FIEL (Firma Electrónica Avanzada).

## Características

- **Descarga masiva** de CFDIs emitidos y recibidos directamente del web service del SAT
- **Importación local** de archivos XML (CFDI 3.3 y 4.0)
- **Base de datos SQLite** para almacenamiento y consultas rápidas
- **Visualizador interactivo** en terminal con dashboard anual, detalle mensual, búsquedas y más
- **Exportación a Excel** con reportes mensuales y anuales
- **Cálculo de impuestos provisionales** (IVA a pagar e ISR provisional estimado)
- **Análisis fiscal inteligente** — clasificación automática de gastos deducibles/no deducibles según régimen fiscal, con reglas basadas en la LISR vigente
- **Integración con IA** (opcional) — usa Claude API para clasificar gastos ambiguos y generar sugerencias de optimización fiscal

## Requisitos

- Python 3.12+
- FIEL vigente del SAT (archivos `.cer` y `.key` + contraseña) — solo para descarga del SAT

## Instalación

```bash
git clone https://github.com/ellaguno/sat-extractor.git
cd sat-extractor

python3 -m venv .venv
source .venv/bin/activate
pip install cfdiclient lxml openpyxl rich cryptography

# Opcional: para análisis fiscal con IA
pip install anthropic
```

## Configuración

```bash
cp config.example.toml config.toml
chmod 600 config.toml    # proteger credenciales
```

Editar `config.toml`:

```toml
[fiel]
cer_path = "/ruta/a/certificado.cer"
key_path = "/ruta/a/llave_privada.key"
password = "tu_contraseña_fiel"

[sat]
rfc = "TU_RFC"

[database]
path = "~/satextractor.db"

[export]
output_dir = "~/reportes_sat"

# Opcional: análisis fiscal inteligente
[contribuyente]
regimen = "612"                  # 612=PFAE, 626=RESICO

[ia]
# api_key = ""                   # O usa ANTHROPIC_API_KEY env var
# model = "claude-sonnet-4-6"
```

## Uso

```bash
source .venv/bin/activate
python -m satextractor
```

## Pantallas

### Menú principal

```
╭──────────────────────────────────────╮
│     SAT CFDI Extractor               │
│     Gestión de facturas electrónicas  │
╰──────────────────────────────────────╯

BD: 156 CFDIs (42 emitidas, 114 recibidas)

Menú Principal
  [1] Descargar CFDIs del SAT
  [2] Importar XMLs desde directorio
  [3] Visualizar datos
  [4] Exportar a Excel
  [5] Análisis Fiscal Inteligente
  [0] Salir
```

### Dashboard anual

```
                              Dashboard 2025
┌────────────┬──────────┬────────────────┬──────────┬────────────────┬──────────────┬──────────────┬────────────────┐
│ Mes        │ Emitidas │     Facturado  │ Recibidas│       Gastos   │  IVA x Pagar │   ISR Prov.  │       Balance  │
├────────────┼──────────┼────────────────┼──────────┼────────────────┼──────────────┼──────────────┼────────────────┤
│ Enero      │    4     │    $58,000.00  │    12    │    $23,450.00  │   $5,528.00  │   $4,120.35  │    $34,550.00  │
│ Febrero    │    6     │    $92,300.00  │    15    │    $31,200.00  │   $9,776.00  │   $8,547.22  │    $61,100.00  │
│ Marzo      │    5     │    $71,500.00  │    18    │    $45,800.00  │   $4,112.00  │   $3,280.18  │    $25,700.00  │
│ Abril      │    3     │    $43,000.00  │     9    │    $18,600.00  │   $3,904.00  │   $2,890.44  │    $24,400.00  │
│ Mayo       │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Junio      │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Julio      │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Agosto     │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Septiembre │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Octubre    │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Noviembre  │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
│ Diciembre  │    -     │      $0.00     │     -    │        $0.00   │       -      │       -      │         -      │
├────────────┼──────────┼────────────────┼──────────┼────────────────┼──────────────┼──────────────┼────────────────┤
│ TOTAL      │          │  $264,800.00   │          │  $119,050.00   │ $23,320.00   │ $18,838.19   │  $145,750.00   │
└────────────┴──────────┴────────────────┴──────────┴────────────────┴──────────────┴──────────────┴────────────────┘
* IVA x Pagar = IVA cobrado - IVA acreditable - IVA retenido
* ISR Prov. = Art.96 LISR sobre (ingresos - deducciones) - ISR retenido - pagos prev.
```

### Detalle mensual

```
╭───────────────── Marzo 2025 ──────────────────╮
│ Emitidas:  5 CFDIs  $71,500.00                │
│ Recibidas: 18 CFDIs  $45,800.00               │
╰───────────────────────────────────────────────╯

           Emitidas - Marzo
┌────────────┬──────────────────────┬──────────────────────────┬──────────────┬──────────┬──────────┐
│ Fecha      │ Contraparte          │ Concepto                 │        Total │ Estado   │ UUID     │
├────────────┼──────────────────────┼──────────────────────────┼──────────────┼──────────┼──────────┤
│ 05/03/2025 │ EMPRESA SA DE CV     │ Servicios de consultoría │  $23,200.00  │ Vigente  │ 4A3B...  │
│ 12/03/2025 │ TECH SOLUTIONS MX    │ Desarrollo de software   │  $18,500.00  │ Vigente  │ 7C2D...  │
│ 15/03/2025 │ COMERCIAL DEL NORTE  │ Asesoría técnica         │  $12,800.00  │ Vigente  │ 9E1F...  │
│ 22/03/2025 │ GRUPO INDUSTRIAL     │ Capacitación personal    │   $9,500.00  │ Vigente  │ B5A2...  │
│ 28/03/2025 │ DISTRIBUIDORA CENTRO │ Soporte técnico mensual  │   $7,500.00  │ Vigente  │ D8C3...  │
├────────────┼──────────────────────┼──────────────────────────┼──────────────┼──────────┼──────────┤
│            │                      │ TOTAL (5 CFDIs)          │  $71,500.00  │          │          │
└────────────┴──────────────────────┴──────────────────────────┴──────────────┴──────────┴──────────┘

           Recibidas - Marzo
┌────────────┬──────────────────────┬──────────────────────────┬──────────────┬──────────┬──────────┐
│ Fecha      │ Contraparte          │ Concepto                 │        Total │ Estado   │ UUID     │
├────────────┼──────────────────────┼──────────────────────────┼──────────────┼──────────┼──────────┤
│ 02/03/2025 │ CFE SUMINISTRADOR    │ Servicio de energía      │   $1,850.00  │ Vigente  │ A1B2...  │
│ 05/03/2025 │ TELMEX SA            │ Servicio de internet     │     $699.00  │ Vigente  │ C3D4...  │
│ ...        │                      │                          │              │          │          │
├────────────┼──────────────────────┼──────────────────────────┼──────────────┼──────────┼──────────┤
│            │                      │ TOTAL (18 CFDIs)         │  $45,800.00  │          │          │
└────────────┴──────────────────────┴──────────────────────────┴──────────────┴──────────┴──────────┘
```

### Detalle de un CFDI

```
╭─────────────────────── Detalle CFDI ────────────────────────╮
│                                                              │
│  UUID:    4A3B1C2D-5E6F-7A8B-9C0D-1E2F3A4B5C6D             │
│  Fecha:   05/03/2025 14:30:22                                │
│  Tipo:    Ingreso                     Estado: Vigente        │
│                                                              │
│  Emisor:  XXXX000000XXX                                      │
│           JUAN PÉREZ GARCÍA                   │
│           Régimen: 612 - Personas Físicas con Act. Emp.      │
│                                                              │
│  Receptor: EMP850101AAA                                      │
│            EMPRESA SA DE CV                                  │
│            Uso CFDI: G03 - Gastos en general                 │
│                                                              │
│  SubTotal:  $20,000.00     Descuento:  $0.00                 │
│  IVA:        $3,200.00     ISR Ret:    $0.00                 │
│  Total:     $23,200.00     Moneda: MXN                       │
│                                                              │
│  Método: PUE               Forma: 03 - Transferencia        │
╰──────────────────────────────────────────────────────────────╯

  Conceptos
┌─────────────┬──────────────────────────┬──────────┬──────────────┬──────────────┐
│ Clave P/S   │ Descripción              │ Cantidad │ P. Unitario  │    Importe   │
├─────────────┼──────────────────────────┼──────────┼──────────────┼──────────────┤
│ 80111600    │ Servicios de consultoría │      1.0 │  $20,000.00  │  $20,000.00  │
│             │ en tecnología            │          │              │              │
└─────────────┴──────────────────────────┴──────────┴──────────────┴──────────────┘
```

### Descarga del SAT

```
Descargar CFDIs del SAT
  [1] Recibidas
  [2] Emitidas
  [3] Ambas
Tipo: 3
Año: 2025
Mes inicio: 1
Mes fin: 3

Autenticando con FIEL...
  Certificado: XXXX000000XXXXXXXXX
  Vigencia: 2024-11-08 - 2028-11-08

Descargando emitidas: 2025-01-01 → 2025-03-31
  Solicitud: a1b2c3d4-e5f6-7890-abcd-ef1234567890
  Listos: 1 paquete(s), 15 CFDI(s)
  Descargado: a1b2c3d4.zip
emitidas 2025-01-01 → 2025-01-31 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  33%
  Procesados: 15 CFDIs (12 nuevos, 3 actualizados)

Descargando recibidas: 2025-01-01 → 2025-03-31
  CFDI no disponible, usando Metadata...
  Solicitud Metadata: b2c3d4e5-f6a7-8901-bcde-f23456789012
  Listos: 1 paquete(s), 45 CFDI(s)
  45 CFDI(s) desde Metadata
recibidas 2025-01-01 → 2025-01-31 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%
```

### Análisis Fiscal Inteligente

```
Análisis Fiscal Inteligente
Régimen: 612

  [1] Clasificar deducciones del periodo
  [2] Resumen por categoría de gasto
  [3] Sugerencias de optimización
  [4] Consultar deducibilidad de un CFDI
  [0] Volver
```

#### Clasificar deducciones

Analiza cada concepto de las facturas recibidas y determina si es deducible según el régimen fiscal configurado:

```
               Deducciones - 2025
┌───┬──────────┬──────────────────────┬──────────────────┬─────────────┬─────────────┬──────┬───┐
│ # │ Fecha    │ Concepto             │ Categoría        │       Monto │   Deducible │    % │   │
├───┼──────────┼──────────────────────┼──────────────────┼─────────────┼─────────────┼──────┼───┤
│ 1 │ 05/03    │ Servicio de internet │ telecomunicacion │     $699.00 │     $699.00 │ 100% │ V │
│ 2 │ 10/03    │ Comida ejecutiva     │ alimentos_rest.  │   $2,500.00 │   $2,287.50 │  92% │ V │
│ 3 │ 15/03    │ Gasolina Premium     │ combustible      │     $980.00 │     $980.00 │ 100% │ V │
│ 4 │ 20/03    │ Laptop Dell XPS      │ equipo_computo   │  $35,000.00 │  $10,500.00 │ 100% │ ! │
│ 5 │ 25/03    │ Cena en restaurante  │ alimentos_rest.  │   $1,800.00 │       $0.00 │   0% │ X │
└───┴──────────┴──────────────────────┴──────────────────┴─────────────┴─────────────┴──────┴───┘
  V=deducible  !=alertas  ?=baja confianza  X=no deducible
```

Reglas implementadas:
- **Restaurantes**: 91.5% deducible solo con pago con tarjeta (Art. 28 Fracc. XX LISR)
- **Combustibles**: 100% deducible solo con pago electrónico (Art. 27 Fracc. III LISR)
- **Inversiones**: deducción por depreciación fiscal (equipo cómputo 30%, vehículos 25%, mobiliario 10%)
- **Pagos en efectivo > $2,000**: NO deducibles (Art. 27 Fracc. III LISR)
- **CFDIs cancelados**: NO deducibles
- **Deducciones personales**: médicos, colegiaturas, funerarios, etc. (Art. 151 LISR)
- Soporte para régimen 612 (PFAE) y 626 (RESICO)

#### Sugerencias de optimización

Genera recomendaciones personalizadas basadas en los patrones de gasto:

```
╭─ 1. Restaurantes pagados en efectivo ──────────────────────────────────────╮
│ Tienes $15,000 en restaurantes pagados en efectivo. Si pagas con tarjeta,  │
│ el 91.5% sería deducible. (ahorro estimado: $4,117.50)                     │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ 2. Sin deducciones personales registradas ────────────────────────────────╮
│ No se encontraron gastos médicos, colegiaturas ni otras deducciones        │
│ personales (Art. 151 LISR).                                                │
╰────────────────────────────────────────────────────────────────────────────╯

* Estas sugerencias son educativas y no sustituyen asesoría fiscal profesional.
```

Si se configura la API de Claude (`[ia]` en config.toml o variable `ANTHROPIC_API_KEY`), las sugerencias se enriquecen con análisis de IA. Sin API, el motor funciona al 100% con reglas locales.

## Exportación a Excel

El reporte anual genera un archivo `.xlsx` con:

1. **Pestaña "Resumen Anual"** — tabla de emitidas, recibidas, e impuestos provisionales por mes
2. **Pestañas Enero–Diciembre** — detalle de cada mes con emitidas arriba y recibidas abajo, incluyendo concepto

El reporte incluye una sección de **Impuestos Provisionales** con:
- IVA a pagar (cobrado - acreditable - retenido)
- ISR provisional estimado (Art. 96 LISR)

## Notas sobre datos del SAT

| Dato                  | XML (emitidas) | Metadata (recibidas) |
|-----------------------|:--------------:|:-------------------:|
| UUID, fecha, RFC      |       ✓        |          ✓          |
| Total                 |       ✓        |          ✓          |
| Estado                |       ✓        |          ✓          |
| SubTotal, IVA, ISR    |       ✓        |          ✗          |
| Conceptos             |       ✓        |          ✗          |
| Método/forma de pago  |       ✓        |          ✗          |

El SAT no permite descargar XMLs de facturas recibidas para personas físicas. El programa usa Metadata automáticamente como fallback. Para obtener datos completos de recibidas, descarga los XMLs manualmente desde el [portal del SAT](https://portalcfdi.facturaelectronica.sat.gob.mx/) e impórtalos con la opción [2].

## Documentación

Ver [INSTRUCCIONES.md](INSTRUCCIONES.md) para documentación completa: configuración de FIEL, uso detallado de cada función, solución de problemas.

## Licencia

MIT
