# Contexto del Proyecto - Vet Suite

## Stack
- Python 3.13 (dev en 3.14)
- tkinter + ttkbootstrap
- openpyxl, cfdiclient, pdfplumber, lxml
- Empaquetado automático con GitHub Actions (tags `v*`)

## Módulos
- **INGRESOS**: descarga de Gmail, procesa XML+PDF, genera Excel
- **EGRESOS**: descarga del SAT, procesa, clasifica, genera Excel PUE/PPD
- **ESTÉTICA Y TRANSPORTES**: clientes, mascotas, rutas, tarifas
- **RECORDATORIOS**: citas y vacunas, envío por WhatsApp (wa.me)

---

## Arquitectura de configuración

### Configuración COMPARTIDA (los 4 módulos)

Vive en **`config_ui.json`** en la raíz de datos. Acceso único vía
`core/config_ui.py`.

**Claves:**
- `"tema"` → nombre del tema ttkbootstrap (ej. `"darkly"`)
- `"veterinaria"` → `{nombre, sucursal_activa, sucursales: [...]}`

**Claves adicionales:**
- `"modulos_activos"` → `{id_modulo: bool}` (activación global de módulos)
- `"perfiles"` → lista de perfiles `[{id, nombre, descripcion, modulos}]`.
  Si falta, se siembra con los defaults de `shared/perfiles.py`.

**Sucursales (fuente de verdad única):**
- Definidas en `config/veterinaria.py` (`SUCURSALES_DEFAULT`).
- Se editan SOLO desde **Configuración General → tab 🏥 Veterinaria**.
- Cada sucursal: `{id, nombre, nombre_corto, direccion, telefono, activa, coordenadas}`
- `nombre_corto` es el identificador estable que usan los módulos
  (ej. Egresos guarda `reg["sucursal"] = "Baalak"`).
- Los `nombre_corto` actuales: `"Baalak"`, `"Prado"`, `"Animalia"`.
- La activa se marca con el botón **● Marcar como activa** (no hay checkbox).
- El diálogo de detalle NO tiene checkbox "activa" — se maneja desde la tabla.

**Perfiles y usuarios (v2.2.0):**
- Los perfiles viven en `config_ui.json#perfiles`. Fuente de verdad.
- Las cuentas de usuario viven en `usuarios.json` (raíz de datos).
- El perfil activo vive SOLO en memoria (`core/sesion.py`).
- La app arranca en login. Sin sesión no hay módulos visibles.
- Solo `admin` puede gestionar perfiles, usuarios y módulos.

**Módulo compartido de acceso:**
- `core/config_ui.py` → única API para leer/escribir `config_ui.json`.
- `core/config_ui.leer()` crea el archivo con `{}` si no existe.
- `core/config_ui.set_seccion(nombre, valor)` → merge no destructivo.
- `AppPrincipal.__init__` fuerza un guardado inicial de defaults para que
  el archivo exista desde el primer arranque.

### Configuración POR MÓDULO

| Módulo | Carpeta datos | Archivos clave |
|--------|---------------|----------------|
| Ingresos | `<raíz>/ingresos/` (dev) o `~/Documents/Vet Suite/ingresos/` (prod) | `gmail_config.json`, `historial_autocompletado.json`, `registros_ingresos_YYYY.json`, `catalogo_qvet.json`, `categorias_manuales.json` |
| Egresos | `<raíz>/egresos/` o `~/Documents/Vet Suite/egresos/` | `config_egresos.json`, `proveedores_tc.json`, `proveedores_sucursal.json`, `observaciones_egresos.json`, `solicitud_sat_activa.json`, `registros_egresos_YYYY.json` |
| Estética y Transportes | `<raíz>/estetica_transportes/` o `~/Documents/Vet Suite/estetica_transportes/` | `clientes_maestro.json`, `mascotas.json`, `servicios_estetica.json`, `tarifas_transporte.json`, `transportes_cliente.json`, `geocoding_cache.json` |
| Recordatorios | `<raíz>/recordatorios/` o `~/Documents/Vet Suite/recordatorios/` | `agenda_importada.json`, `vacunas_importada.json`, `historial_envios.json` |

**Reglas de configuración por módulo:**
- Cada módulo lee/escribe SU carpeta de datos.
- NO acceder a archivos de otros módulos.
- La sucursal activa se lee SIEMPRE de `config.veterinaria.sucursal_activa()`,
  nunca se cachea en el módulo.
- `config_ui.json` es el ÚNICO JSON que vive en la raíz del proyecto.

### Estructura de datos en disco

**Dev:** `<raíz proyecto>/{ingresos,egresos,estetica_transportes,recordatorios}/` + `config_ui.json`
**Prod:** `~/Documents/Vet Suite/{ingresos,egresos,estetica_transportes,recordatorios}/` + `config_ui.json`

**Reportes y facturas visibles** (iguales en dev y prod):

/Documents/
├── Contabilidad 2025/
│ └── Contabilidad enero/
│ ├── Ingreso/
│ │ ├── Facturas Central/
│ │ └── Deposito/
│ └── Egreso/
│ ├── Baalak/
│ │ ├── PUE/
│ │ │ ├── Efectivo/
│ │ │ ├── TC/
│ │ │ ├── TD/
│ │ │ ├── Transferencia/
│ │ │ └── PPD/
│ │ └── PPD/
│ │ └── PPD/
│ ├── Animalia/
│ ├── PDFs/
│ └── Deposito_Egreso/
├── Contabilidad 2026/
│ └── (misma estructura)
├── Reportes Recordatorios/
└── Vet Suite/
└── (datos de la app en prod)

### Migraciones implementadas (v2.1.1)

- `recordatorios/sucursales.json` → `config_ui.json#veterinaria`
  - Se ejecuta al importar `config/veterinaria.py` por primera vez.
  - El archivo viejo se renombra a `.json.bak`.
- `config/temas.py#TEMA` (constante global) → `obtener_tema()` (función).
  - Se mantiene `__getattr__` para retrocompatibilidad.
- `config/ajustes.py` → **ELIMINADO**. Todos los imports migrados a
  `config/config_ingresos.py`.
- Cachés de Recordatorios: formato lista → `{sucursal, clientes}`.
  - Migración automática en `AppRecordatorios._normalizar_cache`.
- `dialogos/sucursal_editor.py` → **ELIMINADO**. El único editor de
  sucursales es Config General → tab Veterinaria.

### Migraciones implementadas (v2.1.2)

- `sat/guardar_egresos.py` ahora usa `core.rutas_egresos.ruta_registros_egresos`
  (única fuente de verdad). Antes calculaba su propia carpeta.
- `registros_egresos_YYYY.json` movido de la raíz a `egresos/`.
- `catalogo_qvet.json` movido de la raíz a `ingresos/`.
- `Reportes Recordatorios` movido de `~/Documents/Vet Suite/` a `~/Documents/`.

---

## Archivos clave

### Compartido / infraestructura
| Archivo | Propósito |
|---------|-----------|
| `main.py` | Entry point |
| `app/principal.py` | Pantalla de inicio (fuerza escritura inicial de `config_ui.json`) |
| `core/config_ui.py` | Única API de acceso a `config_ui.json` |
| `core/rutas.py` | Rutas de Ingresos + `CONFIG_UI_FILE` re-exportado |
| `core/rutas_egresos.py` | Rutas de Egresos (fuente de verdad de rutas del módulo) |
| `core/rutas_estetica.py` | Rutas de Estética |
| `core/rutas_recordatorios.py` | Rutas de Recordatorios + `_cargar_json` / `_guardar_json` |
| `core/sat_historial.py` | Historial completo de descargas SAT (snapshots) |
| `ui/utils.py` | `configurar_ventana()` |
| `ui/widgets.py` | Widgets custom |
| `config/temas.py` | Tema visual (`obtener_tema`, `guardar_tema`, colores) |
| `config/veterinaria.py` | Sucursales y datos del negocio (fuente de verdad) |
| `config/campos.py` | Definiciones de campos (MESES_ES, etc.) |
| `config/config_ingresos.py` | Config de Gmail (ex `ajustes.py`) |
| `config/config_egresos.py` | Config del módulo de Egresos |
| `dialogos/config_general.py` | Config General (Apariencia + Veterinaria) |
| `dialogos/temas.py` | Selector de tema |
| `dialogos/manual.py` | Visor del manual |
| `dialogos/gmail_config.py` | Config de Gmail |
| `scripts/probar_egresos.py` | CLI de pruebas (reprocesar XMLs, snapshots, FIEL) |

### Ingresos
| Archivo | Propósito |
|---------|-----------|
| `modulos/ingresos.py` | Módulo Ingresos. Importación de catálogo QVET desde Excel |
| `modulos/lector_facturas.py` | Parser PDF (productos) + XML (cabecera). Detecta IVA/IEPS/exento por tasa. |
| `modulos/correo_facturas.py` | Descarga de Gmail |
| `dialogos/adjuntos.py` | Ver adjuntos |
| `dialogos/sincronizar.py` | Sincronización Gmail |
| `dialogos/registrar_productos.py` | Ventana unificada de registro (nuevos + reclasificaciones) con badge visual. |
| `dialogos/reclasificador.py` | Reclasificador masivo |
| `core/persistencia.py` | Carga/guarda JSONs |
| `core/correo_utils.py` | Utilidades de correo |
| `excel/generador.py` | Orquestación de Excel (crear/anexar) |
| `excel/escritor.py` | Escritura de filas/encabezados/totales |
| `excel/constantes.py` | Columnas, fórmulas, colores |
| `excel/estilos.py` | Estilos openpyxl |

### Egresos
| Archivo | Propósito |
|---------|-----------|
| `modulos/egresos.py` | Módulo Egresos |
| `sat/descarga.py` | Descarga SAT (cfdiclient) + `probar_fiel()` + historial |
| `sat/conversion.py` | Conversión FIEL (NO TOCAR) |
| `sat/procesar_completo.py` | Procesa XMLs y orquesta (NO genera Excel) |
| `sat/mover_egresos.py` | Mueve y renombra XMLs por fecha real de factura |
| `sat/guardar_egresos.py` | Guarda DB de egresos (usa `core.rutas_egresos`) |
| `dialogos/descargar_sat.py` | Diálogo de descarga + botón "Probar FIEL" |
| `dialogos/egresos_config.py` | Config del SAT |
| `dialogos/egresos_editar.py` | Edita registro + adjuntos |
| `dialogos/clasificar_sucursal.py` | Clasifica proveedor → sucursal (usa `config.veterinaria`) |
| `dialogos/reportes_egresos.py` | Reportes |
| `dialogos/espera_sat.py` | Ventana de espera del SAT |
| `core/persistencia_egresos.py` | Carga/guarda JSONs |
| `excel/egresos.py` | Genera Excel PUE/PPD |

### Estética y Transportes
| Archivo | Propósito |
|---------|-----------|
| `modulos/estetica_transportes.py` | Módulo completo |
| `dialogos/cliente_detalle.py` | Detalle del cliente (4 tabs) |
| `dialogos/mascota_editar.py` | Alta/edición de mascota |
| `dialogos/catalogo_editor.py` | Ver/eliminar servicios y tarifas |
| `dialogos/duplicados_basura.py` | Duplicados + basura |
| `core/geocoding.py` | Geocodificación con Nominatim |

### Recordatorios
| Archivo | Propósito |
|---------|-----------|
| `modulos/recordatorios.py` | Ventana principal |
| `core/recordatorios/sucursales.py` | Adaptador → `config.veterinaria` |
| `core/recordatorios/formatear.py` | Formateo fechas/teléfonos/strings |
| `core/recordatorios/servicios.py` | Diccionario + procesarServicio |
| `core/recordatorios/plantillas.py` | Encabezados de citas/vacunas |
| `core/recordatorios/procesar_excel.py` | Importación + agrupación + mensajes |
| `core/recordatorios/envio.py` | WhatsApp (wa.me) + portapapeles |
| `core/recordatorios/historial.py` | Historial de envíos |

### Autenticación, sesión y perfiles
| Archivo | Propósito |
|---------|-----------|
| `core/auth.py` | Hash/verificación de contraseñas (PBKDF2-SHA256) + generación de password temporal legible |
| `core/sesion.py` | Estado en memoria de la sesión activa. NO se persiste |
| `core/usuarios.py` | CRUD de `usuarios.json` + reglas de "no quedar sin admins" |
| `shared/perfiles.py` | Perfiles: semilla + validación + CRUD. Fuente de verdad en `config_ui.json#perfiles` |
| `dialogos/login.py` | Login modal + bootstrap de primer arranque |
| `dialogos/usuario_editar.py` | Alta/edición de usuarios (admin) |
| `dialogos/perfil_editar.py` | Alta/edición de perfiles (admin) |
| `dialogos/sucursal_detalle.py` | Alta/edición de sucursales (extraído de config_general) |
| `scripts/probar_auth.py` | Pruebas de auth, sesión, perfiles y módulos |

---

## Reglas importantes

1. **NO tocar `sat/conversion.py`** — usa openssl 1.1.1
2.  **NO tocar el password de `Fiel()`** — se pasa vacío porque `preparar_fiel()` ya desencripta.
3. **Solo UNA solicitud SAT a la vez** — el SAT rechaza simultáneas
4. **Los JSON de datos NO van a git** (están en .gitignore)
5. **Los archivos se nombran `<serie>-<folio>.xml`** (sin número de línea)
6. **La numeración de línea se calcula al vuelo** en tabla y Excel
7. **Dev y prod usan la MISMA estructura de carpetas** — solo cambia la base
8. **`config_ui.json` es COMPARTIDO por los 4 módulos** — acceso único vía `core/config_ui.py`
9. **Las sucursales SOLO se editan desde Config General → tab 🏥 Veterinaria**
10. **`nombre_corto` de sucursal es el identificador estable** entre módulos
11. **Los reportes visibles van SIEMPRE a `~/Documents/Contabilidad AAAA/`** (excepto Recordatorios que va a `~/Documents/Reportes Recordatorios/`)
12. **Los mensajes de Recordatorios se cachean con la sucursal activa** (`{"sucursal": id, "clientes": [...]}`). Al abrir, si la sucursal cambió, se regeneran los NO enviados.
13. **El PDF es la FUENTE DE PRODUCTOS de Ingresos.** El XML solo
  aporta cabecera. Motivo: el XML de Baalak agrupa productos por
  remisión; el PDF los separa siempre.
14. **Cada remisión se agrupa entre paréntesis en la fórmula del Excel**
  si tiene 2+ productos. Con 1 producto no se ponen paréntesis.
  Con 2+ remisiones, se suman los grupos: `(500+200)+(500+200)`.
15. **El importe del PDF ya viene con descuento aplicado.** Se guarda
  tal cual y la fórmula lleva el divisor (`/1.16`, `/1.06`, `/1.07`).
  La celda contigua multiplica por la tasa.
16. **El tipo de impuesto se infiere de la tasa del PDF**: 16% → IVA,
  6% → IEPS 6, 7% → IEPS 7, 0% → sin impuesto.
17. **El catálogo QVET se actualiza con merge no destructivo.** Los
  productos que ya existen en el catálogo NO se sobreescriben; solo
  se agregan los nuevos.
18. **La ventana de registro de productos es única** para nuevos y
  reclasificaciones. Se distinguen con badge visual (🆕 / 🏷️).
19. **El Excel de Egresos se ordena por fecha + folio** antes de escribirse.
20. **Catalogo_qvet.json** NO va en el bundle. El usuario lo importa desde la UI (botón "📥 Importar catálogo QVET" en Ingresos visible solo si falta). Vive en ingresos/catalogo_qvet.json.
21. La ventana principal usa sidebar lateral estilo QVET: categorías
  colapsables con módulos indentados debajo. Sin flechas ni iconos
  en las categorías (solo texto). El módulo activo se resalta con
  fondo amarillo (#f0a500) y texto negro.
22. Los módulos que se quieren embeber exponen PanelX(ttk.Frame) y se
  declaran con `panel=` en shared/registro_modulos.py. Los que no,
  siguen abriendo como Toplevel con `factory=`.
23. La pantalla de bienvenida del área central NO muestra tarjetas de
  módulos. Solo el saludo. La navegación vive en el sidebar.
24. El sidebar usa tk.Frame + tk.Label con colores propios (no ttk),
  para evitar que ttkbootstrap sobrescriba bg/fg.
25. Agregar un módulo nuevo = una entrada en shared/registro_modulos.py.
  No se toca app/principal.py.
26. Al abrir un módulo embebido, se destruye el panel anterior antes de
  crear el nuevo (evita paneles superpuestos).
27. El botón "Probar FIEL" vive en dialogos/egresos_config.py (junto a
  las credenciales), no en el diálogo de descarga. Prueba los valores
  actuales del formulario, no los guardados.
28. Los módulos se activan/desactivan desde Config General → tab 🧩 Módulos.
29. El estado de activación vive en `config_ui.json#modulos_activos`
  (`{id: bool}`). El campo `activo` del registro
  (`shared/registro_modulos.py`) es solo el DEFAULT para módulos nuevos.
30. El sidebar usa `modulos_por_categoria()`, que filtra por
  config Y por perfil de la sesión, y OMITE categorías sin módulos
  visibles. `modulos_visibles()` es la lista plana.
31. Al cerrar Config General, la ventana principal reconstruye el sidebar
  (`_reconstruir_sidebar`) y, si el módulo abierto quedó inactivo o ya
  no lo permite el perfil, cierra el embed (`_verificar_modulo_activo`).
32. Los perfiles se declaran/editan en `config_ui.json#perfiles`. Los
  defaults de `shared/perfiles.py` son la SEMILLA inicial (se copian
  si la clave no existe).
33. El perfil `admin` es **intocable**: siempre existe, siempre ve todo,
  siempre puede configurar. Si falta o está alterado en config, se
  regenera al vuelo desde `shared/perfiles.py`.
34. Las cuentas de usuario viven en `usuarios.json` (raíz de datos,
  junto a `config_ui.json`). NO va a git. Solo admin las edita desde
  Config General → 👥 Usuarios.
35. El perfil activo NO vive en `config_ui.json`. Vive en
  `core/sesion.py` (memoria). Se resuelve al hacer login. Así el
  JSON de config no se manipula para escalar privilegios.
36. Sin sesión activa no se ve NINGÚN módulo. La app arranca en login.
37. Un módulo es visible si: (a) está activo en `config_ui.json` Y
  (b) el perfil de la sesión lo permite.
38. Solo el perfil `admin` tiene `puede_configurar=True`. Los tabs
  🎨 Apariencia, 🏥 Veterinaria, 🧩 Módulos, 🧑 Perfiles y 👥 Usuarios
  solo se muestran si `sesion.es_admin()`. El tab 🔒 Mi cuenta lo ve
  todo el mundo.
39. No se puede eliminar ni desactivar al último admin activo. La app
  lo rechaza con mensaje claro. Tampoco se puede eliminar la propia
  cuenta desde la sesión activa.
40. Las contraseñas se hashean con **PBKDF2-SHA256, 600k iteraciones,
  salt 16 bytes por usuario**. Implementación en `core/auth.py`. NUNCA
  se guarda en claro. NUNCA se compara con `==` (usar
  `hmac.compare_digest`).
41. Primer arranque: si no hay `usuarios.json`, se crea un admin con
  contraseña aleatoria legible (12+ chars) y se muestra UNA VEZ en
  pantalla con checkbox de confirmación. Si el usuario cancela, el
  admin se elimina y se fuerza bootstrap limpio en el siguiente
  arranque.
42. Un perfil NO se puede eliminar si hay usuarios asignados a él. La
  UI lo rechaza y muestra la lista de usuarios. No hay reasignación
  automática.
43. El `id` de un perfil es estable (`snake_case`, 3–32 chars). Solo se
  puede editar su nombre visible, descripción y módulos. El id no se
  cambia ni al editar.
44. Un módulo nuevo NO se añade solo a los perfiles con lista explícita.
  Hay que marcarlo en cada perfil que deba verlo (`"*"` es la
  excepción: admin ve todo automáticamente).
45. Cambiar de perfil/sesión NO es autenticación completa: es solo un
  filtro de UI basado en login. La contraseña es la única barrera.
  No hay 2FA, expiración de sesión, ni bloqueo por intentos.
46. Los diálogos de detalle de sucursal viven en
  `dialogos/sucursal_detalle.py`, no en `dialogos/config_general.py`.

---
## Módulo Ingresos — procesamiento de facturas

### Fuente de datos: PDF + XML
- **El PDF es la FUENTE DE PRODUCTOS.** El XML solo aporta cabecera
  (RFC, nombre, folio, fecha, total, folio fiscal).
- **Motivo**: el XML de Baalak a veces agrupa productos de una misma
  remisión en un solo concepto (`Descripcion="Venta"` con importe
  total), a veces los separa. El PDF **siempre** los separa.
- **Regla**: si falta XML o PDF → `ValueError` y no se procesa.
- El **total del XML NUNCA se pisa con el del PDF**.

### Estructura del PDF de Baalak
- Encabezado: `Descripción del producto Cantidad ud. medida P.V.P Dto. Impuesto Importe`
- Bloque por remisión: `No. Remisión: NNNNNN Fecha de remisión: DD/MM/YYYY H:MM a.m./p.m.`
- Cada producto en **una sola línea**:
<nombre> <cantidad> no aplica <PVP> <Dto> <Impuesto> <Importe>
- Última línea del bloque: **total de la remisión** (solo un número).
- **Columna Impuesto — variantes**:
- `16,00% 0,` → IVA 16%
- `16,00%15` → IVA 16% con descuento (el `15` es el % repetido)
- `6,00% 0,` → IEPS 6%
- `7,00% 0,` → IEPS 7%
- `0,` → sin impuesto
- `5,` → sin impuesto pero con descuento

### Regex del producto
^(?P<nombre>.+?)\s+
(?P<cantidad>\d+[,.]\d+)\s+
(?P<unidad>[^\d]+?)\s+
(?P<pvp>[\d.,]+)\s+
(?P<dto>[\d.,]+)\s+
(?P<impuesto>(?:\d+[,.]\d+\s%\s\d,?)|(?:\d+,))\s+
(?P<importe>[\d.,]+)\s$

El ancla es la **cantidad** seguida de la unidad. Esto permite nombres
que terminan en número (`TRATAMIENTO VETERINARIO 50`).

### Clasificación por categoría
- Catálogo QVET (`ingresos/catalogo_qvet.json`) + excepciones manuales
  (`ingresos/categorias_manuales.json`).
- **Categorías válidas:** `U`, `ACCESORIOS`, `MEDICAMENTOS`, `HIGIENE`,
  `ESTETICA`, `TRANSPORTE`, `PENSION`, `VACUNA`, `CLINICA`.
- Categoría no encontrada → `U` + aviso de reclasificación.
- Producto con IVA/IEPS en categoría `SIN_IVA` (VACUNA, CLINICA) → `U` + aviso.

### Tipo de impuesto
Se infiere de la tasa del PDF:
- 16.0% → `iva`
- 6.0% → `ieps_6`
- 7.0% → `ieps_7`
- 0.0% → `sin_imp`

### Separación por tipo fiscal

| Categoría | Columnas del Excel | Contenido |
|---|---|---|
| U, ACCESORIOS, ESTETICA, TRANSPORTE, PENSION | IMPORTE + IVA (16%) | Base sin IVA + fórmula `=base*0.16` |
| VACUNA, CLINICA | IMPORTE | Base tal cual (sin IVA) |
| MEDICAMENTOS | IMPORTE (sin IVA) + SIN IVA + IVA (16%) | Exentos / base gravados / IVA de gravados |
| HIGIENE | IMPORTE (sin IVA) + SIN IVA + IVA (16%) + SIN IEPS 6% + IEPS (6%) + SIN IEPS 7% + IEPS (7%) | Igual pero con 3 impuestos |

### Fórmulas en el Excel
Cada columna construye una fórmula que refleja el desglose por remisión:
- **1 producto en la remisión** → `114`
- **2+ productos en la misma remisión** → `(114+100)`
- **Varias remisiones** → `(114+100)+(200)+(58)`
- **Con divisor (IVA/IEPS):** `=((114+100)+(200)+(58))/1.16`
- **Sin divisor:** `=(50+30)+(80)`

**Divisores:** IVA 16% → `/1.16`, IEPS 6% → `/1.06`, IEPS 7% → `/1.07`,
sin impuesto → sin división.

### Valores guardados en el registro
- `datos_completos["X_importe"]` → número plano (base sin IVA).
- `datos_completos["X_iva"]` → número plano (para validación).
- `datos_completos["X_importe__expr"]` → string con la fórmula sin el `=`.

En el Excel, la columna base usa `={X_importe__expr}`. La columna IVA
usa siempre `=X_base{r}*0.16` (fórmula viva, NO expresión).

### Validaciones
- **Ajuste de centavos**: si `suma_bases + suma_impuestos` difiere del
  total XML por ±$0.01, se ajusta a la base más grande.
- **Deduplicación**: productos con mismo nombre + cantidad + remisión →
  se omite el segundo (con log).
- **Validación por remisión**: suma de importes de productos vs total
  de la remisión. Si difieren > $0.02, se registra en
  `datos["remisiones_con_problema"]`.
- **Check rojo en Excel**: `Total Remisiones` vs `Total Factura`.

### Sincronización de filtros al leer factura
- `_leer_factura` **sincroniza los filtros del UI** (año/mes/centro)
  con los del registro guardado.
- `_guardar_silencioso` **siempre actualiza** `self.registros` y
  `self._anio_cargado`, incluso cuando la factura es de otro año.
- `_leer_factura` **busca el PDF automáticamente** con el mismo nombre
  que el XML. Si no lo encuentra, busca cualquier PDF en la misma
  carpeta. Si hay varios, pregunta.

### Catálogo QVET desde Excel
- **Botón `📥 Importar catálogo QVET`** → `🔄 Actualizar catálogo QVET`
  cuando ya existe el catálogo.
- Acepta `.xlsx`, `.xls`, `.json`.
- **Detección de encabezados por contenido** (no por nombre de archivo):
  busca `DESCRIPCION` + (`SECCION` o `FAMILIA`).
- **Mapeo QVET → categorías del catálogo**: ver `_mapear_categoria_qvet`
  en `modulos/ingresos.py`.
- **Merge no destructivo**: solo agrega productos que NO existan.
- **Informe** con: productos en archivo, ya existentes, nuevos
  agregados, descartadas, total, ubicación.
- **Informe aparte de duplicados**: si hay nombres repetidos, los lista
  con sus códigos internos para corregirlos en QVET.
- **Filas descartadas**: `DESCRIPCION` vacía o que empieza con `*`.

### Ventana de registro de productos
- **Una sola ventana** para dos tipos de pendientes:
  - 🆕 **Productos nuevos** (no catalogados).
  - 🏷️ **Reclasificaciones** (VACUNA/CLINICA con IVA).
- **Badge visual** al inicio de cada fila.
- Subtítulo: `🆕 N nuevo(s) · 🏷️ M para reclasificar`.
- **Scroll con rueda del mouse** funcionando desde el primer movimiento.
- **Scrollregion adaptativo**: se deshabilita si el contenido cabe.

---

## Módulo Egresos

### Propósito
- Descargar CFDI recibidos del SAT
- Procesar XMLs (parsear, clasificar por sucursal, separar PUE/PPD)
- Mover XMLs a carpetas por sucursal/método/forma de pago
- Generar Excel PUE/PPD

### Datos en `/egresos/`
- `config_egresos.json` — RFC, FIEL, último periodo, flag de historial
- `registros_egresos_YYYY.json` — DB anual de registros
- `solicitud_sat_activa.json` — solicitud pendiente (temporal)
- `proveedores_tc.json`, `proveedores_sucursal.json`, `observaciones_egresos.json`
- `_sat_historial/` — snapshots de descargas SAT (no va a git)

### Flujo de descarga y procesamiento

1. **Descargar del SAT** (botón): solicita, espera, descarga, procesa y mueve XMLs.
   **NO genera Excel.**
2. **Revisar** en la tabla: editar sucursal, método o forma de pago. La app mueve el XML
   y actualiza la DB (`mover_un_registro`).
3. **Generar Excel** (botón): genera el Excel del mes/sucursal filtrado,
   **ordenado por fecha + folio**.

### Estructura de carpetas (real)

/Documents/Contabilidad AAAA/Contabilidad <mes>/Egreso/
├── <Sucursal>/ # Baalak | Animalia
│ ├── PUE/
│ │ ├── Efectivo/
│ │ ├── TC/
│ │ ├── TD/
│ │ ├── Transferencia/
│ │ └── PPD/ # (cuando metodo=PPD)
│ └── PPD/
│ └── PPD/
└── Deposito_Egreso/ # Excel generados


**La carpeta refleja la fecha real de emisión de la factura**, no el mes de la solicitud.

### Historial del SAT (`core/sat_historial.py`)

Cada solicitud al SAT se guarda como un "snapshot" en
`egresos/_sat_historial/<timestamp>_<id_solicitud>/`:

- `meta.json` — metadatos de la solicitud
- `01_solicita.json` — respuesta de SolicitaDescarga
- `02_verifica_N.json` — cada verificación
- `03_descarga_N.zip` — el ZIP tal cual lo entrega el SAT
- `xmls/` — XMLs extraídos
- `_errores/` — errores guardados aparte

**Activar/desactivar:**
python3 scripts/probar_egresos.py --historial on|off|status

**Override por entorno:**
export VET_SUITE_HISTORIAL=1

**Reprocesar / listar / errores:**
python3 scripts/probar_egresos.py --desde-snapshot <id>
python3 scripts/probar_egresos.py --listar-snapshots
python3 scripts/probar_egresos.py --reproducir-error <archivo>


### Probar FIEL sin gastar solicitud

- `sat/descarga.py::probar_fiel(cer, key, pwd)` → valida credenciales con `Autenticacion`.
- Botón **"🔑 Probar FIEL"** en `dialogos/descargar_sat.py`.
- **No gasta solicitud**: el SAT no cuenta `Autenticacion` como solicitud de descarga.

### Reglas
- **Los XMLs se mueven por fecha real de emisión de cada factura.**
- **`procesar_todo` NO genera Excel.** El usuario decide cuándo.
- **La numeración de línea se calcula al vuelo.**
- **Editar un registro mueve el XML** (`mover_un_registro`).

---

## Módulo Estética y Transportes

### Propósito
- Buscar clientes por nombre, población, dirección o mascota
- Ver/editar datos de transporte (distancia, tiempo, tarifa, notas)
- Ver/editar datos de estética (mascotas: raza, carácter, precauciones, servicio)

### Datos en `/estetica_transportes/`
- `clientes_maestro.json` — importado del Excel
- `mascotas.json` — `{cliente: [{nombre, raza, carácter, precauciones, ...}]}`
- `servicios_estetica.json` — catálogo de servicios
- `tarifas_transporte.json` — catálogo de tarifas
- `transportes_cliente.json` — datos de transporte por cliente
- `geocoding_cache.json` — caché de geocodificación

### Reglas
- Importación con detección por contenido + preview + merge
- Búsqueda sin acentos ni mayúsculas
- Notas separadas: cliente, transporte, estética
- ⚠️ en la tabla si hay notas en cualquier pestaña
- Cálculo de ruta con Haversine × 1.3 y velocidad 25 km/h
- Origen de rutas = sucursal activa (`config.veterinaria.sucursal_activa()`)

---

## Módulo Recordatorios

### Propósito
- Importar Excel de agenda y vacunas (exportados de QVET)
- Agrupar clientes por teléfono
- Generar mensajes con formato profesional
- Enviar por WhatsApp (wa.me + portapapeles)
- Historial de envíos + informes

### Flujo
1. Importar Excel (auto-detecta tipo por encabezados)
2. Clientes agrupados en 2 tabs: Citas / Vacunas
3. Seleccionar cliente → ver mensaje
4. "Enviar por WhatsApp" → copia al portapapeles + abre WhatsApp Desktop
5. Pegar (Cmd+V) + enviar
6. Confirmar en la app → se marca como enviado

### Formato de Excel

**Citas:** `FECHA | INICIO | TIPO VISITA | PROPIETARIO | MASCOTA | TELÉFONO | ASUNTO | AGENDA | ESTADO`

**Vacunas:** `CLIENTE | TELÉFONO 1 | MASCOTA | TIPO DE RECORDATORIO | VACUNA | PRÓXIMA FECHA`

### Datos en `/recordatorios/`
- `agenda_importada.json` — `{"sucursal": "BAALAK_CENTRAL", "clientes": [...]}`
- `vacunas_importada.json` — `{"sucursal": "BAALAK_CENTRAL", "clientes": [...]}`
- `historial_envios.json` — envíos por fecha
- `plantillas.json` — (futuro)

### Reglas
- Detección de tipo por columnas (no por nombre de archivo)
- Los emojis se preservan al copiar (van al portapapeles)
- Los emojis NO se muestran en Tk (se reemplazan por texto)
- **Los mensajes se regeneran al cambiar la sucursal activa** (solo clientes no enviados)
- **Al recibir foco, con debounce de 200 ms, verifica si la sucursal cambió**
- **Al abrir, si la sucursal guardada ≠ sucursal activa, regenera**
- La sucursal activa se lee SIEMPRE de `config.veterinaria`
- **NO hay botón de sucursales dentro del módulo** (solo en Config General)

### Reportes
- Van SIEMPRE a `~/Documents/Reportes Recordatorios/`.

---

## Empaquetado

- Push de tag `v*` → GitHub Actions compila para Windows y macOS
- `requirements.txt` debe tener cada dependencia en línea separada
- `--collect-all cfdiclient` y `--collect-all lxml` en build.yml
- `--add-data "MANUAL.md:."` para el manual integrado
- `config_ui.json` NO va en el bundle (se genera en runtime)
- `catalogo_qvet.json` NO va en el bundle (vive en `ingresos/`)
- `MANUAL.md` sí va en el bundle (se busca en `sys._MEIPASS`)

---

## Estado actual

- ✅ Autenticación con login obligatorio (PBKDF2, 600k iteraciones)
- ✅ Sesión en memoria, sin persistencia del perfil
- ✅ Perfiles editables desde Config General (admin intocable)
- ✅ Usuarios editables desde Config General
- ✅ Módulos activables/desactivables desde Config
- ✅ Sidebar filtra por activo ∧ permitido por perfil
- ✅ Tab "Mi cuenta" para cambiar la propia contraseña
- ✅ `scripts/probar_auth.py` con 86 checks verdes
- ✅ Ingresos funcional (con fórmulas por remisión)
- ✅ Egresos: descarga, procesa, mueve, Excel
- ✅ XMLs de Egresos se archivan por fecha real de factura
- ✅ Auto-clasificación de proveedores (usa `config.veterinaria`)
- ✅ Manual integrado
- ✅ Empaquetado automático
- ✅ Estética y Transportes completo
- ✅ Recordatorios completo (con regeneración por sucursal)
- ✅ `config_ui.json` unificado (tema + veterinaria)
- ✅ Migración automática de sucursales viejas
- ✅ Editor único de sucursales (Config General → Veterinaria)
- ✅ Shim `config/ajustes.py` eliminado
- ✅ `dialogos/sucursal_editor.py` eliminado
- ✅ Historial del SAT (`core/sat_historial.py`)
- ✅ CLI de pruebas (`scripts/probar_egresos.py`)
- ✅ Botón "Probar FIEL"
- ✅ `catalogo_qvet.json` en `ingresos/`
- ✅ `Reportes Recordatorios` en `~/Documents/`
- ⏳ Pendiente: pruebas con SAT real y cliente final
- ✅ Activar/desactivar módulos desde Config General

---

## Historial de versiones

### v3.1.0 — Descarga del SAT con fechas libres
- `dialogos/descargar_sat.py`: el diálogo de descarga ahora acepta
  un rango de fechas libre (desde/hasta) en lugar de solo mes/año.
  Usa `ttkbootstrap.DateEntry`. Validaciones: rango ≤ 365 días,
  inicio ≤ fin, no fechas futuras. Atajos "Mes actual" y "Mes anterior".
- Si el rango cruza de mes, se avisa al usuario y se procesa con el
  mes del primer día (limitación conocida de `procesar_todo`).
- `solicitud_sat_activa.json` ahora guarda `fecha_inicio` y `fecha_fin`
  además de `anio`/`mes_idx` (compatibilidad con `verificar_solicitud_pendiente`).

### v2.5.0 — Descarga del SAT robusta + descartados procesables

- **`dialogos/descargar_sat.py`**:
  - No re-solicita si ya hay una solicitud vigente del mismo período
    (estados 1/2 → avisa "en proceso"; estado 3 → deriva a descarga;
    estados 4/5 → permite re-solicitar).
  - Persiste `estado_solicitud`, `codigo_estado_solicitud`, `numero_cfdis`,
    `paquetes` y `ultima_verificacion` en `solicitud_sat_activa.json`
    después de cada verificación.
  - Al crear la solicitud, guarda `estado_solicitud: "1"` desde el inicio.
  - Traduce `5002` y `5005` del SAT a mensajes claros en la UI.
- **`modulos/egresos.py`**:
  - `_actualizar_boton_sat()` ya no borra la solicitud a las 24 h.
    Solo limpia cuando el SAT la declara muerta (estados 4/5).
- **`sat/descarga.py`**:
  - `carpeta_destino` de `descargar_paquetes()` pasa de `/tmp/sat_descargas`
    a `<CARPETA_DATOS>/descargas/` (dev: `egresos/descargas/`,
    prod: `~/Documents/Vet Suite/egresos/descargas/`).
- **`sat/procesar_completo.py`**:
  - Nuevo: copia a `<CARPETA_DATOS>/descartados/` cualquier XML que no
    se haya podido mover. Añade `descartados` y `carpeta_descartados`
    al resumen.
- **`dialogos/descargar_sat.py`** (mensaje final):
  - El `messagebox` de "Descarga completa" menciona cuántos XMLs se
    descartaron y dónde están.
- **`scripts/probar_egresos.py`**:
  - Docstring actualizado a la nueva ruta de descargas.
- **`scripts/procesar_descartados.py`** (NUEVO):
  - CLI que inspecciona y procesa los XMLs de `egresos/descartados/`.
  - `--listar`: clasifica cada XML en VÁLIDO / DUPLICADO / INVÁLIDO sin tocar nada.
  - `--procesar-uno <archivo>`: interactivo, pide método/forma, inserta en
    el JSON del año correcto (por fecha real de factura) y mueve el XML
    a su carpeta definitiva.
  - `--procesar-todos --auto`: procesa todos los válidos sin preguntar.
  - Reutiliza `mover_un_registro` de `sat/mover_egresos.py`.

### v2.5.0 — Descarga del SAT robusta + descartados visibles + rutas persistentes

- **`dialogos/descargar_sat.py`**:
  - Antes de solicitar, revisa `solicitud_sat_activa.json` del mismo período.
    Si estado es 1/2 → no molesta al SAT, avisa "en proceso".
    Si estado es 3 → deriva directo a descarga.
    Si estado es 4/5 → limpia y permite solicitar de nuevo.
  - Persiste el estado devuelto por `VerificaSolicitudDescarga`
    (`estado_solicitud`, `codigo_estado_solicitud`, `numero_cfdis`,
    `paquetes`, `ultima_verificacion`) en cada verificación.
  - Al crear la solicitud, guarda `estado_solicitud: "1"` desde el inicio.
  - Traduce `5002` y `5005` del SAT a mensajes claros en la UI.
- **`modulos/egresos.py`**:
  - `_actualizar_boton_sat()` ya no borra la solicitud a las 24 h.
    Solo limpia cuando el estado del SAT es 4 o 5.
- **`sat/descarga.py`**:
  - `carpeta_destino` de `descargar_paquetes()` pasa de `/tmp/sat_descargas`
    a `<CARPETA_DATOS>/descargas/` (dev: `egresos/descargas/`,
    prod: `~/Documents/Vet Suite/egresos/descargas/`).
- **`sat/procesar_completo.py`**:
  - Nuevo: copia a `<CARPETA_DATOS>/descartados/` cualquier XML que no
    se haya podido mover. Añade `descartados` y `carpeta_descartados`
    al resumen.
- **`dialogos/descargar_sat.py`** (mensaje final):
  - El `messagebox` de "Descarga completa" menciona cuántos XMLs
    se descartaron y dónde están.
- **`scripts/probar_egresos.py`**:
  - Docstring actualizado a la nueva ruta de descargas.

### v2.3.0 — Lector de facturas v3 + catálogo QVET desde Excel
- **Reescrito `modulos/lector_facturas.py`**: el PDF es la fuente de
  productos (no el XML). El XML solo aporta cabecera.
- **Detección correcta de IVA / IEPS 6% / IEPS 7% / exento** por tasa.
- **Detección de descuentos del PDF** (columna Dto.).
- **Deduplicación correcta entre remisiones** (por remisión + nombre +
  cantidad).
- **Detección de productos no catalogados** (`no_catalogados`).
- **Validación por remisión**: suma de importes vs total de remisión.
- **`_leer_factura` busca el PDF automáticamente** por nombre.
- **Importación de catálogo QVET desde Excel** (merge no destructivo,
  detección por contenido, mapeo de categorías, informe de duplicados).
- **Botón `📥 Importar` ↔ `🔄 Actualizar`** según exista el catálogo.
- **Ventana de registro unificada** (nuevos + reclasificaciones) con
  badge visual.
- **Fix scroll** en ventana de registro (rueda + scrollregion
  adaptativo).
- **Fix `sincronizar.py`**: unpacking de 4 valores.

### v2.2.0 — Autenticación, perfiles y usuarios
- **Nuevo: sistema de autenticación completo.**
  - `core/auth.py` — hash PBKDF2-SHA256, 600k iteraciones, salt por usuario.
  - `core/sesion.py` — sesión activa en memoria. NO se persiste.
  - `core/usuarios.py` — CRUD de `usuarios.json` + reglas de admins.
  - `shared/perfiles.py` — perfiles como semilla + CRUD, admin blindado.
- **Nuevo: `dialogos/login.py`** — login modal + bootstrap de primer arranque.
- **Cambio mayor: la app arranca en login.** Sin sesión no hay módulos visibles.
- **Nuevo: `dialogos/usuario_editar.py`** — alta/edición de usuarios.
- **Nuevo: `dialogos/perfil_editar.py`** — alta/edición de perfiles.
- **Nuevo: `dialogos/sucursal_detalle.py`** — extraído de `config_general.py`.
- **Config General reescrito:** tabs filtrados por perfil. No-admin solo ve
  "Mi cuenta". Admin ve además Apariencia, Veterinaria, Módulos, Perfiles y Usuarios.
- **Sidebar rediseñado:** bloque de sesión arriba (nombre + perfil),
  footer con Configuración/Mi cuenta · Ayuda · Cerrar sesión.
- **Perfiles editables desde la UI.** Admin intocable. No se elimina un perfil
  con usuarios asignados. Módulos por perfil en `config_ui.json#perfiles`.
- **Módulos activables/desactivables** (ya en v2.1.8, consolidado aquí).
- **Fix: cerrar la ventana principal con Config abierto ya no muestra
  messagebox de error.**
- **Fix: login en macOS ya no queda bloqueado por `transient` sobre
  ventana withdrawn.**
- **Migración automática:** `config_ui.json#perfiles` se siembra con los
  defaults la primera vez que se lee.
- **`scripts/probar_auth.py`** — 86 checks de auth/sesión/perfiles/módulos.

### v2.1.8 — Activar/desactivar módulos desde Config
- **Nuevo: tab 🧩 Módulos** en Config General con checkboxes por módulo,
  agrupados por categoría. Guarda al instante.
- **`config_ui.modulos_activos()` / `modulo_esta_activo()` /
  `set_modulo_activo()`** — estado en `config_ui.json#modulos_activos`.
- **`shared.registro_modulos.modulos_visibles()`** reemplaza a
  `modulos_activos()` (eliminada). `modulos_por_categoria()` filtra por
  config y omite categorías vacías.
- **`app/principal.py`**: `_reconstruir_sidebar()` tras cerrar Config;
  `_verificar_modulo_activo()` cierra el embed si lo desactivaron;
  `_abrir_modulo()` ignora módulos inactivos (atajos viejos).
- **`abrir_dialogo_config_general()`** ahora devuelve el Toplevel para
  poder hacer `wait_window`.
- **`verificar_config.py`**: bloque [8] valida `modulos_activos`.

### v2.1.7 — Rediseño de ventana principal + embed completo
- **Nuevo: `shared/registro_modulos.py`** — registro declarativo de módulos.
  Agregar un módulo = una entrada en MODULOS, sin tocar app/principal.py.
- **Rediseño de `app/principal.py`** — sidebar lateral estilo QVET con
  categorías colapsables. Sin iconos en categorías, sin tarjetas de
  módulos en el área central.
- **Migrados a embed los 4 módulos:** Ingresos, Egresos, Estética y
  Recordatorios. Cada uno expone `PanelX(ttk.Frame)` y mantiene
  `AppX(ttk.Toplevel)` como wrapper legacy.
- **Fix: paneles acumulados** al cambiar de módulo sin dar "←".
- **Botón "🔑 Probar FIEL" movido** de `dialogos/descargar_sat.py` a
  `dialogos/egresos_config.py`.
- **Botón "Volver" del embed** ahora es solo la flecha `←`.
- **Contrato de embed:** `Modulo.panel` activa el embed. Los módulos sin
  `panel=` siguen abriendo como Toplevel.

### v2.1.6 — Migración de Egresos a embed
- Migrado a embed: Egresos.
  - AppEgresos → PanelEgresos(ttk.Frame).
  - Se mantiene AppEgresos(ttk.Toplevel) como wrapper legacy.
  - Registro: panel=_panel_egresos.
- Fix: _preguntar_accion_excel usa parent.winfo_toplevel() para
  transient, así funciona con Frame o Toplevel como parent.
- Movido: botón "🔑 Probar FIEL" de dialogos/descargar_sat.py a
  dialogos/egresos_config.py. Ahora vive donde se configuran las
  credenciales y prueba los valores actuales del formulario
  (aunque no estén guardados).
- _panel_ingresos ya está declarada en shared/registro_modulos.py
  pero comentada; se activa cuando se migre Ingresos.

### v2.1.5 — Migración de Recordatorios a embed
- Migrado a embed: Recordatorios.
  - AppRecordatorios → PanelRecordatorios(ttk.Frame).
  - Se mantiene AppRecordatorios(ttk.Toplevel) como wrapper legacy.
  - Registro: panel=_panel_recordatorios.
- Fix: al abrir un módulo embebido, se destruye el panel anterior
  antes de crear el nuevo (evita paneles superpuestos).
- Botón "Volver" del embed ahora es solo la flecha ←, sin texto
  ni contorno (bootstyle="link").

### v2.1.4 — Rediseño de ventana principal
- Nuevo: shared/registro_modulos.py — registro declarativo de módulos.
  Agregar un módulo = una entrada en MODULOS, sin tocar app/principal.py.
- Rediseño de app/principal.py — sidebar lateral con acordeón de
  categorías (estilo QVET), sin flechas ni iconos en categorías.
- Nuevo: contrato de embed. Módulos con PanelX(ttk.Frame) se declaran
  con `panel=` y se embeben en el área central. Los demás siguen como
  Toplevel.
- Migrado a embed: Estética y Transportes.
  - AppEsteticaTransportes → PanelEsteticaTransportes(ttk.Frame).
  - Se mantiene AppEsteticaTransportes(ttk.Toplevel) como wrapper legacy.
- Pantalla de bienvenida simplificada (sin tarjetas de módulos).
- Pendiente: migrar Ingresos, Egresos y Recordatorios a embed.

### v2.1.4 — Sidebar + Embed
- **Nuevo: `shared/registro_modulos.py`** — registro declarativo de módulos.
  Agregar un módulo = una entrada en `MODULOS`, sin tocar `app/principal.py`.
- **Rediseño de `app/principal.py`** — sidebar lateral + lista compacta
  de módulos agrupada por categoría (Operación / Clientes / Comunicación).
- **Nuevo: contrato de embed.** Los módulos exponen `Panel*(ttk.Frame)` y se
  embeben en el área central. Los que no, siguen abriendo como Toplevel.
- **Migrado a embed: Estética y Transportes.**
  - `AppEsteticaTransportes` → `PanelEsteticaTransportes(ttk.Frame)`.
  - Se mantiene `AppEsteticaTransportes(ttk.Toplevel)` como wrapper legacy.
  - Registro: `Modulo.panel` activa el embed.
- **Regla nueva:** un módulo migrado a embed debe exponer
  `PanelX(master, on_volver=None)` y no llamar `title/geometry/protocol`.
- **Pendiente:** migrar Ingresos, Egresos y Recordatorios a embed.

### v2.1.3
- **Nuevo: Anexar facturas al Excel de Egresos** sin perder anotaciones
  - `excel/egresos.py::anexar_facturas_al_excel()`
  - Diálogo de 3 opciones: Anexar / Reemplazar / Omitir
  - Detecta duplicados por UUID
  - Renumera columna # y recalcula TOTALES

### v2.1.2
- **Fix: XMLs de Egresos se archivan por fecha real de factura** (no mes de solicitud)
- **Refactor: `sat/guardar_egresos.py` usa `core.rutas_egresos`** (única fuente de verdad)
- **Migración: `registros_egresos_YYYY.json` movido a `egresos/`**
- **Migración: `catalogo_qvet.json` movido a `ingresos/`**
- **Migración: `Reportes Recordatorios` movido a `~/Documents/`**
- **Nuevo: `core/sat_historial.py`** — historial completo de descargas SAT
- **Nuevo: `scripts/probar_egresos.py`** — CLI de pruebas
- **Nuevo: `sat/descarga.py::probar_fiel`** — valida FIEL sin gastar solicitud
- **Nuevo: botón "🔑 Probar FIEL" en el diálogo de descarga**
- **Cambio: `procesar_todo` ya no genera Excel** (el usuario lo hace con el botón)
- **Fix: Excel de Egresos se ordena por fecha + folio**
- **Limpieza: `_ordenar_facturas` restaurada y usada en la generación de Excel**
- **Fix: `mover_y_renombrar_egresos` agrupa por `(anio_factura, mes_factura, sucursal, metodo, forma)`**
- **Nuevo: botón "📥 Importar catálogo QVET"** en Ingresos (solo si falta el catálogo)
- **Fix: catalogo_qvet.json** fuera del bundle (causaba fallo en CI)

### v2.1.1
- **Refactor de configuración compartida:**
  - `core/config_ui.py` como única API de `config_ui.json`
  - `config/temas.py` y `config/veterinaria.py` usan `config_ui`
  - Bug del `TEMA` global arreglado (`obtener_tema()`)
  - `config_ui.json` se autocrea al arrancar la app
- **Renombrado `config/ajustes.py` → `config/config_ingresos.py`:**
  - Shim eliminado, imports migrados
- **`dialogos/clasificar_sucursal.py`:** usa sucursales dinámicas
- **`dialogos/config_general.py`:** editor único de sucursales
- **`config/veterinaria.py`:** `nombre_corto` simplificado
- **`modulos/recordatorios.py`:** caché con sucursal, regeneración
- **`modulos/ingresos.py`:** `mapa_campos` (MEDICAMENTOS/HIGIENE separan exentos)
- **`modulos/lector_facturas.py`:** rechaza sin XML o PDF, no pisa total, fórmulas por remisión
- **`excel/escritor.py`:** `_calcular_total_remisiones` con claves correctas

### v2.1.0
- Módulo **Recordatorios** completo
- Fix crash `espera_sat.py` (bad window path name)
- Separación de `config_ui.json` (tema) e `ingresos/gmail_config.json` (correo)

### v2.0.0
- Renombrado a **Vet Suite**
- Nueva arquitectura de rutas de datos en dev y prod
- Módulo **Estética y Transportes** funcional

### v1.0.1
- Ingresos y Egresos funcionales
- Empaquetado automático con GitHub Actions

---

### Pendiente
- [ ] Probar con PDFs de otros proveedores (no solo Baalak).
- [ ] Tests del parser de PDF (casos: con/sin descuento, con/sin IEPS).
- [ ] Tests de `_leer_excel_qvet` con Excel de QVET real.
- [ ] Exportar informe de remisiones con discrepancia a un .txt.
- [ ] Rotación de snapshots SAT.
- [ ] Tests con pytest sobre snapshots reales (anonimizados).
- [ ] Tests de core/config_ui.py.
- [ ] Tests del pipeline de Ingresos.
- [ ] Refactor v3.0.0 por dominio funcional.
- [ ] Actualizar el manual.
- [ ] Ampliar `verificar_config.py` con bloque `[10]` para `usuarios.json`.
- [ ] Ampliar `scripts/probar_auth.py` con tests de integración de perfiles.
- [ ] Migración de usuarios huérfanos (perfil borrado tras asignar usuario).
- [ ] Log de auditoría de cambios de perfiles/usuarios.
- [ ] Sección de login y perfiles en el manual.