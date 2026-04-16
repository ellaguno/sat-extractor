# SAT CFDI Extractor - Instrucciones de Uso

## Requisitos

- Python 3.12+
- FIEL vigente del SAT (archivos `.cer` y `.key` + contraseña)

## Instalacion

```bash
cd /home/ellaguno/MEGA/Proyectos/SesoLibre/Proyectos/impuestos

# Crear entorno virtual (solo la primera vez)
python3 -m venv .venv

# Activar entorno
source .venv/bin/activate

# Instalar dependencias (solo la primera vez)
pip install cfdiclient lxml openpyxl rich cryptography

# Opcional: para analisis fiscal con IA
pip install anthropic
```

## Configuracion

Copiar el archivo de ejemplo y editarlo:

```bash
cp config.example.toml config.toml
```

Editar `config.toml` con tus datos:

```toml
[fiel]
cer_path = "/ruta/completa/a/tu/certificado.cer"
key_path = "/ruta/completa/a/tu/llave_privada.key"
password = "tu_contraseña_de_fiel"     # Opcional: si no se pone, se pide al ejecutar

[sat]
rfc = "TU_RFC_AQUI"                    # Ejemplo: "XAXX010101000"

[database]
path = "~/satextractor.db"            # Donde se guarda la base de datos

[export]
output_dir = "~/reportes_sat"          # Donde se guardan los Excel

# Opcional: analisis fiscal inteligente
[contribuyente]
regimen = "612"                        # 612=PFAE, 626=RESICO
# actividad = "Desarrollo de software" # Tu actividad economica

[ia]
# api_key = ""                         # O usa variable ANTHROPIC_API_KEY
# model = "claude-sonnet-4-6"          # Modelo de IA a usar
# cache_dias = 90                      # Dias que se cachean clasificaciones
```

### Sobre la FIEL

- Los archivos `.cer` y `.key` son los que descargaste del portal del SAT
  cuando tramitaste tu Firma Electronica Avanzada.
- La contraseña es la que elegiste al generar la FIEL.
- La FIEL tiene vigencia de 4 años. Puedes verificar la vigencia al
  ejecutar el programa (se muestra al autenticarse).
- **Nota de seguridad**: si pones el password en config.toml, asegurate
  de que el archivo tenga permisos restrictivos:
  ```bash
  chmod 600 config.toml
  ```

## Ejecucion

```bash
source .venv/bin/activate
python -m satextractor
```

O con un archivo de configuracion especifico:

```bash
python -m satextractor --config /ruta/a/config.toml
```

## Menu Principal

```
BD: 31 CFDIs (6 emitidas, 25 recibidas)

Menu Principal
  [1] Descargar CFDIs del SAT
  [2] Importar XMLs desde directorio
  [3] Visualizar datos
  [4] Exportar a Excel
  [5] Analisis Fiscal Inteligente
  [0] Salir
```

Al iniciar se muestra un conteo de los CFDIs almacenados en la base de datos.

---

### [1] Descargar CFDIs del SAT

Descarga facturas directamente del web service del SAT usando tu FIEL.

- **Recibidas**: facturas que te emitieron a ti
- **Emitidas**: facturas que tu emitiste
- **Ambas**: descarga las dos en secuencia

Se pide el rango de fechas (año, mes inicio, mes fin). El programa
divide la descarga por meses y muestra el progreso.

**Notas importantes:**
- No se pueden descargar fechas futuras (se limita al dia de hoy)
- El SAT puede tardar en procesar solicitudes (el programa espera
  automaticamente)
- Si el SAT rechaza una solicitud por saturacion, el programa reintenta
- **Emitidas** se descargan como XML completo (todos los campos,
  incluyendo conceptos/descripciones)
- **Recibidas**: el SAT no permite descargar XMLs de recibidas para
  personas fisicas. El programa automaticamente usa "Metadata"
  (datos resumidos: UUID, RFC, nombre, monto, tipo, estado, fecha).
  **Los Metadata NO incluyen**: subtotal, IVA trasladado, ISR retenido,
  IVA retenido, método/forma de pago, moneda, ni conceptos/descripciones.
  Para tener estos datos, descarga los XMLs manualmente desde el portal
  del SAT e importalos con la opcion [2] (ver seccion abajo).

---

### [2] Importar XMLs desde directorio

Si ya tienes archivos XML de facturas descargados manualmente,
puedes importarlos desde un directorio local.

- Busca archivos `.xml` recursivamente en el directorio indicado
- Detecta automaticamente CFDI version 3.3 y 4.0
- Si el UUID ya existe en la base de datos (por ejemplo, de una
  descarga previa via Metadata), los datos se **enriquecen**: se
  agregan subtotal, IVA, ISR, conceptos, metodo de pago, etc.

**Esto es especialmente util para facturas recibidas**, donde la
descarga automatica solo obtiene Metadata (sin IVA ni conceptos).
Al importar los XMLs, los registros se completan con toda la
informacion.

#### Como descargar XMLs desde el portal del SAT

1. Entra a [https://portalcfdi.facturaelectronica.sat.gob.mx/](https://portalcfdi.facturaelectronica.sat.gob.mx/)
2. Inicia sesion con tu **FIEL** (certificado .cer + llave .key + contraseña)
3. En el menu, selecciona **"Consultar Facturas Recibidas"**
4. Filtra por fecha (mes/año) y haz clic en **"Buscar CFDI"**
5. Selecciona las facturas que quieras (o usa "Seleccionar Todos")
6. Haz clic en **"Descargar"** — se descarga un ZIP con los XMLs
7. Descomprime el ZIP en una carpeta, por ejemplo `~/xmls_recibidas/`
8. En el programa, usa la opcion **[2] Importar XMLs desde directorio**
   e indica la ruta de la carpeta

**Tip**: puedes descargar un mes a la vez. El programa detecta
duplicados automaticamente, asi que no importa si re-importas
archivos que ya tenias.

---

### [3] Visualizar datos

Submenú interactivo para explorar la informacion descargada:

```
Visualizar Datos
  [1] Dashboard anual
  [2] Detalle mensual
  [3] Buscar por RFC o nombre
  [4] Ver detalle de un CFDI
  [5] Top emisores / receptores
  [0] Volver
```

#### [3.1] Dashboard anual

Tabla de los 12 meses con columnas:

| Mes | Emitidas | Total Emi. | Recibidas | Total Rec. | IVA Trasl. | ISR Ret. | Balance |

- Los meses sin datos aparecen atenuados
- El **balance** (emitidas - recibidas) se muestra en verde si es
  positivo y en rojo si es negativo
- Incluye fila de totales anuales
- Al final puedes escribir un numero de mes para entrar directamente
  al detalle de ese mes

#### [3.2] Detalle mensual

Muestra un panel resumen del mes y luego dos tablas:

1. **Emitidas**: con fecha, contraparte (receptor), concepto, total,
   estado y UUID
2. **Recibidas**: misma estructura (contraparte = emisor)

Cada tabla incluye subtotal al final. Puedes escribir los primeros
caracteres de un UUID para ver el detalle completo de esa factura.

#### [3.3] Buscar por RFC o nombre

Busca facturas por:
- **RFC exacto**: por ejemplo `SCE070306R20`
- **Nombre parcial**: por ejemplo `GOOGLE` o `Kuspit`

Muestra los resultados en tabla con opcion de ver detalle por UUID.

#### [3.4] Ver detalle de un CFDI

Ingresa un UUID (completo o los primeros caracteres) y muestra un
panel con toda la informacion:

- Datos generales: UUID, fecha, tipo, estado
- Emisor: RFC, nombre, regimen fiscal
- Receptor: RFC, nombre, uso CFDI
- Montos: subtotal, descuento, total, moneda, tipo de cambio
- Impuestos: IVA trasladado, ISR retenido, IVA retenido
- Pago: metodo de pago, forma de pago, lugar de expedicion
- **Tabla de conceptos**: clave producto/servicio, descripcion,
  cantidad, precio unitario, importe

Si la factura fue descargada via Metadata (recibidas), los conceptos
no estaran disponibles.

#### [3.5] Top emisores / receptores

Muestra dos rankings para el año seleccionado:

1. **Top Proveedores**: emisores de facturas recibidas, ordenados por
   monto total (a quién le compraste mas)
2. **Top Clientes**: receptores de facturas emitidas, ordenados por
   monto total (a quién le facturaste mas)

---

### [4] Exportar a Excel

Genera archivos `.xlsx` en el directorio configurado en `output_dir`.

**Reporte mensual** (`reporte_mensual_YYYY_MM.xlsx`):
- Una sola hoja con el nombre del mes
- Seccion superior: **Emitidas** con headers, datos y subtotal
- Seccion inferior: **Recibidas** con headers, datos y subtotal
- Incluye columna de **Concepto** (descripcion de la factura)

**Reporte anual** (`reporte_anual_YYYY.xlsx`):
- Pestaña **"Resumen Anual"**: tabla de emitidas (12 meses + total)
  seguida de tabla de recibidas (12 meses + total). Columnas: mes,
  CFDIs, ingresos, egresos, IVA trasladado, ISR retenido, IVA
  retenido, total
- Pestañas **Enero** a **Diciembre**: detalle del mes con emitidas
  arriba y recibidas abajo, incluyendo concepto

Antes de generar, el programa muestra cuantos registros se incluiran.
Si dice "0 recibidas, 0 emitidas" verifica que estas pidiendo el
mes/año correcto.

### [5] Analisis Fiscal Inteligente

Motor de clasificacion automatica de deducciones basado en las reglas
de la LISR vigente. Clasifica cada concepto de tus facturas recibidas
como deducible o no segun tu regimen fiscal.

```
Analisis Fiscal Inteligente
Regimen: 612

  [1] Clasificar deducciones del periodo
  [2] Resumen por categoria de gasto
  [3] Sugerencias de optimizacion
  [4] Consultar deducibilidad de un CFDI
  [0] Volver
```

#### [5.1] Clasificar deducciones del periodo

Analiza todas las facturas recibidas de un mes o año completo.
Muestra cada concepto con su categoria, porcentaje deducible,
monto deducible y alertas.

Indicadores en la columna final:
- **V** = Deducible (alta confianza)
- **!** = Deducible con alertas (revisar requisitos)
- **?** = Baja confianza de clasificacion (la clave SAT no se reconocio)
- **X** = No deducible

#### [5.2] Resumen por categoria de gasto

Agrupa todos los gastos del año por categoria fiscal:

- Gastos de operacion, servicios profesionales, telecomunicaciones, etc.
- Software y licencias, papeleria, mantenimiento
- Restaurantes (91.5% deducible con pago con tarjeta)
- Combustibles (100% con pago electronico)
- Inversiones (equipo de computo, vehiculos, mobiliario) con depreciacion
- Deducciones personales (medicos, colegiaturas, etc.)

Muestra totales deducibles y no deducibles, y alertas por categoria.

#### [5.3] Sugerencias de optimizacion

Genera recomendaciones basadas en tus patrones de gasto:

- **Pagos en efectivo > $2,000**: se pierden como deduccion
  (Art. 27 Fracc. III LISR)
- **Restaurantes en efectivo**: no son deducibles; con tarjeta
  serian al 91.5% (Art. 28 Fracc. XX LISR)
- **Deducciones personales faltantes**: medicos, colegiaturas,
  seguros de gastos medicos, aportaciones a retiro
- **Proporcion deducciones/ingresos**: alerta si es muy baja

Si configuras la API de IA (`[ia]` en config.toml), las sugerencias
se enriquecen con analisis personalizado. Sin API, el motor funciona
al 100% con reglas locales.

#### [5.4] Consultar deducibilidad de un CFDI

Ingresa el UUID de una factura recibida y muestra el analisis
completo de cada concepto: categoria, porcentaje, fundamento legal
de la LISR, requisitos y alertas.

#### Reglas fiscales implementadas

El motor incluye reglas para el regimen 612 (PFAE) basadas en:

| Regla | Fundamento | Detalle |
|-------|-----------|---------|
| Gastos de operacion | Art. 103 Fracc. III LISR | 100% si estrictamente indispensable |
| Restaurantes | Art. 28 Fracc. XX LISR | 91.5% solo con pago con tarjeta |
| Combustibles | Art. 27 Fracc. III LISR | 100% solo con pago electronico |
| Pagos en efectivo > $2,000 | Art. 27 Fracc. III LISR | NO deducibles |
| Vehiculos (inversion) | Art. 36 Fracc. II LISR | Limite $175,000 (combustion), $250,000 (electricos) |
| Equipo de computo | Art. 34 Fracc. VII LISR | Depreciacion 30% anual |
| Mobiliario oficina | Art. 34 Fracc. III LISR | Depreciacion 10% anual |
| Automoviles | Art. 34 Fracc. VI LISR | Depreciacion 25% anual |
| Honorarios medicos | Art. 151 Fracc. I LISR | 100% con pago electronico |
| Colegiaturas | Decreto DOF 26/12/2013 | Limites por nivel educativo |
| Gastos funerarios | Art. 151 Fracc. II LISR | Limite 1 UMA anual |
| Donativos | Art. 151 Fracc. III LISR | Limite 7% utilidad fiscal |
| CFDIs cancelados | Art. 27 Fracc. XVIII LISR | NO deducibles |

Las reglas se encuentran en `satextractor/fiscal/reglas_deducciones.toml`
y el catalogo de claves SAT en `satextractor/fiscal/catalogo_sat.toml`.
Puedes editarlos para ajustar reglas o agregar claves.

**Nota importante**: Las clasificaciones y sugerencias son educativas
y no sustituyen asesoria fiscal profesional.

---

## Datos extraidos de cada CFDI

| Campo              | Descripcion                                       | XML | Metadata |
|--------------------|---------------------------------------------------|-----|----------|
| UUID               | Identificador unico del timbre fiscal             | Si  | Si       |
| Fecha              | Fecha de emision                                  | Si  | Si       |
| RFC Emisor         | RFC de quien emitio la factura                    | Si  | Si       |
| Nombre Emisor      | Razon social del emisor                           | Si  | Si       |
| RFC Receptor       | RFC de quien recibio la factura                   | Si  | Si       |
| Nombre Receptor    | Razon social del receptor                         | Si  | Si       |
| Tipo Comprobante   | I=Ingreso, E=Egreso, T=Traslado, P=Pago, N=Nomina| Si  | Si       |
| Total              | Monto total con impuestos                         | Si  | Si       |
| Estado             | Vigente o Cancelado                               | Si  | Si       |
| SubTotal           | Monto antes de impuestos                          | Si  | No       |
| Descuento          | Descuento aplicado                                | Si  | No       |
| IVA Trasladado     | IVA cobrado                                       | Si  | No       |
| ISR Retenido       | ISR retenido                                      | Si  | No       |
| IVA Retenido       | IVA retenido                                      | Si  | No       |
| Metodo de Pago     | PUE (una exhibicion) o PPD (parcialidades)        | Si  | No       |
| Forma de Pago      | 01=Efectivo, 03=Transferencia, etc.               | Si  | No       |
| Moneda             | MXN, USD, etc.                                    | Si  | No       |
| Conceptos          | Descripcion de productos/servicios facturados     | Si  | No       |

Las columnas marcadas "No" en Metadata quedan vacias para facturas
recibidas que se descargaron via Metadata.

## Base de datos

La base de datos SQLite se guarda en la ruta configurada (default:
`~/satextractor.db`). Puedes consultarla directamente:

```bash
sqlite3 ~/satextractor.db

-- Ver cuantas facturas hay
SELECT tipo, COUNT(*), SUM(total) FROM comprobantes GROUP BY tipo;

-- Ver facturas de un RFC
SELECT fecha, total, nombre_emisor FROM comprobantes
WHERE rfc_emisor = 'XAXX010101000';

-- Ver resumen por mes
SELECT strftime('%Y-%m', fecha) as mes, tipo, COUNT(*), SUM(total)
FROM comprobantes GROUP BY mes, tipo ORDER BY mes;

-- Ver conceptos de una factura
SELECT c.descripcion, c.cantidad, c.importe
FROM conceptos c WHERE c.uuid = 'TU-UUID-AQUI';
```

## Solucion de problemas

**"No se pudo desencriptar la llave privada"**
- Verifica que el password en config.toml sea correcto
- Es la contraseña que usaste al generar tu FIEL en el SAT

**"Fecha final invalida"**
- No se puede descargar un periodo que no ha terminado
- El programa limita automaticamente al dia de hoy

**"CFDI no disponible, usando Metadata..."**
- El SAT no permite descargar XMLs de facturas recibidas para
  personas fisicas. El programa cambia automaticamente a Metadata
- Los datos basicos (UUID, RFC, monto, estado) se obtienen
  correctamente, pero **no se incluyen**: IVA, ISR, subtotal,
  conceptos, metodo de pago ni forma de pago
- Para obtener estos datos, descarga los XMLs manualmente desde
  el portal del SAT e importalos con la opcion [2]

**"Solicitud rechazada"**
- El SAT tiene limite de solicitudes. El programa reintenta
  automaticamente con espera incremental
- Si persiste, espera unos minutos y vuelve a intentar

**Excel vacio**
- Verifica que estas exportando el mes correcto
- Usa Visualizar datos > Dashboard anual para confirmar que hay datos
- El reporte mensual por default usa el mes actual

**"No se encontro config.toml"**
- Copia config.example.toml a config.toml y edita tus datos
- Sin config.toml puedes usar importacion local y visualizacion,
  pero no la descarga del SAT
