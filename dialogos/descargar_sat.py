# -*- coding: utf-8 -*-
"""
dialogos/descargar_sat.py
Dialogo para elegir el periodo de descarga del SAT y ejecutar
el flujo completo (solicitar -> esperar -> descargar -> procesar).

Flujo:
  1. Pedir fechas (desde/hasta) al usuario
  2. Solicitar descarga al SAT -> obtiene id_solicitud
  3. Abrir dialogos/espera_sat.py con el verificador correcto
  4. Cuando el SAT termina (estado=3), descargar paquetes y procesar

v3.1.0:
  - Fechas libres (DateEntry) en lugar de solo mes/año.
  - Validaciones: rango <= 365 días, inicio <= fin, no fechas futuras.
  - Atajos: "Mes actual" y "Mes anterior" rellenan el mes completo.
  - Se guarda fecha_inicio/fecha_fin en solicitud_sat_activa.json
    (compatible con anio/mes_idx para verificar_solicitud_pendiente).
  - Aviso si el rango cruza de mes (porque procesar_todo usa el mes
    del primer día).
"""

import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
import ttkbootstrap as ttk

from tkinter import messagebox

from config.campos import MESES_ES


# ============================================================
# HELPERS
# ============================================================
def _ultimo_dia(anio: int, mes: int) -> int:
    from calendar import monthrange
    return monthrange(anio, mes)[1]


# ============================================================
# DIALOGO DE SELECCION DE PERIODO
# ============================================================
def abrir_dialogo_descargar_sat(app):
    """
    Abre el dialogo de descarga del SAT.

    Parametros:
      - app: instancia de AppEgresos (o PanelEgresos).

    Devuelve True si se lanzo una descarga, False si se cancelo.
    """
    from ui.utils import configurar_ventana

    hoy = datetime.now()

    ventana = ttk.Toplevel(app.winfo_toplevel())
    ventana.title("📥 Descargar del SAT")
    configurar_ventana(app, ventana, ancho=480, alto=430,
                       min_ancho=430, min_alto=380)

    # Encabezado
    ttk.Label(
        ventana,
        text="📥 Descargar facturas del SAT",
        font=("Segoe UI", 15, "bold"),
    ).pack(pady=(20, 5))

    ttk.Label(
        ventana,
        text="Descarga los CFDI recibidos (facturas de compra)\n"
             "del rango de fechas seleccionado.",
        font=("Segoe UI", 9),
        foreground="gray",
        justify="center",
    ).pack(pady=(0, 15))

    try:
        from ttkbootstrap import DateEntry
        _usar_dateentry = True
    except ImportError:
        DateEntry = None
        _usar_dateentry = False

    # ---- Formulario ----
    form = ttk.Frame(ventana)
    form.pack(fill="x", padx=30, pady=5)

    ttk.Label(form, text="Desde:").grid(
        row=0, column=0, sticky="e", padx=(0, 10), pady=8)
    ttk.Label(form, text="Hasta:").grid(
        row=1, column=0, sticky="e", padx=(0, 10), pady=8)

    fecha_ini_default = datetime(hoy.year, hoy.month, 1)
    fecha_fin_default = hoy

    # ttkbootstrap.DateEntry: dateformat (no date_pattern), startdate (no year/month/day)
    entry_ini = ttk.DateEntry(
        form, width=14,
        dateformat="%Y-%m-%d",
        startdate=fecha_ini_default,
    )
    entry_fin = ttk.DateEntry(
        form, width=14,
        dateformat="%Y-%m-%d",
        startdate=fecha_fin_default,
    )
    entry_ini.grid(row=0, column=1, sticky="w", pady=8)
    entry_fin.grid(row=1, column=1, sticky="w", pady=8)

    # ---- Atajos ----
    atajos = ttk.Frame(ventana)
    atajos.pack(fill="x", padx=30, pady=(0, 10))

    def _set_fecha(entry: ttk.DateEntry, fecha: datetime):
        """ttkbootstrap.DateEntry no tiene set_date().
        Hay que reescribir el Entry interno."""
        entry.entry.delete(0, "end")
        entry.entry.insert(0, fecha.strftime("%Y-%m-%d"))

    def _get_fecha(entry: ttk.DateEntry) -> datetime:
        """ttkbootstrap.DateEntry no tiene get_date().
        Hay que leer el Entry interno y parsear."""
        texto = entry.entry.get().strip()
        if not texto:
            raise ValueError("Fecha vacía")
        return datetime.strptime(texto, "%Y-%m-%d")

    def _mes_completo(anio_m, mes_m):
        ultimo = _ultimo_dia(anio_m, mes_m)
        _set_fecha(entry_ini, datetime(anio_m, mes_m, 1))
        _set_fecha(entry_fin, datetime(anio_m, mes_m, ultimo, 23, 59, 59))

    ttk.Button(
        atajos, text="Mes actual",
        command=lambda: _mes_completo(hoy.year, hoy.month),
        bootstyle="secondary-outline",
    ).pack(side="left", padx=3)

    if hoy.month > 1:
        mes_ant = hoy.month - 1
        anio_ant = hoy.year
    else:
        mes_ant = 12
        anio_ant = hoy.year - 1

    ttk.Button(
        atajos, text=f"Mes anterior ({MESES_ES[mes_ant - 1]})",
        command=lambda: _mes_completo(anio_ant, mes_ant),
        bootstyle="secondary-outline",
    ).pack(side="left", padx=3)

    # ---- Nota ----
    ttk.Label(
        ventana,
        text="⚠️ La descarga puede tardar varios minutos.\n"
             "El SAT procesa la solicitud en segundo plano.",
        font=("Segoe UI", 8),
        foreground="gray",
        justify="center",
    ).pack(pady=(10, 10))

    # ---- Botón para configurar e.firma ----
    def _abrir_config():
        from dialogos.egresos_config import abrir_dialogo_config_egresos
        abrir_dialogo_config_egresos(app)

    resultado = {"ok": False}

    def _descargar():
        try:
            ini = _get_fecha(entry_ini)
            fin = _get_fecha(entry_fin)
            fecha_inicio = datetime(ini.year, ini.month, ini.day, 0, 0, 0)
            fecha_fin = datetime(fin.year, fin.month, fin.day, 23, 59, 59)
        except ValueError as e:
            messagebox.showwarning(
                "Fecha inválida",
                f"Usa el formato YYYY-MM-DD (ej. 2026-08-01).\n\n{e}",
                parent=ventana)
            return

        # Validaciones
        if fecha_fin < fecha_inicio:
            messagebox.showwarning(
                "Rango inválido",
                "La fecha 'Hasta' no puede ser menor que 'Desde'.",
                parent=ventana)
            return

        if (fecha_fin - fecha_inicio).days > 365:
            messagebox.showwarning(
                "Rango demasiado largo",
                "El SAT no acepta rangos mayores a 1 año.",
                parent=ventana)
            return

        hoy_dt = datetime.now()
        if fecha_inicio > hoy_dt:
            messagebox.showwarning(
                "Fecha futura",
                "No puedes solicitar fechas futuras.",
                parent=ventana)
            return

        if fecha_fin > hoy_dt:
            fecha_fin = hoy_dt.replace(hour=23, minute=59, second=59)

        # Aviso si cruza de mes
        if fecha_inicio.month != fecha_fin.month or \
                fecha_inicio.year != fecha_fin.year:
            if not messagebox.askyesno(
                "El rango cruza de mes",
                "El rango seleccionado cruza de mes.\n\n"
                "Las facturas se procesarán con el mes del primer día "
                f"({MESES_ES[fecha_inicio.month - 1]} {fecha_inicio.year}).\n\n"
                "¿Continuar?",
                parent=ventana):
                return

        # Validar config ANTES de cerrar
        from config.config_egresos import cargar_config_egresos
        cfg = cargar_config_egresos()
        rfc = cfg.get("rfc_receptor", "")
        cer = cfg.get("certificado_cer", "")
        key = cfg.get("certificado_key", "")
        pwd = cfg.get("password_fiel", "")

        if not all([rfc, cer, key, pwd]):
            messagebox.showwarning(
                "Configuración incompleta",
                "Falta configurar la e.firma.\n\n"
                "Ve a ⚙️ Configurar e.firma (SAT) primero.",
                parent=ventana)
            return

        resultado["ok"] = True
        ventana.destroy()

        _lanzar_descarga(app, fecha_inicio, fecha_fin)

    def _cancelar():
        ventana.destroy()

    fr_btn = ttk.Frame(ventana)
    fr_btn.pack(fill="x", padx=30, pady=(10, 20))

    ttk.Button(
        fr_btn,
        text="⚙️ Configurar e.firma (SAT)",
        command=_abrir_config,
        bootstyle="secondary-outline",
    ).pack(side="left", padx=5)

    ttk.Button(
        fr_btn,
        text="📥 Descargar",
        command=_descargar,
        bootstyle="info-outline",
    ).pack(side="right", padx=5)

    ventana.protocol("WM_DELETE_WINDOW", _cancelar)
    ventana.bind("<Escape>", lambda e: _cancelar())

    ventana.wait_window()
    return resultado["ok"]


# ============================================================
# PERSISTENCIA DEL ESTADO DEL SAT
# ============================================================
def _persistir_estado_sat(resultado_verif):
    """
    Actualiza solicitud_sat_activa.json con el estado devuelto
    por VerificaSolicitudDescarga. Se llama después de cada
    verificación para que _actualizar_boton_sat() del panel
    sepa qué mostrar.
    """
    from config.config_egresos import (
        cargar_solicitud_activa,
        guardar_solicitud_activa,
    )
    datos = cargar_solicitud_activa() or {}
    datos.update({
        "estado_solicitud": str(resultado_verif.get("estado_solicitud", "")),
        "codigo_estado_solicitud": str(
            resultado_verif.get("codigo_estado_solicitud", "")
        ),
        "numero_cfdis": resultado_verif.get("numero_cfdis"),
        "paquetes": resultado_verif.get("paquetes", []),
        "ultima_verificacion": datetime.now().isoformat(timespec="seconds"),
    })
    guardar_solicitud_activa(datos)


# ============================================================
# LANZAR DESCARGA (solicitar -> esperar -> descargar -> procesar)
# ============================================================
def _lanzar_descarga(app, fecha_inicio: datetime, fecha_fin: datetime):
    """Ejecuta el flujo de descarga en un hilo separado."""
    from config.config_egresos import (
        cargar_config_egresos,
        cargar_solicitud_activa,
        limpiar_solicitud_activa,
    )

    cfg = cargar_config_egresos()
    rfc = cfg.get("rfc_receptor", "")
    cer = cfg.get("certificado_cer", "")
    key = cfg.get("certificado_key", "")
    pwd = cfg.get("password_fiel", "")

    # ── ¿Ya hay una solicitud vigente para el mismo rango? ──
    existente = cargar_solicitud_activa()
    if existente:
        ini_guardada = existente.get("fecha_inicio")
        fin_guardada = existente.get("fecha_fin")
        ini_nueva = fecha_inicio.date().isoformat()
        fin_nueva = fecha_fin.date().isoformat()

        mismo_rango = (ini_guardada == ini_nueva and fin_guardada == fin_nueva)

        # Compatibilidad con formato viejo (solo anio/mes_idx)
        mismo_mes_viejo = False
        if existente.get("anio") == fecha_inicio.year \
                and existente.get("mes_idx") == fecha_inicio.month:
            if (ini_nueva.endswith("-01")
                    and fin_nueva == f"{fecha_inicio.year}-"
                                    f"{fecha_inicio.month:02d}-"
                                    f"{_ultimo_dia(fecha_inicio.year, fecha_inicio.month):02d}"):
                mismo_mes_viejo = True

        if mismo_rango or mismo_mes_viejo:
            estado = str(existente.get("estado_solicitud", ""))

            if estado in ("1", "2"):
                messagebox.showinfo(
                    "Solicitud en proceso",
                    "Ya tienes una solicitud vigente para este período.\n\n"
                    "El SAT aún la está procesando. Usa '🔄 Verificar solicitud' "
                    "en unos minutos.",
                    parent=app)
                return

            if estado == "3":
                messagebox.showinfo(
                    "Descarga pendiente",
                    "Ya hay una descarga lista para este período.\n\n"
                    "Se abrirá la ventana para descargarla.",
                    parent=app)
                verificar_solicitud_pendiente(app)
                return

            if estado in ("4", "5"):
                limpiar_solicitud_activa()

    # ── Solicitar ──
    from sat.descarga import solicitar_descarga

    try:
        resultado = solicitar_descarga(
            cer, key, pwd, rfc,
            fecha_inicio, fecha_fin,
        )
    except Exception as e:
        messagebox.showerror(
            "Error al solicitar descarga",
            f"No se pudo solicitar la descarga:\n\n{e}",
            parent=app)
        return

    id_solicitud = resultado.get("id_solicitud")
    if not id_solicitud:
        cod = resultado.get("cod_estatus", "?")
        msg = resultado.get("mensaje", "Sin mensaje")

        traduccion = {
            "301": "XML mal formado (revisa fechas o RFC)",
            "302": "RFC no válido o sin permisos",
            "303": "Certificado no válido",
            "304": "Ya existe una solicitud en proceso para este periodo",
            "305": "Rango de fechas inválido",
            "306": "Sin información para ese periodo",
            "404": "No se encontró la solicitud",
            "5000": "OK",
            "5002": "Solicitudes agotadas para este periodo",
            "5005": "Ya existe una solicitud vigente para este periodo",
        }
        explicacion = traduccion.get(str(cod), "Error desconocido")

        messagebox.showerror(
            "Solicitud rechazada por el SAT",
            f"El SAT rechazó la solicitud.\n\n"
            f"Código: {cod}\n"
            f"Motivo: {explicacion}\n\n"
            f"Mensaje del SAT:\n{msg}",
            parent=app)
        return

    # ── Guardar la solicitud activa ──
    from config.config_egresos import guardar_solicitud_activa
    guardar_solicitud_activa({
        "id_solicitud": id_solicitud,
        "rfc": rfc,
        "fecha_inicio": fecha_inicio.date().isoformat(),
        "fecha_fin": fecha_fin.date().isoformat(),
        # Compatibilidad con verificar_solicitud_pendiente
        "anio": fecha_inicio.year,
        "mes_idx": fecha_inicio.month,
        "mes_nombre": MESES_ES[fecha_inicio.month - 1],
        "fecha_solicitud": datetime.now().isoformat(timespec="seconds"),
        "estado_solicitud": "1",
        "paquetes": [],
    })

    # ── Abrir ventana de espera ──
    from dialogos.espera_sat import abrir_ventana_espera_sat
    from sat.descarga import verificar_solicitud

    anio = fecha_inicio.year
    mes_idx = fecha_inicio.month

    def _verificador():
        res = verificar_solicitud(cer, key, pwd, rfc, id_solicitud)
        _persistir_estado_sat(res)
        return res

    def _on_completado(resultado_verif):
        paquetes = resultado_verif.get("paquetes", [])
        _descargar_y_procesar(
            app, cer, key, pwd, rfc, paquetes, anio, mes_idx,
            id_solicitud=id_solicitud,
        )

    abrir_ventana_espera_sat(app, _verificador, on_completado=_on_completado)


# ============================================================
# DESCARGA + PROCESAMIENTO
# ============================================================
def _descargar_y_procesar(app, cer, key, pwd, rfc, paquetes, anio, mes_idx,
                          id_solicitud=None):
    """Descarga paquetes y procesa todo. Se ejecuta en hilo."""
    def _worker():
        try:
            from sat.descarga import descargar_paquetes
            from core.rutas_egresos import CARPETA_DATOS

            # Descargar
            carpeta_destino = str(Path(CARPETA_DATOS) / "descargas")
            Path(carpeta_destino).mkdir(parents=True, exist_ok=True)

            descargar_paquetes(
                cer, key, pwd, rfc, paquetes,
                carpeta_destino=carpeta_destino,
                id_solicitud=id_solicitud,
            )

            # Procesar todo
            from sat.procesar_completo import procesar_todo
            resumen = procesar_todo(anio, mes_idx, carpeta_xml=carpeta_destino)

            # Cerrar snapshot del historial
            if id_solicitud:
                from core import sat_historial
                sat_historial.cerrar_snapshot(
                    id_solicitud=id_solicitud,
                    estado_final="terminada",
                    num_xmls=resumen.get("nuevas", 0) + resumen.get("duplicadas", 0),
                )

            # Limpiar la solicitud activa
            from config.config_egresos import limpiar_solicitud_activa
            limpiar_solicitud_activa()

            # Mostrar resumen
            def _mostrar():
                msg = (
                    f"✅ Descarga y procesamiento exitosos\n\n"
                    f"Facturas nuevas: {resumen['nuevas']}\n"
                    f"Duplicadas: {resumen['duplicadas']}\n"
                    f"XMLs movidos: {resumen['movidos']}\n"
                )
                descartados = resumen.get("descartados", 0)
                if descartados > 0:
                    msg += f"\n⚠ Descartados (no se movieron): {descartados}\n"
                    carpeta_desc = resumen.get("carpeta_descartados")
                    if carpeta_desc:
                        msg += f"   Guardados en:\n   {carpeta_desc}\n"
                    msg += (
                        "\nRevisa esa carpeta antes de borrarla: "
                        "puede haber facturas que necesites registrar a mano."
                    )
                msg += (
                    f"\n\nRevisa los registros y usa '📊 Generar Excel'\n"
                    f"cuando termines."
                )
                messagebox.showinfo("Descarga completa", msg, parent=app)
            app.after(0, _mostrar)

        except Exception as e:
            err = str(e)
            def _mostrar_error():
                messagebox.showerror(
                    "Error en descarga/procesamiento",
                    f"{err}",
                    parent=app)
            app.after(0, _mostrar_error)

    threading.Thread(target=_worker, daemon=True).start()


# ============================================================
# VERIFICAR SOLICITUD PENDIENTE (retomar)
# ============================================================
def verificar_solicitud_pendiente(app):
    """
    Retoma una solicitud que quedó en curso.
    - Lee el id_solicitud guardado
    - Abre la ventana de espera
    - Cuando termina, descarga y procesa, y limpia la solicitud
    """
    from config.config_egresos import (
        cargar_solicitud_activa,
        cargar_config_egresos,
    )

    datos = cargar_solicitud_activa()
    if not datos:
        messagebox.showinfo(
            "Sin solicitudes",
            "No hay ninguna solicitud pendiente.",
            parent=app)
        return

    cfg = cargar_config_egresos()
    rfc = cfg.get("rfc_receptor", "")
    cer = cfg.get("certificado_cer", "")
    key = cfg.get("certificado_key", "")
    pwd = cfg.get("password_fiel", "")

    if not all([rfc, cer, key, pwd]):
        messagebox.showwarning(
            "Configuración incompleta",
            "Falta configurar la e.firma.\n\n"
            "Ve a ⚙️ Configuración SAT primero.",
            parent=app)
        return

    id_solicitud = datos.get("id_solicitud", "")
    anio = datos.get("anio", 0)
    mes_idx = datos.get("mes_idx", 1)

    if not id_solicitud:
        messagebox.showerror(
            "Solicitud inválida",
            "El archivo de solicitud no tiene id_solicitud.",
            parent=app)
        return

    # Abrir ventana de espera
    from dialogos.espera_sat import abrir_ventana_espera_sat
    from sat.descarga import verificar_solicitud

    def _verificador():
        res = verificar_solicitud(cer, key, pwd, rfc, id_solicitud)
        _persistir_estado_sat(res)
        return res

    def _on_completado(resultado_verif):
        paquetes = resultado_verif.get("paquetes", [])
        _descargar_y_procesar(
            app, cer, key, pwd, rfc, paquetes, anio, mes_idx,
            id_solicitud=id_solicitud,
        )
        from config.config_egresos import limpiar_solicitud_activa
        limpiar_solicitud_activa()

    abrir_ventana_espera_sat(app, _verificador, on_completado=_on_completado)