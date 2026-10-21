# Sesión de trabajo — 2026-10-20 (v2.5.0)

## Resumen
Se reforzó el flujo de descarga del SAT para que la app no vuelva a
solicitar un período cuando ya hay una solicitud vigente, se persistió
el estado del SAT en `solicitud_sat_activa.json`, y se movió la carpeta
de trabajo de `/tmp/sat_descargas` a `<CARPETA_DATOS>/descargas/`.
Además, los XMLs que no se pueden mover ahora se copian a
`<CARPETA_DATOS>/descartados/` y se reportan en el resumen final.
Se agregó `scripts/procesar_descartados.py` para recuperar, clasificar
y procesar manualmente los XMLs descartados.

# Sesión de trabajo — 2026-10-18 (v2.5.0)

## Resumen
Se corrigió el flujo de descarga del SAT para que no se vuelva a
solicitar un período cuando ya hay una solicitud vigente, se persistió
el estado del SAT en `solicitud_sat_activa.json` para que la UI sepa
qué botón mostrar, y se movió la carpeta de trabajo de `/tmp/sat_descargas`
a `<CARPETA_DATOS>/descargas/`. Además, los XMLs que no se pueden mover
ahora se copian a `<CARPETA_DATOS>/descartados/` y se reportan en el
resumen final.

# Sesión de trabajo — 2026-10-15 (v2.3.0)

## Resumen
Sistema completo de autenticación, perfiles y usuarios. La app arranca
en login. Sidebar y Config General se filtran por perfil. Módulos
activables/desactivables y perfiles editables desde la UI.

Además, en esta sesión se reescribió el **lector de facturas** para
usar el **PDF como fuente de productos** (el XML solo aporta cabecera).
Se agregó importación de catálogo QVET desde Excel. Se corrigieron 4
bugs del pipeline de Ingresos: descuentos, IEPS, deduplicación de
remisiones y detección de productos no catalogados.

## Qué se hizo

### 1. Autenticación (Fases 1–3)
- **`core/auth.py`** — PBKDF2-SHA256, 600k iteraciones, salt 16 bytes por
  usuario. `hashear_password()`, `verificar_password()` (comparación en
  tiempo constante), `generar_password_temporal()` (12+ chars legibles).
- **`core/sesion.py`** — sesión activa en memoria. NO se persiste. El
  perfil activo vive aquí, no en `config_ui.json`, para evitar escalada
  de privilegios editando el JSON.
- **`core/usuarios.py`** — CRUD de `usuarios.json` (raíz de datos).
  Reglas de negocio: no eliminar/desactivar al último admin activo.
- **`shared/perfiles.py`** — 5 perfiles iniciales (admin, contabilidad,
  almacen, cajero, medico). Admin blindado. Fuente de verdad en
  `config_ui.json#perfiles`, defaults aquí.
- **`dialogos/login.py`** — login modal + bootstrap de primer arranque.
  En macOS, sin `transient` ni `grab_set` sobre padre withdrawn.
- **`main.py`** — DPI awareness → crear AppPrincipal → withdraw →
  mostrar_login → si OK, deiconify + mainloop.

### 2. Sidebar con sesión (Fase 3)
- Bloque de sesión arriba: `👤 Ana (Administrador)`.
- Footer: `Configuración`/`Mi cuenta` (según perfil) · `Ayuda` ·
  `🚪 Cerrar sesión`.
- Cerrar sesión vuelve al login sin reiniciar el proceso.

### 3. Config General con tabs filtrados (Fases 4a–4c)
- Tab **🔒 Mi cuenta** (todos los perfiles) — cambiar la propia contraseña.
- Tabs admin: 🎨 Apariencia, 🏥 Veterinaria, 🧩 Módulos, 🧑 Perfiles,
  👥 Usuarios.
- CRUD de usuarios desde la UI. Contraseña editable en el diálogo de
  edición (vacío = no cambiar).
- Sucursales extraídas a `dialogos/sucursal_detalle.py`.

### 4. Perfiles editables (Sub-fases A y B)
- Perfiles movidos a `config_ui.json#perfiles`. Defaults como semilla.
- Admin blindado: no editable, no eliminable, siempre `modulos="*"`.
- CRUD de perfiles desde la UI. No se elimina un perfil con usuarios
  asignados (rechazo con lista de usuarios).
- Cambios en perfiles aplican al siguiente login del usuario afectado,
  no en caliente.

### 5. Importación de catálogo QVET desde Excel (NUEVO)
- **El botón "📥 Importar catálogo QVET"** se transforma en
  **"🔄 Actualizar catálogo QVET"** cuando ya existe el catálogo.
- Acepta `.xlsx`, `.xls` y `.json`.
- Detecta encabezados **por contenido**, no por nombre de archivo:
  busca `DESCRIPCION` + (`SECCION` o `FAMILIA`).
- **Mapeo QVET → categorías del catálogo** (`_mapear_categoria_qvet`):
  - `ALIMENTOS` → `PENSION`
  - `FARMACIA` / `MEDICAMENTOS` → `MEDICAMENTOS`
  - `HIGIENE` → `HIGIENE`
  - `MEDICINA PREVENTIVA` + `VACUNA` en subfamilia → `VACUNA`
  - `ESTETICA` (sección o familia) → `ESTETICA`
  - `RESIDENCIA` / `PENSION DIARIA` / `GUARDERIA` → `PENSION`
  - `TRANSPORTE` (sección o familia) → `TRANSPORTE`
  - Accesorios (ROPA, JUGUETES, CAMAS, etc.) → `ACCESORIOS`
  - `CLINICA` + quirúrgico/lab → `CLINICA`
  - Resto → `U`
- **Merge no destructivo**: solo agrega productos que NO existan. Los
  ya existentes se respetan (no se sobreescriben).
- **Informe** con: productos en archivo, ya existentes, **nuevos
  agregados**, filas descartadas, total en catálogo, ubicación.
- **Informe aparte de duplicados**: si el Excel trae nombres repetidos,
  los lista con sus códigos internos para corregirlos en QVET.
- **Filas descartadas**: `DESCRIPCION` vacía o que empieza con `*`,
  `**`, `***`, `Concepto_Migracion...`.

### 6. Lector de facturas reescrito (v3) — CAMBIO MAYOR (NUEVO)
- **El PDF es la fuente de productos.** El XML solo aporta cabecera
  (RFC, nombre, folio, fecha, total, folio fiscal).
- **Motivo**: el XML de Baalak a veces agrupa productos de una misma
  remisión en un solo concepto (`Descripcion="Venta"` con importe
  total), a veces los separa. El PDF **siempre** los separa.
- **Estructura del PDF de Baalak** (confirmada):
  - Encabezado: `Descripción del producto Cantidad ud. medida P.V.P Dto. Impuesto Importe`
  - Bloque por remisión: `No. Remisión: NNNNNN Fecha de remisión: DD/MM/YYYY H:MM a.m./p.m.`
  - Cada producto en **una sola línea**:
<nombre> <cantidad> no aplica <PVP> <Dto> <Impuesto> <Importe>
- Última línea del bloque: **total de la remisión** (solo un número).
- **Regex exacta del producto** (`_RE_PRODUCTO`):
^(?P<nombre>.+?)\s+
(?P<cantidad>\d+[,.]\d+)\s+
(?P<unidad>[^\d]+?)\s+
(?P<pvp>[\d.,]+)\s+
(?P<dto>[\d.,]+)\s+
(?P<impuesto>(?:\d+[,.]\d+\s%\s\d,?)|(?:\d+,))\s+
(?P<importe>[\d.,]+)\s$
El ancla es la **cantidad** (`\d+[,.]\d+`) seguida de la unidad. Esto
permite nombres que terminan en número, como
`TRATAMIENTO VETERINARIO 50`.
- **Columna Impuesto — variantes**:
- `16,00% 0,` → IVA 16%
- `16,00%15` → IVA 16% con descuento (el `15` es el % repetido)
- `6,00% 0,` → IEPS 6%
- `7,00% 0,` → IEPS 7%
- `0,` → sin impuesto
- `5,` → sin impuesto pero con descuento
- **Tipo de impuesto** se infiere de la tasa (`_clasificar_tasa_pdf`):
- 16.0 → `iva`
- 6.0 → `ieps_6`
- 7.0 → `ieps_7`
- 0.0 → `sin_imp`
- **Importe**: se guarda **tal cual viene del PDF** (ya con descuento
aplicado). La fórmula del Excel lleva el divisor correspondiente
(1.16, 1.06, 1.07) para que la celda contigua multiplique por la tasa.
- **Validación por remisión**: suma de importes de productos vs total
de remisión. Si difieren > $0.02, se registra en
`datos["remisiones_con_problema"]` y se imprime en consola.
- **Pagos**: se siguen extrayendo del PDF (con fallback a `FormaPago`
del XML si no se detectan).

### 7. Ventana unificada de registro de productos (NUEVO)
- **Una sola ventana** para los dos tipos de pendientes:
- 🆕 **Productos nuevos** (no catalogados, categoría `U`).
- 🏷️ **Reclasificaciones** (VACUNA/CLINICA con IVA mal categorizado).
- **Badge visual** al inicio de cada fila para distinguir el tipo.
- Subtítulo: `🆕 N producto(s) nuevo(s) · 🏷️ M para reclasificar`.
- **Scroll con rueda del mouse** funcionando desde el primer movimiento
(bind al `Toplevel`, `canvas`, `frame` y todos los hijos).
- **Scrollregion adaptativo**: si el contenido cabe en el viewport, el
scroll se deshabilita (no se puede "colar" el área vacía).
- Se llama **una sola vez** desde `sincronizar.py` y desde `ingresos.py`,
con la lista combinada.

### 8. Bugs resueltos

**De autenticación / config:**
- Login en macOS con `transient` sobre padre withdrawn → queda colgado.
- Bootstrap no bloqueante → doble ventana superpuesta.
- Cancelar bootstrap → admin huérfano con contraseña perdida.
- Cerrar ventana principal con Config abierto → messagebox de error.
- `_abrir_configuracion` faltante tras refactor.
- `_abrir_ayuda` duplicado.

**De Ingresos (esta sesión):**
- **No informaba productos nuevos**: `agrupar_por_categoria` no devolvía
la lista. Ahora devuelve `no_catalogados` y se muestra en ventana.
- **No leía descuentos del PDF**: la regex no contemplaba la columna
`Dto.`. Ahora la regex cubre los 4 casos (con/sin impuesto ×
con/sin descuento).
- **Deduplicaba mal entre remisiones**: el parser anterior usaba el XML
que agrupa productos. Ahora el PDF es la fuente y cada remisión
produce sus propios grupos.
- **Marcaba IEPS como IVA 16%**: infería por tasa del PDF asumiendo
IVA. Ahora distingue 16% / 6% / 7% / 0% correctamente.
- **Nombres sucios en reclasificación** (`APOQUEL 5.4 MG MAST
(BLISTER) 1,00 no aplica 500,00...`): la regex capturaba línea
completa. Ahora se ancla por cantidad + unidad.
- **Fechas como productos** (`03/10/2026 pagina 1`): filtro
insuficiente. Ahora la regex del producto exige la estructura
completa (cantidad + no aplica + PVP + Dto + Impuesto + Importe).
- **Fórmulas sin paréntesis por remisión**
(`=250+50+700+700+500` en vez de
`=250+50+(500+200)+(500+200)+500`): el XML agrupaba conceptos.
Ahora el PDF separa → agrupación correcta.
- **Sync fallaba** (`too many values to unpack (expected 3, got 4)`):
unpacking desactualizado en `sincronizar.py`.
- **Dos ventanas de reclasificación**: se unificaron en una con badge.
- **Scroll no funcionaba con rueda**: bind faltante en macOS.
- **Scroll con pocos productos "colaba" lo negro**: `scrollregion`
mal calculado.

## Estado actual
- ✅ Login obligatorio (PBKDF2-SHA256, 600k iteraciones).
- ✅ Sesión en memoria, sin persistencia del perfil.
- ✅ Sidebar filtrado por activo ∧ permitido por perfil.
- ✅ Perfiles editables desde Config General (admin intocable).
- ✅ Usuarios editables desde Config General.
- ✅ Módulos activables/desactivables desde Config.
- ✅ Tab "Mi cuenta" para cambiar la propia contraseña.
- ✅ `scripts/probar_auth.py` con 86 checks verdes.
- ✅ `python3 verificar_config.py` OK.
- ✅ **Importación de catálogo QVET desde Excel con merge no destructivo.**
- ✅ **Botón Importar ↔ Actualizar catálogo QVET según exista.**
- ✅ **Informe de duplicados del Excel con códigos internos.**
- ✅ **Lector de facturas v3: PDF como fuente de productos.**
- ✅ **Detección correcta de IVA / IEPS 6% / IEPS 7% / exento.**
- ✅ **Detección de descuentos del PDF.**
- ✅ **Detección de productos no catalogados.**
- ✅ **Ventana unificada de registro con badge visual.**
- ✅ **Scroll de la ventana de registro arreglado (rueda + región).**
- ⏳ Pendiente: pruebas con SAT real y cliente final.

## Cómo trabajar
- Configuración compartida → `core/config_ui.py`.
- Cuentas de usuario → `core/usuarios.py` + `usuarios.json`.
- Perfiles → `config_ui.json#perfiles` (semilla en `shared/perfiles.py`).
- Sesión activa → `core/sesion.py`.
- Sucursales → `config/veterinaria.py` (fuente de verdad).
- Registro de módulos → `shared/registro_modulos.py`.
- Lector de facturas → `modulos/lector_facturas.py` (**PDF = fuente
de productos, XML = solo cabecera**).
- Catálogo QVET → `ingresos/catalogo_qvet.json` (importable desde Excel).
- Antes de tocar: correr `python3 verificar_config.py` y
`python3 scripts/probar_auth.py`.
- Los JSON de datos NO van a git (`config_ui.json`, `usuarios.json`).

## Pendientes (deuda técnica)

### Testing
- [ ] Ampliar `verificar_config.py` con bloque `[10]` para `usuarios.json`.
- [ ] Ampliar `scripts/probar_auth.py` con tests de integración de perfiles.
- [ ] pytest sobre snapshots reales (anonimizados).
- [ ] Tests del pipeline de Ingresos (parser de PDF, dedup, agrupación).
- [ ] Tests de `_leer_excel_qvet` con Excel de QVET real.

### Autenticación
- [ ] Migración de usuarios huérfanos (perfil borrado tras asignar usuario).
- [ ] Log de auditoría de cambios de perfiles/usuarios.
- [ ] (Opcional) Bloqueo por intentos fallidos.
- [ ] (Opcional) Expiración de sesión.

### Módulos y arquitectura
- [ ] Refactor v3.0.0 por dominio funcional.
- [ ] Rotación de snapshots SAT.
- [ ] Anexar + reordenar Excel de Egresos con anotaciones.

### Ingresos
- [ ] Probar con PDFs de otros proveedores (no solo Baalak).
- [ ] Manejo de PDFs con formato ligeramente distinto (otros layouts).
- [ ] Validar el orden de las remisiones en la fórmula (¿importa?).
- [ ] Exportar informe de remisiones con discrepancia a un .txt.

### Documentación
- [ ] Sección de login y perfiles en `MANUAL.md`.
- [ ] Sección de importación de catálogo QVET en `MANUAL.md`.




# Sesión de trabajo — 2026-10-15 (v2.2.0)

## Resumen
Sistema completo de autenticación, perfiles y usuarios. La app arranca
en login. Sidebar y Config General se filtran por perfil. Módulos
activables/desactivables y perfiles editables desde la UI.

## Qué se hizo

### 1. Autenticación (Fases 1–3)
- **`core/auth.py`** — PBKDF2-SHA256, 600k iteraciones, salt 16 bytes por
  usuario. `hashear_password()`, `verificar_password()` (comparación en
  tiempo constante), `generar_password_temporal()` (12+ chars legibles).
- **`core/sesion.py`** — sesión activa en memoria. NO se persiste. El
  perfil activo vive aquí, no en `config_ui.json`, para evitar escalada
  de privilegios editando el JSON.
- **`core/usuarios.py`** — CRUD de `usuarios.json` (raíz de datos).
  Reglas de negocio: no eliminar/desactivar al último admin activo.
- **`shared/perfiles.py`** — 5 perfiles iniciales (admin, contabilidad,
  almacen, cajero, medico). Admin blindado. Fuente de verdad en
  `config_ui.json#perfiles`, defaults aquí.
- **`dialogos/login.py`** — login modal + bootstrap de primer arranque.
  En macOS, sin `transient` ni `grab_set` sobre padre withdrawn.
- **`main.py`** — DPI awareness → crear AppPrincipal → withdraw →
  mostrar_login → si OK, deiconify + mainloop.

### 2. Sidebar con sesión (Fase 3)
- Bloque de sesión arriba: `👤 Ana (Administrador)`.
- Footer: `Configuración`/`Mi cuenta` (según perfil) · `Ayuda` ·
  `🚪 Cerrar sesión`.
- Cerrar sesión vuelve al login sin reiniciar el proceso.

### 3. Config General con tabs filtrados (Fases 4a–4c)
- Tab **🔒 Mi cuenta** (todos los perfiles) — cambiar la propia contraseña.
- Tabs admin: 🎨 Apariencia, 🏥 Veterinaria, 🧩 Módulos, 🧑 Perfiles,
  👥 Usuarios.
- CRUD de usuarios desde la UI. Contraseña editable en el diálogo de
  edición (vacío = no cambiar).
- Sucursales extraídas a `dialogos/sucursal_detalle.py`.

### 4. Perfiles editables (Sub-fases A y B)
- Perfiles movidos a `config_ui.json#perfiles`. Defaults como semilla.
- Admin blindado: no editable, no eliminable, siempre `modulos="*"`.
- CRUD de perfiles desde la UI. No se elimina un perfil con usuarios
  asignados (rechazo con lista de usuarios).
- Cambios en perfiles aplican al siguiente login del usuario afectado,
  no en caliente.

### 5. Bugs resueltos
- Login en macOS con `transient` sobre padre withdrawn → queda colgado.
- Bootstrap no bloqueante → doble ventana superpuesta.
- Cancelar bootstrap → admin huérfano con contraseña perdida.
- Cerrar ventana principal con Config abierto → messagebox de error.
- `_abrir_configuracion` faltante tras refactor.
- `_abrir_ayuda` duplicado.

## Estado actual
- ✅ Login obligatorio (PBKDF2-SHA256, 600k iteraciones).
- ✅ Sesión en memoria, sin persistencia del perfil.
- ✅ Sidebar filtrado por activo ∧ permitido por perfil.
- ✅ Perfiles editables desde Config General (admin intocable).
- ✅ Usuarios editables desde Config General.
- ✅ Módulos activables/desactivables desde Config.
- ✅ Tab "Mi cuenta" para cambiar la propia contraseña.
- ✅ `scripts/probar_auth.py` con 86 checks verdes.
- ✅ `python3 verificar_config.py` OK.
- ⏳ Pendiente: pruebas con SAT real y cliente final.

## Cómo trabajar
- Configuración compartida → `core/config_ui.py`.
- Cuentas de usuario → `core/usuarios.py` + `usuarios.json`.
- Perfiles → `config_ui.json#perfiles` (semilla en `shared/perfiles.py`).
- Sesión activa → `core/sesion.py`.
- Sucursales → `config/veterinaria.py` (fuente de verdad).
- Registro de módulos → `shared/registro_modulos.py`.
- Antes de tocar: correr `python3 verificar_config.py` y
  `python3 scripts/probar_auth.py`.
- Los JSON de datos NO van a git (`config_ui.json`, `usuarios.json`).

## Pendientes (deuda técnica)

### Testing
- [ ] Ampliar `verificar_config.py` con bloque `[10]` para `usuarios.json`.
- [ ] Ampliar `scripts/probar_auth.py` con tests de integración de perfiles.
- [ ] pytest sobre snapshots reales (anonimizados).
- [ ] Tests del pipeline de Ingresos.

### Autenticación
- [ ] Migración de usuarios huérfanos (perfil borrado tras asignar usuario).
- [ ] Log de auditoría de cambios de perfiles/usuarios.
- [ ] (Opcional) Bloqueo por intentos fallidos.
- [ ] (Opcional) Expiración de sesión.

### Módulos y arquitectura
- [ ] Refactor v3.0.0 por dominio funcional.
- [ ] Rotación de snapshots SAT.
- [ ] Anexar + reordenar Excel de Egresos con anotaciones.

### Documentación
- [ ] Sección de login y perfiles en `MANUAL.md`.