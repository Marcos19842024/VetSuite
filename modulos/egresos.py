# -*- coding: utf-8 -*-
"""
modulos/egresos.py
Modulo de Egresos con tabla, edicion, reportes y generacion de Excel.
"""

import sys
import shutil
from datetime import datetime
from pathlib import Path

_raiz = Path(__file__).parent.parent
if str(_raiz) not in sys.path:
    sys.path.insert(0, str(_raiz))

import tkinter as tk
import ttkbootstrap as ttk

from tkinter import messagebox

from config.campos import MESES_ES
from config.config_egresos import (
    cargar_solicitud_activa,
    horas_desde_solicitud,
    limpiar_solicitud_activa,
)
from core.persistencia_egresos import (
    cargar_db_egresos,
    guardar_db_egresos,
    actualizar_historial_egresos,
)
from core.rutas_egresos import (
    ruta_egreso,
    ruta_deposito_egreso,
)


class PanelEgresos(ttk.Frame):
    """
    Panel principal del módulo de Egresos.

    Diseñado para ser embebido como Frame dentro de Vet Suite.
    También puede usarse en un Toplevel si se necesita (ver wrapper abajo).
    """

    def __init__(self, master, on_volver=None):
        super().__init__(master)
        self._on_volver = on_volver

        # Estado interno
        try:
            self._anio_cargado = int(datetime.now().year)
        except Exception:
            self._anio_cargado = datetime.now().year

        self.registros = cargar_db_egresos(self._anio_cargado)
        self.var_anio = ttk.StringVar(value=str(self._anio_cargado))
        self.var_mes = ttk.StringVar(value=MESES_ES[datetime.now().month - 1])
        self.var_sucursal = ttk.StringVar(value="Baalak")

        self._construir_ui()
        self._refrescar_tabla()
        self._actualizar_boton_sat()

    # ============================================================
    # UI
    # ============================================================
    def _construir_ui(self):
        # ---- Barra superior de filtros ----
        top = ttk.LabelFrame(self, text="Configuracion", padding=10)
        top.pack(fill="x", padx=10, pady=5)

        ttk.Label(top, text="Sucursal:").grid(row=0, column=0, padx=5, sticky="e")
        ttk.Combobox(
            top, textvariable=self.var_sucursal,
            values=["Baalak", "Animalia"],
            width=12, state="readonly", bootstyle="primary",
        ).grid(row=0, column=1, padx=5)

        ttk.Label(top, text="Anio:").grid(row=0, column=2, padx=5, sticky="e")
        ttk.Entry(top, textvariable=self.var_anio, width=6,
                  style="Custom.TEntry").grid(row=0, column=3, padx=5)

        ttk.Label(top, text="Mes:").grid(row=0, column=4, padx=5, sticky="e")
        ttk.Combobox(
            top, textvariable=self.var_mes,
            values=MESES_ES, width=11, state="readonly",
            bootstyle="primary",
        ).grid(row=0, column=5, padx=5)

        # ---- Filtro Método (Todas / PUE / PPD) ----
        ttk.Label(top, text="Método:").grid(row=0, column=6, padx=(15, 5), sticky="e")
        self.var_filtro_metodo = ttk.StringVar(value="Todas")
        ttk.Combobox(
            top, textvariable=self.var_filtro_metodo,
            values=["Todas", "PUE", "PPD"],
            width=10, state="readonly", bootstyle="primary",
        ).grid(row=0, column=7, padx=5)

        # ---- Filtro Forma de pago ----
        ttk.Label(top, text="Forma:").grid(row=0, column=8, padx=(15, 5), sticky="e")
        self.var_filtro_forma = ttk.StringVar(value="Todas")
        ttk.Combobox(
            top, textvariable=self.var_filtro_forma,
            values=["Todas", "Efectivo", "TC", "TD", "Transferencia", "PPD"],
            width=14, state="readonly", bootstyle="primary",
        ).grid(row=0, column=9, padx=5)

        ttk.Button(
            top, text="Abrir carpeta",
            command=self._abrir_carpeta_egreso,
            bootstyle="info-outline",
        ).grid(row=0, column=10, padx=10)

        # ---- Barra de botones de acciones ----
        botones = ttk.Frame(self, padding=(10, 5))
        botones.pack(fill="x", padx=10)

        # ---- Panel de solicitud SAT actual ----
        self._frame_sat = ttk.LabelFrame(self, text="Solicitud SAT actual", padding=5)
        self._frame_sat.pack(fill="x", padx=10, pady=(0, 5))

        cols_sat = ("periodo", "estado", "cfdi", "ultima", "acciones")
        self._tabla_sat = ttk.Treeview(
            self._frame_sat, columns=cols_sat, show="headings", height=1,
        )
        for c, txt, w in (
            ("periodo", "Período", 110),
            ("estado", "Estado", 200),
            ("cfdi", "CFDI", 80),
            ("ultima", "Últ. verificación", 150),
            ("acciones", "Acciones", 130),
        ):
            self._tabla_sat.heading(c, text=txt)
            self._tabla_sat.column(c, width=w, anchor="center")
        self._tabla_sat.pack(fill="x")

        self._lbl_sat_sin = ttk.Label(
            self._frame_sat,
            text="No hay solicitud activa.",
            foreground="gray",
        )
        self._lbl_sat_sin.pack(anchor="w")

        self._refrescar_tabla_sat()

        # Frame dinamico: descargar / verificar
        self._btn_sat_frame = ttk.Frame(botones)
        self._btn_sat_frame.pack(side="left", padx=3)

        self._btn_descargar = ttk.Button(
            self._btn_sat_frame,
            text="📥 Descargar del SAT",
            command=self._descargar_sat,
            bootstyle="info-outline",
        )

        self._btn_verificar = ttk.Button(
            self._btn_sat_frame,
            text="🔄 Verificar solicitud",
            command=self._verificar_solicitud,
            bootstyle="warning-outline",
        )

        ttk.Button(
            botones, text="🏢 Clasificar sucursal",
            command=self._clasificar_sucursal,
            bootstyle="warning-outline",
        ).pack(side="left", padx=3)

        ttk.Button(
            botones, text="📊 Generar Excel",
            command=self._generar_excel,
            bootstyle="success-outline",
        ).pack(side="left", padx=3)

        ttk.Button(
            botones, text="📈 Reportes",
            command=self._ver_reportes,
            bootstyle="info-outline",
        ).pack(side="left", padx=3)

        # ---- Tabla (con scroll horizontal y vertical) ----
        frame_tabla = ttk.LabelFrame(self, text="Registros de Egresos", padding=5)
        frame_tabla.pack(fill="both", expand=True, padx=10, pady=5)

        contenedor = ttk.Frame(frame_tabla)
        contenedor.pack(fill="both", expand=True)

        cols = (
            "linea", "fecha", "folio", "uuid", "rfc_emisor",
            "nombre_emisor", "cp", "subtotal", "iva", "ieps", "total",
            "forma_pago_texto", "metodo_pago", "observacion",
            "sucursal", "carpeta",
        )
        encabezados = {
            "linea": "#",
            "fecha": "FECHA",
            "folio": "FACTURA",
            "uuid": "UUID",
            "rfc_emisor": "RFC EMISOR",
            "nombre_emisor": "NOMBRE EMISOR",
            "cp": "C.P.",
            "subtotal": "SUBTOTAL",
            "iva": "IVA",
            "ieps": "IEPS",
            "total": "TOTAL",
            "forma_pago_texto": "FORMA PAGO",
            "metodo_pago": "METODO",
            "observacion": "OBSERVACION",
            "sucursal": "SUCURSAL",
            "carpeta": "CARPETA",
        }
        anchos = {
            "linea": 40,
            "fecha": 90,
            "folio": 130,
            "uuid": 260,
            "rfc_emisor": 120,
            "nombre_emisor": 220,
            "cp": 70,
            "subtotal": 90,
            "iva": 80,
            "ieps": 70,
            "total": 100,
            "forma_pago_texto": 100,
            "metodo_pago": 70,
            "observacion": 160,
            "sucursal": 90,
            "carpeta": 90,
        }

        self.tabla = ttk.Treeview(
            contenedor, columns=cols, show="headings", height=18,
            bootstyle="primary",
        )
        for c in cols:
            self.tabla.heading(c, text=encabezados[c])
            self.tabla.column(c, width=anchos[c], anchor="center")

        # Scroll vertical
        sb_v = ttk.Scrollbar(contenedor, orient="vertical",
                             command=self.tabla.yview)
        # Scroll horizontal
        sb_h = ttk.Scrollbar(contenedor, orient="horizontal",
                             command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        self.tabla.grid(row=0, column=0, sticky="nsew")
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        contenedor.rowconfigure(0, weight=1)
        contenedor.columnconfigure(0, weight=1)

        # ---- Footer de totales ----
        self.lbl_totales = ttk.Label(
            self, text="", font=("Segoe UI", 10, "bold"),
        )
        self.lbl_totales.pack(fill="x", padx=15, pady=(0, 8))

        # ---- Menu contextual ----
        #self._crear_menu_contextual()

        # ---- Bindings ----
        self.tabla.bind("<Double-Button-1>", self._editar_seleccionado)
        self.var_anio.trace_add("write", self._al_cambiar_anio)
        self.var_mes.trace_add("write", lambda *a: self._refrescar_tabla())
        self.var_sucursal.trace_add("write", lambda *a: self._refrescar_tabla())
        self.var_filtro_metodo.trace_add("write", lambda *a: self._refrescar_tabla())
        self.var_filtro_forma.trace_add("write", lambda *a: self._refrescar_tabla())
        self._tabla_sat.bind("<Double-Button-1>", self._al_seleccionar_sat)

    # ============================================================
    # TABLA DE SOLICITUD SAT
    # ============================================================
    def _refrescar_tabla_sat(self):
        """Pinta la fila de la solicitud activa (o el mensaje de vacío)."""
        for i in self._tabla_sat.get_children():
            self._tabla_sat.delete(i)

        datos = cargar_solicitud_activa()
        if not datos:
            self._lbl_sat_sin.pack(anchor="w")
            self._tabla_sat.pack_forget()
            return

        self._lbl_sat_sin.pack_forget()
        self._tabla_sat.pack(fill="x")

        periodo = f"{datos.get('mes_nombre', '?')} {datos.get('anio', '?')}"
        estado_cod = str(datos.get("estado_solicitud", ""))
        estado_txt = {
            "":   "Sin verificar",
            "1":  "Aceptada (en cola)",
            "2":  "En proceso",
            "3":  "Lista para descargar",
            "4":  "Rechazada",
            "5":  "Vencida",
        }.get(estado_cod, f"Código {estado_cod}")

        cfdi = datos.get("numero_cfdis") or "—"
        ultima = datos.get("ultima_verificacion", "—")
        if "T" in str(ultima):
            ultima = str(ultima).replace("T", " ")[:16]

        accion = "Descargar" if estado_cod == "3" else "Verificar"

        self._tabla_sat.insert(
            "", "end",
            values=(periodo, estado_txt, cfdi, ultima, accion),
        )

    def _al_seleccionar_sat(self, event=None):
        """Al hacer doble clic en la fila: verificar o descargar según estado."""
        datos = cargar_solicitud_activa()
        if not datos:
            return
        if str(datos.get("estado_solicitud", "")) == "3":
            self._verificar_solicitud()   # descarga directa
        else:
            self._verificar_solicitud()   # vuelve a verificar estado

    def _al_verificar_sat(self):
        """Botón 'Verificar' de la fila de la solicitud."""
        self._verificar_solicitud()

    def _crear_menu_contextual(self):
        self.menu_ctx = tk.Menu(self, tearoff=0)
        self.menu_ctx.add_command(label="✏️  Editar", command=self._editar_seleccionado)
        self.menu_ctx.add_command(label="🗑️  Eliminar", command=self._eliminar_seleccionado)
        self.menu_ctx.add_separator()
        self.menu_ctx.add_command(label="📂  Abrir carpeta del XML", command=self._abrir_carpeta_xml)
        self.menu_ctx.add_command(label="📂  Abrir carpeta del mes", command=self._abrir_carpeta_egreso)

        self.tabla.bind("<Button-3>", self._mostrar_menu_ctx)
        self.tabla.bind("<Button-2>", self._mostrar_menu_ctx)
        self.tabla.bind("<Control-Button-1>", self._mostrar_menu_ctx)

    def _mostrar_menu_ctx(self, event):
        item = self.tabla.identify_row(event.y)
        if not item:
            return
        self.tabla.selection_set(item)
        try:
            self.menu_ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu_ctx.grab_release()

    # ============================================================
    # TABLA
    # ============================================================
    def _al_cambiar_anio(self, *args):
        try:
            anio = int(self.var_anio.get())
        except Exception:
            return
        if self._anio_cargado != anio:
            self.registros = cargar_db_egresos(anio)
            self._anio_cargado = anio
        self._refrescar_tabla()

    def _refrescar_tabla(self):
        # Limpiar
        for i in self.tabla.get_children():
            self.tabla.delete(i)

        try:
            anio = int(self.var_anio.get())
        except Exception:
            anio = self._anio_cargado

        mes = self.var_mes.get()
        sucursal = self.var_sucursal.get()

        # Filtros adicionales
        filtro_metodo = getattr(self, "var_filtro_metodo", None)
        filtro_metodo = filtro_metodo.get() if filtro_metodo else "Todas"

        filtro_forma = getattr(self, "var_filtro_forma", None)
        filtro_forma = filtro_forma.get() if filtro_forma else "Todas"

        # Filtrar base: año + mes + sucursal
        filtrados = [
            r for r in self.registros
            if r.get("anio") == anio
            and r.get("mes") == mes
            and r.get("sucursal", "Baalak") == sucursal
        ]

        # Aplicar filtro Método
        if filtro_metodo == "PUE":
            filtrados = [r for r in filtrados if r.get("metodo_pago") != "PPD"]
        elif filtro_metodo == "PPD":
            filtrados = [r for r in filtrados if r.get("metodo_pago") == "PPD"]

        # Aplicar filtro Forma de pago
        if filtro_forma != "Todas":
            filtrados = [
                r for r in filtrados
                if self._forma_pago_de(r) == filtro_forma
            ]

        # Ordenar por fecha + folio
        def _orden(r):
            try:
                partes = r.get("fecha", "").split("/")
                if len(partes) == 3:
                    fecha = (int(partes[2]), int(partes[1]), int(partes[0]))
                else:
                    fecha = (0, 0, 0)
            except Exception:
                fecha = (0, 0, 0)
            return (fecha, str(r.get("folio", "")))

        filtrados.sort(key=_orden)

        for idx, r in enumerate(filtrados, 1):
            self.tabla.insert(
                "", "end", iid=str(r.get("id")),
                values=(
                    idx,
                    r.get("fecha", ""),
                    r.get("folio", ""),
                    r.get("uuid", ""),
                    r.get("rfc_emisor", ""),
                    r.get("nombre_emisor", ""),
                    r.get("cp", ""),
                    f"${r.get('subtotal', 0):,.2f}",
                    f"${r.get('iva', 0):,.2f}",
                    f"${r.get('ieps', 0):,.2f}",
                    f"${r.get('total', 0):,.2f}",
                    r.get("forma_pago_texto", ""),
                    r.get("metodo_pago", ""),
                    r.get("observacion", ""),
                    r.get("sucursal", ""),
                    r.get("carpeta", ""),
                ),
            )

        # Totales
        total = sum(r.get("total", 0) for r in filtrados)
        pue_count = sum(1 for r in filtrados if r.get("metodo_pago") != "PPD")
        ppd_count = sum(1 for r in filtrados if r.get("metodo_pago") == "PPD")

        if filtro_metodo == "PUE":
            texto = f"PUE: {len(filtrados)}  |  Total PUE: ${total:,.2f}"
        elif filtro_metodo == "PPD":
            texto = f"PPD: {len(filtrados)}  |  Total PPD: ${total:,.2f}"
        else:
            total_pue = sum(
                r.get("total", 0) for r in filtrados
                if r.get("metodo_pago") != "PPD"
            )
            total_ppd = sum(
                r.get("total", 0) for r in filtrados
                if r.get("metodo_pago") == "PPD"
            )
            texto = (
                f"Total registros: {len(filtrados)}  |  "
                f"PUE: {pue_count} (${total_pue:,.2f})  |  "
                f"PPD: {ppd_count} (${total_ppd:,.2f})  |  "
                f"Total: ${total:,.2f}"
            )

        self.lbl_totales.configure(text=texto)

    def _forma_pago_de(self, reg):
        """
        Devuelve la forma de pago normalizada de un registro
        (para el filtro).
        """
        # Si es PPD, siempre es "PPD"
        if reg.get("metodo_pago") == "PPD":
            return "PPD"

        forma = reg.get("forma_pago_texto", "")
        if not forma:
            return "Efectivo"

        # Mapear antiguos valores a nuevos
        mapa = {
            "EFVO": "Efectivo",
            "TRANSF": "Transferencia",
            "EFECTIVO": "Efectivo",
            "CHEQUE": "Efectivo",  # por si quedó alguno
        }
        return mapa.get(forma, forma)

    # ============================================================
    # SELECCION
    # ============================================================
    def _obtener_seleccionado(self):
        sel = self.tabla.selection()
        if not sel:
            return None
        id_sel = int(sel[0])
        for r in self.registros:
            if r.get("id") == id_sel:
                return r
        return None

    # ============================================================
    # EDICION
    # ============================================================
    def _editar_seleccionado(self, event=None):
        """Abre el diálogo de edición/adjuntos para el registro seleccionado."""
        reg = self._obtener_seleccionado()
        if not reg:
            messagebox.showinfo("Editar", "Selecciona un registro.")
            return

        from dialogos.egresos_editar import abrir_dialogo_editar_egreso
        resultado = abrir_dialogo_editar_egreso(self, reg)

        # Compatibilidad: si devuelve bool, tratarlo como "guardado"
        if isinstance(resultado, bool):
            resultado = {"guardado": resultado, "eliminado": False}

        if resultado.get("eliminado"):
            # Quitar del JSON
            self.registros = [
                r for r in self.registros if r.get("id") != reg.get("id")
            ]
            try:
                anio = int(self.var_anio.get())
            except Exception:
                anio = self._anio_cargado
            from sat.guardar_egresos import guardar_db_egresos
            guardar_db_egresos(self.registros, anio)
            self._refrescar_tabla()

        elif resultado.get("guardado"):
            # Guardar cambios en JSON + recargar
            self._guardar_cambios()
            try:
                anio = int(self.var_anio.get())
            except Exception:
                anio = self._anio_cargado
            from sat.guardar_egresos import cargar_db_egresos
            self.registros = cargar_db_egresos(anio)
            self._refrescar_tabla()

    def _eliminar_seleccionado(self):
        reg = self._obtener_seleccionado()
        if not reg:
            messagebox.showinfo("Eliminar", "Selecciona un registro.")
            return
        folio = reg.get("folio", "?")
        if not messagebox.askyesno(
            "Eliminar",
            f"¿Eliminar el registro de la factura {folio}?\n\n"
            f"Tambien se eliminara su XML (si existe)."
        ):
            return

        # Borrar XML
        ruta_xml = reg.get("ruta_xml") or reg.get("ruta_xml_destino")
        if ruta_xml:
            try:
                p = Path(ruta_xml)
                if p.exists():
                    p.unlink()
            except Exception as e:
                print(f"Error al eliminar XML: {e}")

        # Quitar del JSON
        self.registros = [r for r in self.registros if r.get("id") != reg.get("id")]
        self._guardar_cambios()
        self._refrescar_tabla()

    def _guardar_cambios(self):
        """Guarda los registros actuales y actualiza el historial."""
        try:
            anio = int(self.var_anio.get())
        except Exception:
            anio = self._anio_cargado
        guardar_db_egresos(self.registros, anio)
        actualizar_historial_egresos(self.registros)

    # ============================================================
    # BOTONES DE ACCION
    # ============================================================
    def _descargar_sat(self):
        from dialogos.descargar_sat import abrir_dialogo_descargar_sat
        abrir_dialogo_descargar_sat(self)
        self.after(2000, self._actualizar_boton_sat)

    def _verificar_solicitud(self):
        from dialogos.descargar_sat import verificar_solicitud_pendiente
        verificar_solicitud_pendiente(self)
        self.after(2000, self._actualizar_boton_sat)

    def _actualizar_boton_sat(self):
        """
        Decide si mostrar 'Descargar' o 'Verificar' según el estado real
        de la solicitud guardada.

        Reglas:
          - Si hay solicitud con estado 1 o 2 (aceptada/en proceso): verificar.
          - Si hay solicitud con estado 3 (terminada): verificar (para descargar).
          - Si hay solicitud sin estado (versión vieja del JSON): verificar.
          - Si hay solicitud con estado 4 o 5 (rechazada/vencida): limpiar y descargar.
          - Sin solicitud: descargar.
        """
        datos = cargar_solicitud_activa()
        if datos:
            estado = str(datos.get("estado_solicitud", ""))

            # Solo limpiamos si el SAT ya nos dijo que está muerta
            if estado in ("4", "5"):
                limpiar_solicitud_activa()
                datos = None
            # estados "1", "2", "3" o "" (vacío, JSON viejo) → se mantiene

        for w in self._btn_sat_frame.winfo_children():
            w.pack_forget()

        if datos:
            self._btn_verificar.pack()
        else:
            self._btn_descargar.pack()

        self._refrescar_tabla_sat()

    def _clasificar_sucursal(self):
        try:
            anio = int(self.var_anio.get())
        except Exception:
            messagebox.showwarning("Anio invalido", "El anio no es valido.")
            return
        from dialogos.clasificar_sucursal import abrir_dialogo_clasificar_sucursal
        abrir_dialogo_clasificar_sucursal(self, anio=anio)
        self._refrescar_tabla()
        self._refrescar_tabla_sat()

    def _ver_reportes(self):
        from dialogos.reportes_egresos import abrir_dialogo_reportes_egresos
        abrir_dialogo_reportes_egresos(self)

    def _abrir_carpeta_xml(self):
        reg = self._obtener_seleccionado()
        if not reg:
            return
        ruta_xml = reg.get("ruta_xml") or reg.get("ruta_xml_destino")
        if not ruta_xml:
            messagebox.showinfo("Sin XML", "Este registro no tiene XML asociado.")
            return
        p = Path(ruta_xml)
        if not p.exists():
            messagebox.showwarning("No existe", f"El archivo no existe:\n{p}")
            return
        self._abrir_carpeta(p.parent)

    def _abrir_carpeta_egreso(self):
        try:
            anio = int(self.var_anio.get())
        except Exception:
            return
        mes_idx = MESES_ES.index(self.var_mes.get()) + 1
        ruta = ruta_egreso(anio, mes_idx)
        ruta.mkdir(parents=True, exist_ok=True)
        self._abrir_carpeta(ruta)

    @staticmethod
    def _abrir_carpeta(ruta):
        import os
        if sys.platform.startswith("win"):
            os.startfile(str(ruta))
        elif sys.platform == "darwin":
            os.system(f'open "{ruta}"')
        else:
            os.system(f'xdg-open "{ruta}"')

    # ============================================================
    # EXCEL
    # ============================================================
    def _generar_excel(self):
        """Genera los Excel PUE y PPD del mes/anio/sucursal activos."""
        try:
            anio = int(self.var_anio.get())
        except Exception:
            messagebox.showwarning("Anio invalido", "El anio no es valido.")
            return

        mes_nombre = self.var_mes.get()
        if mes_nombre not in MESES_ES:
            messagebox.showwarning("Mes invalido", "Selecciona un mes valido.")
            return
        mes_idx = MESES_ES.index(mes_nombre) + 1

        # Filtrar registros de la sucursal activa (Baalak excluye Animalia)
        sucursal_activa = self.var_sucursal.get()
        filtrados = [
            r for r in self.registros
            if r.get("anio") == anio
            and r.get("mes") == mes_nombre
            and r.get("sucursal", "Baalak") == sucursal_activa
        ]

        if not filtrados:
            messagebox.showwarning(
                "Sin datos",
                f"No hay registros para {sucursal_activa} - {mes_nombre} {anio}."
            )
            return

        pue = [r for r in filtrados if r.get("metodo_pago") != "PPD"]
        ppd = [r for r in filtrados if r.get("metodo_pago") == "PPD"]

        # Ordenar por fecha + folio antes de escribir
        from sat.mover_egresos import _ordenar_facturas
        pue = _ordenar_facturas(pue)
        ppd = _ordenar_facturas(ppd)

        carpeta = ruta_deposito_egreso(anio, mes_idx)
        carpeta.mkdir(parents=True, exist_ok=True)

        from excel.egresos import generar_excel_pue, generar_excel_ppd

        msgs = []

        # PUE
        if pue:
            ruta_pue = carpeta / f"RELACION FACTURAS PUE - {mes_nombre} {anio}.xlsx"
            self._generar_con_backup(
                ruta_pue,
                lambda ruta: generar_excel_pue(pue, ruta, mes_nombre, anio),
                msgs, f"PUE ({len(pue)} facturas)",
                tipo="PUE", facturas=pue,
            )

        # PPD
        if ppd:
            ruta_ppd = carpeta / f"RELACION FACTURAS PPD - {mes_nombre} {anio}.xlsx"
            self._generar_con_backup(
                ruta_ppd,
                lambda ruta: generar_excel_ppd(ppd, ruta, mes_nombre, anio),
                msgs, f"PPD ({len(ppd)} facturas)",
                tipo="PPD", facturas=ppd,
            )

        msgs.append(f"\nCarpeta:\n{carpeta}")
        messagebox.showinfo("Excel generado", "\n".join(msgs))
        self._abrir_carpeta(carpeta)

    def _generar_con_backup(self, ruta_xlsx, generador, msgs, etiqueta,
                             tipo=None, facturas=None):
        """
        Genera un Excel. Si ya existe, pregunta: anexar, reemplazar u omitir.

        tipo: "PUE" o "PPD" (necesario para el anexado).
        facturas: lista de registros a escribir (necesario para el anexado).
        """
        if not ruta_xlsx.exists():
            try:
                generador(ruta_xlsx)
                msgs.append(f"✅ {etiqueta}: creado")
            except Exception as e:
                msgs.append(f"❌ {etiqueta}: {e}")
            return

        # El archivo ya existe → preguntar
        accion = _preguntar_accion_excel(self, ruta_xlsx.name)

        if accion == "omitir":
            msgs.append(f"⏭️ {etiqueta}: omitido")
            return

        if accion == "reemplazar":
            # Backup
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                nombre_backup = (
                    f"{ruta_xlsx.stem}_backup_{timestamp}{ruta_xlsx.suffix}"
                )
                ruta_backup = ruta_xlsx.parent / nombre_backup
                shutil.copy2(ruta_xlsx, ruta_backup)
            except Exception as e:
                msgs.append(f"⚠️ {etiqueta}: no se pudo crear backup ({e})")
                return

            # Borrar y regenerar
            try:
                ruta_xlsx.unlink()
                generador(ruta_xlsx)
                msgs.append(
                    f"✅ {etiqueta}: reordenado\n"
                    f"    Backup: {ruta_backup.name}"
                )
            except Exception as e:
                msgs.append(f"❌ {etiqueta}: {e}")
            return

        if accion == "anexar":
            if tipo is None or facturas is None:
                msgs.append(f"⚠️ {etiqueta}: no se puede anexar (faltan datos)")
                return

            try:
                from excel.egresos import anexar_facturas_al_excel
                nuevos, omitidos = anexar_facturas_al_excel(
                    ruta_xlsx, facturas, tipo,
                )
                msgs.append(
                    f"✅ {etiqueta}: {nuevos} anexadas, "
                    f"{omitidos} omitidas (ya existían)"
                )
            except Exception as e:
                msgs.append(f"❌ {etiqueta}: {e}")
            return


def _preguntar_accion_excel(parent, nombre_archivo):
    """Devuelve 'anexar', 'reemplazar' u 'omitir'."""
    ventana = ttk.Toplevel(parent)
    ventana.title("Archivo existente")

    # Subir al Toplevel padre si el parent es un Frame embebido
    toplevel_padre = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent
    try:
        ventana.transient(toplevel_padre)
    except Exception:
        pass
    try:
        ventana.grab_set()
    except Exception:
        pass

    ventana.resizable(False, False)

    ttk.Label(
        ventana,
        text=f"El archivo ya existe:\n{nombre_archivo}",
        font=("Segoe UI", 10, "bold"),
    ).pack(pady=(20, 5), padx=30)

    ttk.Label(
        ventana,
        text="¿Qué quieres hacer?",
        font=("Segoe UI", 9),
    ).pack(pady=(0, 15))

    resultado = {"accion": "omitir"}

    def _set(accion):
        resultado["accion"] = accion
        ventana.destroy()

    frame = ttk.Frame(ventana)
    frame.pack(pady=(0, 20), padx=20)

    ttk.Button(
        frame, text="📥 Anexar nuevas",
        command=lambda: _set("anexar"),
        bootstyle="success",
    ).pack(side="left", padx=5)

    ttk.Button(
        frame, text="🔄 Reemplazar todo",
        command=lambda: _set("reemplazar"),
        bootstyle="warning",
    ).pack(side="left", padx=5)

    ttk.Button(
        frame, text="Omitir",
        command=lambda: _set("omitir"),
        bootstyle="secondary",
    ).pack(side="left", padx=5)

    ventana.wait_window()
    return resultado["accion"]


# ================================================================
# Wrapper legacy: abre el panel dentro de un Toplevel independiente
# ================================================================

class AppEgresos(ttk.Toplevel):
    """
    Wrapper legacy: abre el panel dentro de una ventana independiente.
    Mantener mientras haya código que importe AppEgresos.
    """

    def __init__(self, master=None):
        super().__init__(master)
        self.title("Vet Suite — Egresos")
        self.geometry("1300x880")
        self.minsize(1050, 700)

        panel = PanelEgresos(self)
        panel.pack(fill="both", expand=True)


if __name__ == "__main__":
    import ttkbootstrap as ttk_local
    from config.temas import obtener_tema

    raiz = ttk_local.Window(themename=obtener_tema())
    raiz.withdraw()
    app = AppEgresos(master=raiz)
    app.protocol("WM_DELETE_WINDOW", raiz.destroy)
    raiz.mainloop()