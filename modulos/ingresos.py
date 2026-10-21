# -*- coding: utf-8 -*-
"""
Sistema de Ingresos - Contabilidad
Interfaz moderna con ttkbootstrap.
Registros por año (un archivo JSON por año).
"""

import sys
import os
import json
import tkinter as tk
from datetime import datetime
from pathlib import Path
import shutil
from tkinter import messagebox, filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# Agregar la raíz del proyecto al path
_raiz = Path(__file__).parent.parent
if str(_raiz) not in sys.path:
    sys.path.insert(0, str(_raiz))

# ============================================================
# IMPORTS INTERNOS
# ============================================================
from config.campos import (
    MESES_ES,
    CAMPOS,
)
from config.temas import (
    obtener_tema,
)
from core.rutas import (
    _CARPETA_DATOS,
    ruta_ingreso,
    ruta_deposito,
)
from core.utilidades import (
    parse_fecha,
    mes_anio_desde_fecha,
    formatear_moneda,
)
from core.persistencia import (
    cargar_db,
    guardar_db,
    actualizar_historial,
    obtener_no_factura_numerico,
)
from core.adjuntos import (
    carpeta_de_registro,
    archivos_del_registro,
    adjuntar_archivos,
)
from excel.generador import (
    archivo_esta_bloqueado,
    escribir_excel,
    anexar_al_excel,
)
from modulos.lector_facturas import (
    procesar_factura,
    agrupar_por_categoria,
    ruta_catalogo_usuario,
    recargar_catalogo,
)


# ============================================================
# MAPEO DE SERIES A CENTROS
# ============================================================
def centro_desde_serie(serie):
    """Devuelve el nombre del centro según la serie del XML."""
    if not serie:
        return None
    s = str(serie).strip().upper()
    s = s.replace("/", "").replace("-", "").replace(" ", "")
    mapeo = {
        "S1": "Central",
        "PRADOS": "Prado",
        "PRADO": "Prado",
    }
    return mapeo.get(s)


# ============================================================
# IMPORTACIÓN DE CATÁLOGO QVET
# ============================================================
def _mapear_categoria_qvet(seccion, familia, subfamilia):
    """Mapea (SECCION, FAMILIA, SUBFAMILIA) del Excel QVET a las 9 categorías."""
    s = (seccion or "").strip().upper()
    f = (familia or "").strip().upper()
    sf = (subfamilia or "").strip().upper()

    if f == "MEDICINA PREVENTIVA" and "VACUNA" in sf:
        return "VACUNA"
    if f == "ALIMENTOS":
        return "PENSION"
    if f in ("FARMACIA", "MEDICAMENTOS"):
        return "MEDICAMENTOS"
    if f == "HIGIENE":
        return "HIGIENE"
    if s == "ESTETICA" or f == "ESTETICA":
        return "ESTETICA"
    if s == "RESIDENCIA" or f in ("PENSION DIARIA", "GUARDERIA"):
        return "PENSION"
    if s == "TRANSPORTE" or f == "TRANSPORTE":
        return "TRANSPORTE"
    if f in (
        "ACCESORIOS", "ROPA", "MOÑOS", "JUGUETES", "CAMAS", "COLLARES",
        "CORREAS", "PECHERAS", "BOZALES", "PLATOS", "CARNAZAS",
        "TRANSPORTADORAS", "MANEJO DE DESECHOS", "ENTRENADORES",
        "CARDAS Y PEINES", "DISPENSADORES",
    ):
        return "ACCESORIOS"
    if s == "CLINICA" or f in (
        "CIRUGIA", "LABORATORIO", "RAYOS X", "ODONTOLOGIA",
        "MATERIAL DE CURACION Y CIRUGIA", "INSTRUMENTAL DE CIRUGIA",
        "EQUIPOS Y MOBILIARIO", "HOSPITALIZACION", "PROCEDIMIENTOS",
        "CONSULTA", "ULTRASONIDO", "ELECTROCARDIOGRAFIA",
        "MEDICINA PREVENTIVA",
    ):
        return "CLINICA"
    return "U"


def _leer_excel_qvet(ruta):
    """
    Lee el Excel de QVET y devuelve (catalogo, descartadas, duplicados).
    Detecta encabezados por contenido.
    """
    import openpyxl
    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    ws = wb.active

    assert ws is not None
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        raise ValueError("El archivo está vacío.")

    idx_header = None
    for i, fila in enumerate(filas[:20]):
        celdas = [str(c or "").strip().upper() for c in fila]
        tiene_desc = any(("DESCRIPCION" in c) or ("DESCRIPCIÓN" in c) for c in celdas)
        tiene_sec = any(("SECCION" in c) or ("SECCIÓN" in c) for c in celdas)
        tiene_fam = any("FAMILIA" in c for c in celdas)
        if tiene_desc and (tiene_sec or tiene_fam):
            idx_header = i
            break

    if idx_header is None:
        raise ValueError(
            "No se encontró la fila de encabezados.\n"
            "Se esperaba una fila con 'DESCRIPCION' y 'SECCION' o 'FAMILIA'."
        )

    header = [str(c or "").strip().upper() for c in filas[idx_header]]

    def _buscar_col(*nombres):
        for j, h in enumerate(header):
            for n in nombres:
                if n in h:
                    return j
        return None

    col_cod = _buscar_col("CODIGO", "CÓDIGO")
    col_desc = _buscar_col("DESCRIPCION", "DESCRIPCIÓN")
    col_sec = _buscar_col("SECCION", "SECCIÓN")
    col_fam = _buscar_col("FAMILIA")
    col_sub = _buscar_col("SUBFAMILIA")

    if col_desc is None:
        raise ValueError("No se encontró la columna DESCRIPCION.")

    catalogo = {}
    descartadas = 0
    apariciones = {}

    for fila in filas[idx_header + 1:]:
        if not fila:
            continue
        desc = str(fila[col_desc] or "").strip().upper()
        if not desc:
            descartadas += 1
            continue
        if desc.startswith("*") or desc.startswith("CONCEPTO_MIGRACION"):
            descartadas += 1
            continue

        cod = ""
        if col_cod is not None:
            cod = str(fila[col_cod] or "").strip()

        sec = str(fila[col_sec] or "").strip().upper() if col_sec is not None else ""
        fam = str(fila[col_fam] or "").strip().upper() if col_fam is not None else ""
        sub = str(fila[col_sub] or "").strip().upper() if col_sub is not None else ""

        cat = _mapear_categoria_qvet(sec, fam, sub)
        apariciones.setdefault(desc, []).append(cod or "(sin código)")
        catalogo[desc] = cat  # última aparición gana

    if not catalogo:
        raise ValueError("No se encontró ningún producto válido en el Excel.")

    duplicados = {
        desc: codigos
        for desc, codigos in apariciones.items()
        if len(codigos) > 1
    }

    return catalogo, descartadas, duplicados


# ============================================================
# PANEL PRINCIPAL (embebible)
# ============================================================
class PanelIngresos(ttk.Frame):
    """Panel principal del módulo de Ingresos."""

    def __init__(self, master, on_volver=None):
        super().__init__(master)
        self._on_volver = on_volver

        try:
            self._anio_cargado = int(datetime.now().year)
        except Exception:
            self._anio_cargado = datetime.now().year

        self.registros = cargar_db(self._anio_cargado)
        self.historial = actualizar_historial(self.registros)
        self.id_actual = None
        self._ultima_factura_xml = None
        self._ultima_factura_pdf = None
        self._sincronizacion_activa = False
        self._construir_ui()
        self._refrescar_tabla()

    # ============================================================
    # UI
    # ============================================================
    def _construir_ui(self):
        top = ttk.LabelFrame(self, text="Filtros", padding=10)
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="Centro:").grid(row=0, column=0, padx=5, sticky="e")
        self.var_centro = ttk.StringVar(value="Central")
        ttk.Combobox(
            top, textvariable=self.var_centro,
            values=["Central", "Prado"],
            width=12, state="readonly", bootstyle="primary",
        ).grid(row=0, column=1, padx=5)

        ttk.Label(top, text="Año:").grid(row=0, column=2, padx=5, sticky="e")
        self.var_anio = ttk.StringVar(value=str(datetime.now().year))
        ttk.Entry(
            top, textvariable=self.var_anio, width=6,
            style="Custom.TEntry",
        ).grid(row=0, column=3, padx=5)

        ttk.Label(top, text="Mes:").grid(row=0, column=4, padx=5, sticky="e")
        self.var_mes = ttk.StringVar(value=MESES_ES[datetime.now().month - 1])
        ttk.Combobox(
            top, textvariable=self.var_mes,
            values=MESES_ES, width=11, state="readonly",
            bootstyle="primary",
        ).grid(row=0, column=5, padx=5)

        ttk.Button(
            top, text="Abrir carpeta",
            command=self._abrir_carpeta_ingreso,
            bootstyle="info-outline",
        ).grid(row=0, column=6, padx=10)

        botones = ttk.Frame(self, padding=(10, 5))
        botones.pack(fill="x", padx=10)

        acciones = [
            ("⚡ Sincronizar",        self._sincronizar,       "info-outline"),
            ("📥 Leer factura",      self._leer_factura,      "info-outline"),
            ("🏷️ Reclasificar",      self._abrir_reclasificador, "warning-outline"),
            ("📊 Generar Excel",     self._generar_excel,     "success-outline"),
            ("📈 Reportes",          self._ver_reportes,      "info-outline"),
            ("📜 Ver logs",          self._ver_logs,          "secondary-outline"),
            ("🔧 Reset caché",       self._reset_cache,       "secondary-outline"),
        ]

        for txt, cmd, estilo in acciones:
            ttk.Button(
                botones, text=txt, command=cmd, bootstyle=estilo,
            ).pack(side="left", padx=3)

        self.btn_importar_catalogo = ttk.Button(
            botones,
            text="📥 Importar catálogo QVET",
            command=self._importar_catalogo,
            bootstyle="warning",
        )
        self._actualizar_boton_catalogo()

        frame_tabla = ttk.LabelFrame(self, text="Registros", padding=5)
        frame_tabla.pack(fill="both", expand=True, padx=10, pady=5)

        contenedor = ttk.Frame(frame_tabla)
        contenedor.pack(fill="both", expand=True)

        cols_vis = [
            "no_factura", "qvet", "fecha", "nombre", "rfc",
            "total", "efectivo", "tc", "td", "cheque", "transfer",
            "folio_fiscal", "centro", "adjuntos",
        ]
        encabezados = {
            "no_factura": "No. FACTURA",
            "qvet": "QVET",
            "fecha": "FECHA",
            "nombre": "NOMBRE",
            "rfc": "RFC",
            "total": "TOTAL",
            "efectivo": "EFECTIVO",
            "tc": "TC",
            "td": "TD",
            "cheque": "CHEQUE",
            "transfer": "TRANSFER",
            "folio_fiscal": "FOLIO FISCAL",
            "centro": "CENTRO",
            "adjuntos": "📎",
        }
        anchos = {
            "no_factura": 110, "qvet": 90, "fecha": 90, "nombre": 200,
            "rfc": 120, "total": 90, "efectivo": 80, "tc": 80, "td": 80,
            "cheque": 80, "transfer": 80, "folio_fiscal": 260,
            "centro": 80, "adjuntos": 50,
        }

        self.tabla = ttk.Treeview(
            contenedor, columns=cols_vis, show="headings",
            height=20, bootstyle="primary",
        )
        for c in cols_vis:
            self.tabla.heading(c, text=encabezados[c])
            self.tabla.column(c, width=anchos[c],
                              anchor="center" if c != "nombre" else "w")

        sb_v = ttk.Scrollbar(contenedor, orient="vertical",
                             command=self.tabla.yview)
        sb_h = ttk.Scrollbar(contenedor, orient="horizontal",
                             command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        self.tabla.grid(row=0, column=0, sticky="nsew")
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        contenedor.rowconfigure(0, weight=1)
        contenedor.columnconfigure(0, weight=1)

        self.lbl_totales = ttk.Label(
            self, text="", font=("Segoe UI", 10, "bold"),
        )
        self.lbl_totales.pack(fill="x", padx=15, pady=(0, 8))

        self.tabla.bind("<Double-Button-1>", self._ver_adjuntos_seleccionado)
        self.var_anio.trace_add("write", self._al_cambiar_anio)
        self.var_mes.trace_add("write", lambda *a: self._refrescar_tabla())
        self.var_centro.trace_add("write", lambda *a: self._refrescar_tabla())

    # ============================================================
    # CATÁLOGO QVET
    # ============================================================
    def _actualizar_boton_catalogo(self):
        try:
            existe = ruta_catalogo_usuario().exists()
        except Exception:
            existe = False

        if existe:
            self.btn_importar_catalogo.configure(
                text="🔄 Actualizar catálogo QVET",
                bootstyle="info",
            )
        else:
            self.btn_importar_catalogo.configure(
                text="📥 Importar catálogo QVET",
                bootstyle="warning",
            )
        if not self.btn_importar_catalogo.winfo_ismapped():
            self.btn_importar_catalogo.pack(side="left", padx=3)

    def _importar_catalogo(self):
        ruta = filedialog.askopenfilename(
            title="Selecciona el catálogo QVET (Excel o JSON)",
            filetypes=[
                ("Excel o JSON", "*.xlsx *.xls *.json"),
                ("Excel", "*.xlsx *.xls"),
                ("JSON", "*.json"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not ruta:
            return

        ext = Path(ruta).suffix.lower()
        destino = ruta_catalogo_usuario()
        destino.parent.mkdir(parents=True, exist_ok=True)

        duplicados = {}

        if ext == ".json":
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    nuevos = json.load(f)
                if not isinstance(nuevos, dict) or not nuevos:
                    messagebox.showerror(
                        "Catálogo inválido",
                        "El JSON no tiene el formato esperado.\n"
                        "Debe ser {producto: categoría}.",
                        parent=self,
                    )
                    return
                descartadas = 0
            except Exception as e:
                messagebox.showerror(
                    "Error al leer",
                    f"No se pudo leer el archivo:\n{e}",
                    parent=self,
                )
                return
        elif ext in (".xlsx", ".xls"):
            try:
                nuevos, descartadas, duplicados = _leer_excel_qvet(ruta)
            except Exception as e:
                messagebox.showerror(
                    "Error al leer Excel",
                    f"No se pudo procesar el Excel:\n{e}",
                    parent=self,
                )
                return
        else:
            messagebox.showerror(
                "Formato no soportado",
                f"Extensión no soportada: {ext}\nUsa .xlsx, .xls o .json.",
                parent=self,
            )
            return

        existente = {}
        if destino.exists():
            try:
                with open(destino, "r", encoding="utf-8") as f:
                    existente = json.load(f)
                if not isinstance(existente, dict):
                    existente = {}
            except Exception:
                existente = {}

        hubo_catalogo_previo = bool(existente)

        nuevos_agregados = []
        ya_existentes = 0
        for prod, cat in nuevos.items():
            if prod in existente:
                ya_existentes += 1
            else:
                existente[prod] = cat
                nuevos_agregados.append(prod)

        try:
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(existente, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror(
                "Error al guardar",
                f"No se pudo guardar el catálogo:\n{e}",
                parent=self,
            )
            return

        try:
            catalogo = recargar_catalogo()
            total = len(catalogo) if isinstance(catalogo, dict) else 0
        except Exception:
            total = len(existente)

        self._actualizar_boton_catalogo()

        accion = "actualizado" if hubo_catalogo_previo else "creado"
        lineas = [
            f"✅ Catálogo {accion}.",
            "",
            f"Productos en el archivo: {len(nuevos)}",
            f"Ya existían en el catálogo: {ya_existentes}",
            f"🆕 Nuevos agregados: {len(nuevos_agregados)}",
        ]
        if descartadas:
            lineas.append(f"⚠️ Filas descartadas: {descartadas}")
        lineas += ["", f"Total en catálogo: {total}", f"Ubicación: {destino}"]

        if nuevos_agregados:
            muestra = nuevos_agregados[:15]
            lineas.append("")
            lineas.append(f"Primeros {len(muestra)} nuevos:")
            for p in muestra:
                lineas.append(f"  • {p}")
            if len(nuevos_agregados) > 15:
                lineas.append(f"  … y {len(nuevos_agregados) - 15} más")

        messagebox.showinfo("Catálogo QVET", "\n".join(lineas), parent=self)

        if duplicados:
            self._mostrar_duplicados(duplicados)

    def _mostrar_duplicados(self, duplicados):
        total_dup = sum(len(v) for v in duplicados.values()) - len(duplicados)
        lineas = [
            f"Se encontraron {len(duplicados)} nombre(s) repetido(s) en el Excel.",
            f"({total_dup} fila(s) extra en total)",
            "",
            "En el catálogo solo se conserva la ÚLTIMA aparición.",
            "Corrige estos nombres directamente en QVET:",
            "",
        ]
        for desc, codigos in duplicados.items():
            codigos_str = ", ".join(codigos)
            lineas.append(f"  • {desc}")
            lineas.append(f"      códigos: {codigos_str}")
        texto = "\n".join(lineas)

        win = tk.Toplevel(self)
        win.title("Nombres duplicados en el Excel")
        win.geometry("640x480")
        win.transient(self.winfo_toplevel())

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"⚠️ {len(duplicados)} nombre(s) duplicado(s) en el Excel",
            font=("Segoe UI", 11, "bold"),
            bootstyle="warning",
        ).pack(anchor="w", pady=(0, 8))

        texto_widget = tk.Text(frame, wrap="word", height=20)
        texto_widget.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(frame, orient="vertical",
                           command=texto_widget.yview)
        sb.pack(side="right", fill="y")
        texto_widget.configure(yscrollcommand=sb.set)

        texto_widget.insert("1.0", texto)
        texto_widget.configure(state="disabled")

        ttk.Button(
            win, text="Cerrar", command=win.destroy, bootstyle="secondary",
        ).pack(pady=8)

    # ============================================================
    # TABLA
    # ============================================================
    def _al_cambiar_anio(self, *args):
        try:
            anio = int(self.var_anio.get())
        except Exception:
            return
        if self._anio_cargado != anio:
            self.registros = cargar_db(anio)
            self._anio_cargado = anio
        self._refrescar_tabla()

    def _refrescar_tabla(self):
        for i in self.tabla.get_children():
            self.tabla.delete(i)

        try:
            anio = int(self.var_anio.get())
        except Exception:
            anio = self._anio_cargado

        centro = self.var_centro.get()
        mes = self.var_mes.get()

        filtrados = [
            r for r in self.registros
            if r.get("centro") == centro
            and r.get("anio") == anio
            and r.get("mes") == mes
        ]

        def clave_orden(r):
            n = obtener_no_factura_numerico(r.get("no_factura", ""))
            return (n is None, n or 0, str(r.get("no_factura", "")))
        filtrados.sort(key=clave_orden)

        total_sum = 0.0
        for r in filtrados:
            try:
                n_adj = len(archivos_del_registro(r))
            except Exception:
                n_adj = 0

            self.tabla.insert(
                "", "end", iid=str(r.get("id")),
                values=(
                    r.get("no_factura", ""),
                    r.get("qvet", ""),
                    r.get("fecha", ""),
                    r.get("nombre", ""),
                    r.get("rfc", ""),
                    formatear_moneda(r.get("total", 0)),
                    formatear_moneda(r.get("efectivo", 0)),
                    formatear_moneda(r.get("tc", 0)),
                    formatear_moneda(r.get("td", 0)),
                    formatear_moneda(r.get("cheque", 0)),
                    formatear_moneda(r.get("transfer", 0)),
                    r.get("folio_fiscal", ""),
                    r.get("centro", ""),
                    f"📎 {n_adj}" if n_adj else "",
                ),
            )
            total_sum += float(r.get("total", 0) or 0)

        self.lbl_totales.configure(
            text=f"Registros: {len(filtrados)}  |  Total: ${total_sum:,.2f}"
        )

    # ============================================================
    # SELECCIÓN
    # ============================================================
    def _actualizar_titulo(self):
        pass

    def _obtener_seleccionado(self):
        sel = self.tabla.selection()
        if not sel:
            return None
        try:
            id_sel = int(sel[0])
        except Exception:
            return None
        for r in self.registros:
            if r.get("id") == id_sel:
                return r
        return None

    def _ver_adjuntos_seleccionado(self, event=None):
        reg = self._obtener_seleccionado()
        if not reg:
            messagebox.showinfo("Ver adjuntos", "Selecciona un registro.")
            return

        from dialogos.adjuntos import abrir_dialogo_adjuntos
        fue_eliminado = abrir_dialogo_adjuntos(self, reg)

        if fue_eliminado:
            self.registros = [
                r for r in self.registros if r.get("id") != reg.get("id")
            ]
            try:
                anio = int(self.var_anio.get())
            except Exception:
                anio = self._anio_cargado
            guardar_db(self.registros, anio)
            self.historial = actualizar_historial(self.registros)
            self._refrescar_tabla()

    def _eliminar_seleccionado(self):
        reg = self._obtener_seleccionado()
        if not reg:
            messagebox.showinfo("Eliminar", "Selecciona un registro.")
            return

        from dialogos.adjuntos import abrir_dialogo_adjuntos
        fue_eliminado = abrir_dialogo_adjuntos(self, reg)

        if fue_eliminado:
            self.registros = [
                r for r in self.registros if r.get("id") != reg.get("id")
            ]
            try:
                anio = int(self.var_anio.get())
            except Exception:
                anio = self._anio_cargado
            guardar_db(self.registros, anio)
            self.historial = actualizar_historial(self.registros)
            self._refrescar_tabla()

    def _abrir_carpeta_registro(self):
        reg = self._obtener_seleccionado()
        if not reg:
            return
        try:
            carpeta = carpeta_de_registro(reg)
            if carpeta and carpeta.exists():
                self._abrir_carpeta(carpeta)
            else:
                messagebox.showinfo(
                    "Sin carpeta",
                    "Este registro no tiene carpeta creada."
                )
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la carpeta:\n{e}")

    # ============================================================
    # ACCIONES DE BOTONES
    # ============================================================
    def _sincronizar(self):
        if self._sincronizacion_activa:
            messagebox.showwarning(
                "Sincronización en curso",
                "Ya hay una sincronización activa.\n\n"
                "Espera a que termine o ciérrala antes de iniciar otra.",
                parent=self,
            )
            return

        self._sincronizacion_activa = True
        try:
            from dialogos.sincronizar import sincronizar_facturas
            sincronizar_facturas(self)
        finally:
            self._sincronizacion_activa = False

    def _leer_factura(self):
        """
        Lee un XML y busca automáticamente el PDF con el mismo nombre.
        Si no lo encuentra, lo pide.
        """
        ruta_xml = filedialog.askopenfilename(
            title="Selecciona el XML de la factura",
            filetypes=[("XML CFDI", "*.xml"), ("Todos", "*.*")],
        )
        if not ruta_xml:
            return

        # Buscar PDF automáticamente en la misma carpeta con el mismo nombre
        ruta_pdf = None
        p_xml = Path(ruta_xml)
        candidatos = [
            p_xml.with_suffix(".pdf"),
            p_xml.with_suffix(".PDF"),
        ]
        for c in candidatos:
            if c.exists():
                ruta_pdf = str(c)
                break

        # Si no aparece con el mismo nombre, buscar cualquier PDF en la carpeta
        if not ruta_pdf:
            pdfs_misma_carpeta = list(p_xml.parent.glob("*.pdf")) + \
                                 list(p_xml.parent.glob("*.PDF"))
            if len(pdfs_misma_carpeta) == 1:
                ruta_pdf = str(pdfs_misma_carpeta[0])

        # Si aún no, preguntar al usuario
        if not ruta_pdf:
            ruta_pdf = filedialog.askopenfilename(
                title="No se encontró el PDF automáticamente. Selecciónalo:",
                filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
                initialdir=str(p_xml.parent),
            )
            if not ruta_pdf:
                messagebox.showwarning(
                    "Falta el PDF",
                    "El PDF es obligatorio. La factura no se procesó.",
                )
                return

        try:
            datos = procesar_factura(ruta_xml, ruta_pdf)
        except Exception as e:
            messagebox.showerror(
                "Error al leer factura",
                f"No se pudo procesar la factura:\n{e}",
            )
            return

        self._ultima_factura_xml = ruta_xml
        self._ultima_factura_pdf = ruta_pdf

        # Nuevo unpacking: 4 valores (agregado no_catalogados)
        resumen, datos_completos, avisos, no_catalogados = \
            self._llenar_desde_factura(datos)

        # Una sola ventana con ambos tipos de pendientes
        todos_pendientes = list(no_catalogados or []) + list(avisos or [])
        if todos_pendientes:
            try:
                from dialogos.registrar_productos import abrir_dialogo_registrar_productos
                abrir_dialogo_registrar_productos(self, todos_pendientes)
            except Exception:
                pass

        self._guardar_silencioso(datos_completos)

        try:
            self.var_centro.set(datos_completos.get("centro", "Central"))
            self.var_anio.set(str(datos_completos.get("anio", datetime.now().year)))
            self.var_mes.set(
                datos_completos.get("mes", MESES_ES[datetime.now().month - 1])
            )
        except Exception:
            pass

        self._refrescar_tabla()

        # Mensaje final con conteo
        n_productos = sum(
            len(prods)
            for prods in datos.get("productos_por_remision", {}).values()
        )
        lineas = [
            f"Factura leída: {datos.get('no_factura', '')}",
            f"Centro: {datos_completos.get('centro', '?')}",
            f"Año: {datos_completos.get('anio', '?')} | "
            f"Mes: {datos_completos.get('mes', '?')}",
            f"Total: ${datos.get('total', 0):,.2f}",
            "",
            f"Productos procesados: {n_productos}",
        ]
        if no_catalogados:
            lineas.append(f"⚠️ No catalogados: {len(no_catalogados)}")
        if avisos:
            lineas.append(f"⚠️ Reclasificaciones: {len(avisos)}")
        lineas += ["", "Registro guardado."]

        messagebox.showinfo("Factura leída", "\n".join(lineas))

    def _abrir_reclasificador(self):
        from dialogos.reclasificador import abrir_dialogo_reclasificador
        abrir_dialogo_reclasificador(self)

    def _generar_excel(self):
        if not self.registros:
            messagebox.showwarning("Sin datos", "No hay registros.")
            return

        try:
            anio = int(self.var_anio.get())
        except Exception:
            messagebox.showerror("Error", "Año inválido.")
            return

        mes_idx = MESES_ES.index(self.var_mes.get()) + 1
        mes_nombre = self.var_mes.get()
        centro = self.var_centro.get()

        filtrados = [
            r for r in self.registros
            if r.get("anio") == anio
            and r.get("mes") == mes_nombre
            and r.get("centro") == centro
        ]

        def _clave_orden(r):
            fecha_str = r.get("fecha", "")
            try:
                fecha_dt = datetime.strptime(fecha_str, "%d/%m/%Y")
            except Exception:
                fecha_dt = datetime.min
            no_factura = obtener_no_factura_numerico(r.get("no_factura", "")) or 0
            return (fecha_dt, no_factura)
        filtrados.sort(key=_clave_orden)

        if not filtrados:
            messagebox.showwarning(
                "Sin datos",
                f"No hay registros para {centro} - {mes_nombre} {anio}.",
            )
            return

        carpeta = ruta_deposito(anio, mes_idx)
        carpeta.mkdir(parents=True, exist_ok=True)

        nombre = f"Resumen {centro} - {mes_nombre} {anio}.xlsx"
        ruta_xlsx = carpeta / nombre
        existe = ruta_xlsx.exists()

        if archivo_esta_bloqueado(ruta_xlsx):
            messagebox.showerror(
                "Archivo en uso",
                f"El archivo Excel ya existe y está abierto.\n\n"
                f"Archivo:\n{ruta_xlsx}\n\n"
                f"Cierra el archivo y vuelve a intentar.",
            )
            return

        try:
            if existe:
                respuesta = messagebox.askyesnocancel(
                    "Archivo existente",
                    f"El archivo Excel ya existe:\n{ruta_xlsx}\n\n"
                    f"• Sí → Anexar solo los registros NUEVOS\n"
                    f"• No → Reordenar TODO (borra y regenera)\n"
                    f"• Cancelar → No hacer nada",
                    icon="question",
                )
                if respuesta is None:
                    return
                elif respuesta is True:
                    nuevos, omitidos = anexar_al_excel(ruta_xlsx, filtrados)
                    if nuevos == 0:
                        messagebox.showinfo(
                            "Sin novedades",
                            f"El archivo ya contiene todos los registros.\n\n"
                            f"Ya presentes: {omitidos}",
                        )
                        return
                    msg = (
                        f"Archivo ACTUALIZADO:\n{ruta_xlsx}\n\n"
                        f"Nuevos: {nuevos}\n"
                        f"Ya existian: {omitidos}"
                    )
                else:
                    ruta_backup = self._backup_excel(ruta_xlsx)
                    try:
                        ruta_xlsx.unlink()
                    except Exception as e:
                        messagebox.showerror(
                            "Error al borrar", f"No se pudo borrar:\n{e}"
                        )
                        return
                    escribir_excel(
                        ruta_xlsx, filtrados,
                        var_mes=mes_nombre, var_anio=anio,
                    )
                    msg = (
                        f"Archivo REORDENADO:\n{ruta_xlsx}\n\n"
                        f"Registros: {len(filtrados)}"
                    )
                    if ruta_backup:
                        msg += f"\n\nBackup: {ruta_backup.name}"
            else:
                escribir_excel(
                    ruta_xlsx, filtrados,
                    var_mes=mes_nombre, var_anio=anio,
                )
                msg = (
                    f"Archivo creado:\n{ruta_xlsx}\n\n"
                    f"Registros: {len(filtrados)}"
                )
        except PermissionError:
            messagebox.showerror(
                "Archivo en uso",
                f"Cierra el archivo Excel y vuelve a intentar.",
            )
            return
        except Exception as e:
            messagebox.showerror("Error al crear Excel", str(e))
            return

        messagebox.showinfo("Excel generado", msg)
        self._abrir_carpeta(carpeta)

    @staticmethod
    def _backup_excel(ruta_xlsx):
        if not ruta_xlsx.exists():
            return None
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            nombre = f"{ruta_xlsx.stem}_backup_{timestamp}{ruta_xlsx.suffix}"
            ruta_backup = ruta_xlsx.parent / nombre
            shutil.copy2(ruta_xlsx, ruta_backup)
            return ruta_backup
        except Exception as e:
            print(f"[_backup_excel] Error: {e}")
            return None

    def _ver_reportes(self):
        from dialogos.reportes import abrir_dialogo_reportes
        abrir_dialogo_reportes(self)

    def _elegir_tema(self):
        from dialogos.temas import abrir_dialogo_temas
        abrir_dialogo_temas(self)

    def _ver_logs(self):
        carpeta = _CARPETA_DATOS / "logs"
        carpeta.mkdir(parents=True, exist_ok=True)
        self._abrir_carpeta(carpeta)

    def _reset_cache(self):
        ruta = _CARPETA_DATOS / "correos_procesados.json"
        if ruta.exists():
            if not messagebox.askyesno(
                "Reset caché",
                "Esto hará que la próxima sincronización descargue TODOS los correos.\n\n"
                "¿Continuar?",
            ):
                return
            try:
                ruta.unlink()
                messagebox.showinfo("Reset caché", "Caché eliminada.")
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar:\n{e}")
        else:
            messagebox.showinfo("Reset caché", "No hay caché para eliminar.")

    # ============================================================
    # HELPERS DE ARCHIVOS
    # ============================================================
    def _abrir_carpeta_ingreso(self):
        try:
            anio = int(self.var_anio.get())
        except Exception:
            return
        mes = MESES_ES.index(self.var_mes.get()) + 1
        ruta = ruta_ingreso(self.var_centro.get(), anio, mes)
        ruta.mkdir(parents=True, exist_ok=True)
        self._abrir_carpeta(ruta)

    @staticmethod
    def _abrir_carpeta(ruta):
        if sys.platform.startswith("win"):
            os.startfile(str(ruta)) # type: ignore
        elif sys.platform == "darwin":
            os.system(f'open "{ruta}"')
        else:
            os.system(f'xdg-open "{ruta}"')

    @staticmethod
    def _abrir_archivo(ruta):
        if sys.platform.startswith("win"):
            os.startfile(str(ruta)) # type: ignore
        elif sys.platform == "darwin":
            os.system(f'open "{ruta}"')
        else:
            os.system(f'xdg-open "{ruta}"')

    # ============================================================
    # FUNCIONES INTERNAS
    # ============================================================
    def _llenar_desde_factura(self, datos):
        """
        Convierte los datos de una factura en un dict del formulario
        para guardarlo silenciosamente.
        Devuelve: (resumen, datos_completos, avisos, no_catalogados)
        """
        serie = datos.get("serie", "").strip()
        centro_detectado = centro_desde_serie(serie) or "Central"
        if not centro_desde_serie(serie):
            print(f"ℹ️  Serie desconocida: '{serie}' → centro por default 'Central'")

        fecha_factura = datos.get("fecha", "")
        mes_detectado, anio_detectado = mes_anio_desde_fecha(fecha_factura)
        anio = anio_detectado or datetime.now().year
        mes = mes_detectado or MESES_ES[datetime.now().month - 1]

        if self._anio_cargado != anio:
            self.registros = cargar_db(anio)
            self._anio_cargado = anio

        datos_completos = {
            "no_factura": str(datos.get("no_factura", "")).upper(),
            "qvet": str(datos.get("qvet", "")).upper(),
            "fecha": datos.get("fecha", ""),
            "nombre": str(datos.get("nombre", "")).upper(),
            "rfc": str(datos.get("rfc", "")).upper(),
            "fecha_impresion": datos.get("fecha_impresion", ""),
            "folio_fiscal": datos.get("folio_fiscal", ""),
            "centro": centro_detectado,
            "anio": anio,
            "mes": mes,
        }

        # Nueva firma: 4 valores
        agrupado, detalle, avisos, no_catalogados = \
            agrupar_por_categoria(datos)

        mapa_campos = {
            "U": {"importe": "u_importe"},
            "ACCESORIOS": {"importe": "ac_importe"},
            "ESTETICA": {"importe": "est_importe"},
            "TRANSPORTE": {"importe": "tra_importe"},
            "VACUNA": {"importe": "vac_importe"},
            "CLINICA": {"importe": "cli_importe"},
            "PENSION": {"importe": "pen_importe"},
            "MEDICAMENTOS": {
                "importe": "med_importe",
                "sin_iva": "med_sin_iva",
            },
            "HIGIENE": {
                "importe": "hig_importe",
                "sin_iva": "hig_sin_iva",
                "sin_ieps_6": "hig_sin_ieps_6",
                "sin_ieps_7": "hig_sin_ieps_7",
            },
        }

        for clave, _, _, tipo in CAMPOS:
            if tipo == "number":
                datos_completos.setdefault(clave, 0.0)

        for cat, valores in agrupado.items():
            if cat not in mapa_campos:
                continue
            for subclave, campo in mapa_campos[cat].items():
                if subclave in valores:
                    datos_completos[campo] = round(valores[subclave], 2)

        # IVA / IEPS calculados
        datos_completos["u_iva"] = round(datos_completos.get("u_importe", 0) * 0.16, 2)
        datos_completos["ac_iva"] = round(datos_completos.get("ac_importe", 0) * 0.16, 2)
        datos_completos["est_iva"] = round(datos_completos.get("est_importe", 0) * 0.16, 2)
        datos_completos["tra_iva"] = round(datos_completos.get("tra_importe", 0) * 0.16, 2)
        datos_completos["pen_iva"] = round(datos_completos.get("pen_importe", 0) * 0.16, 2)
        datos_completos["med_iva"] = round(datos_completos.get("med_sin_iva", 0) * 0.16, 2)
        datos_completos["hig_iva"] = round(datos_completos.get("hig_sin_iva", 0) * 0.16, 2)
        datos_completos["hig_ieps_6"] = round(datos_completos.get("hig_sin_ieps_6", 0) * 0.06, 2)
        datos_completos["hig_ieps_7"] = round(datos_completos.get("hig_sin_ieps_7", 0) * 0.07, 2)

        for campo, expr in detalle.items():
            datos_completos[f"{campo}__expr"] = expr

        pagos = datos.get("pagos", {})
        for clave in ("efectivo", "tc", "td", "cheque", "transfer", "vale"):
            datos_completos[clave] = round(pagos.get(clave, 0.0), 2)

        datos_completos["total"] = round(datos.get("total", 0.0), 2)

        return [], datos_completos, avisos, no_catalogados

    def _guardar_silencioso(self, datos):
        for clave, _, _, tipo in CAMPOS:
            if tipo == "date":
                v = datos.get(clave, "")
                if v:
                    try:
                        datos[clave] = parse_fecha(v).replace("-", "/")
                    except Exception:
                        pass

        datos["id"] = int(datetime.now().timestamp() * 1000)

        try:
            anio_datos = int(datos.get("anio", self._anio_cargado))
        except Exception:
            anio_datos = self._anio_cargado

        if anio_datos != self._anio_cargado:
            regs_destino = cargar_db(anio_datos)
        else:
            regs_destino = self.registros

        regs_destino.append(datos)
        guardar_db(regs_destino, anio_datos)

        if anio_datos != self._anio_cargado:
            self._anio_cargado = anio_datos
        self.registros = regs_destino
        self.historial = actualizar_historial(regs_destino)

        try:
            fecha_carpeta = parse_fecha(datos.get("fecha", ""))
            ruta = ruta_ingreso(
                datos["centro"], datos["anio"],
                MESES_ES.index(datos["mes"]) + 1,
            ) / fecha_carpeta
            ruta.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        rutas_adjuntar = []
        if self._ultima_factura_xml and Path(self._ultima_factura_xml).exists():
            rutas_adjuntar.append(self._ultima_factura_xml)
        if self._ultima_factura_pdf and Path(self._ultima_factura_pdf).exists():
            rutas_adjuntar.append(self._ultima_factura_pdf)

        if rutas_adjuntar:
            try:
                adjuntar_archivos(datos, rutas_adjuntar)
            except Exception as e:
                print(f"[_guardar_silencioso] Error al adjuntar: {e}")

        carpeta_descargas = _CARPETA_DATOS / "facturas_descargadas"
        for r in rutas_adjuntar:
            try:
                p = Path(r)
                if p.exists() and p.parent == carpeta_descargas:
                    p.unlink()
            except Exception:
                pass

        self._ultima_factura_xml = None
        self._ultima_factura_pdf = None

    def _avisar_reclasificacion(self, avisos):
        if not avisos:
            return
        try:
            from dialogos.registrar_productos import abrir_dialogo_registrar_productos
            abrir_dialogo_registrar_productos(self, avisos)
        except Exception:
            pass

    def _avisar_no_catalogados(self, no_catalogados):
        if not no_catalogados:
            return
        try:
            from dialogos.registrar_productos import abrir_dialogo_registrar_productos
            abrir_dialogo_registrar_productos(self, no_catalogados)
        except Exception:
            pass


# ================================================================
# Wrapper legacy
# ================================================================
class AppIngresos(ttk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master) # type: ignore
        self.title("Vet Suite — Ingresos")
        self.geometry("1300x880")
        self.minsize(1050, 700)
        panel = PanelIngresos(self)
        panel.pack(fill="both", expand=True)


# ============================================================
if __name__ == "__main__":
    import ttkbootstrap as ttk_local
    raiz = ttk_local.Window(themename=obtener_tema())
    raiz.withdraw()
    app = AppIngresos(master=raiz)
    app.protocol("WM_DELETE_WINDOW", raiz.destroy)
    raiz.mainloop()