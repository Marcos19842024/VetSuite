# -*- coding: utf-8 -*-
"""
dialogos/descargar_sat.py
Dialogo para elegir el periodo de descarga del SAT y ejecutar
el flujo completo (solicitar -> esperar -> descargar -> procesar).

Flujo:
  1. Pedir mes/año al usuario
  2. Solicitar descarga al SAT -> obtiene id_solicitud
  3. Abrir dialogos/espera_sat.py con el verificador correcto
  4. Cuando el SAT termina (estado=3), descargar paquetes y procesar

v2.4.1:
  - No se vuelve a solicitar si ya hay una solicitud vigente para el período.
  - Se persiste el estado del SAT en solicitud_sat_activa.json tras cada
    verificación, para que el botón del panel sepa qué mostrar.
  - La solicitud se limpia solo cuando el SAT la declara muerta (4/5) o
    cuando la descarga+procesamiento termina.
"""

import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
import ttkbootstrap as ttk

from tkinter import messagebox

from config.campos import MESES_ES


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

    # Valores por defecto: mes y año actuales
    hoy = datetime.now()
    mes_default = MESES_ES[hoy.month - 1]
    anio_default = str(hoy.year)

    ventana = ttk.Toplevel(app)
    ventana.title("📥 Descargar del SAT")
    configurar_ventana(app, ventana, ancho=450, alto=350,
                       min_ancho=400, min_alto=300)

    # Encabezado
    ttk.Label(
        ventana,
        text="📥 Descargar facturas del SAT",
        font=("Segoe UI", 15, "bold"),
    ).pack(pady=(20, 5))

    ttk.Label(
        ventana,
        text="Descarga los CFDI recibidos (facturas de compra)\n"
             "del periodo seleccionado.",
        font=("Segoe UI", 9),
        foreground="gray",
        justify="center",
    ).pack(pady=(0, 20))

    # Formulario
    form = ttk.Frame(ventana)
    form.pack(fill="x", padx=30, pady=10)

    ttk.Label(form, text="Año:").grid(
        row=0, column=0, sticky="e", padx=(0, 10), pady=8)
    var_anio = tk.StringVar(value=anio_default)
    ttk.Entry(form, textvariable=var_anio, width=8).grid(
        row=0, column=1, sticky="w", pady=8)

    ttk.Label(form, text="Mes:").grid(
        row=1, column=0, sticky="e", padx=(0, 10), pady=8)
    var_mes = tk.StringVar(value=mes_default)
    ttk.Combobox(
        form,
        textvariable=var_mes,
        values=MESES_ES,
        width=15,
        state="readonly",
    ).grid(row=1, column=1, sticky="w", pady=8)

    # Nota
    ttk.Label(
        ventana,
        text="⚠️ La descarga puede tardar varios minutos.\n"
             "El SAT procesa la solicitud en segundo plano.",
        font=("Segoe UI", 8),
        foreground="gray",
        justify="center",
    ).pack(pady=(15, 10))

    # Botón para configurar e.firma
    def _abrir_config():
        from dialogos.egresos_config import abrir_dialogo_config_egresos
        abrir_dialogo_config_egresos(app)

    resultado = {"ok": False}

    def _descargar():
        anio_txt = var_anio.get().strip()
        mes_nombre = var_mes.get()

        # Validaciones
        try:
            anio = int(anio_txt)
            if anio < 2020 or anio > 2100:
                raise ValueError()
        except ValueError:
            messagebox.showwarning(
                "Año inválido",
                "Ingresa un año válido (ej. 2026).",
                parent=ventana)
            return

        if mes_nombre not in MESES_ES:
            messagebox.showwarning(
                "Mes inválido",
                "Selecciona un mes válido.",
                parent=ventana)
            return

        mes_idx = MESES_ES.index(mes_nombre) + 1

        # ⚠️ VALIDAR CONFIG ANTES de cerrar la ventana
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

        # Ahora sí, cerrar y lanzar
        resultado["ok"] = True
        ventana.destroy()

        _lanzar_descarga(app, anio, mes_idx, mes_nombre)

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
def _lanzar_descarga(app, anio, mes_idx, mes_nombre):
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

    # ── NUEVO: ¿ya hay una solicitud vigente para este período? ──
    existente = cargar_solicitud_activa()
    if existente and existente.get("anio") == anio \
            and existente.get("mes_idx") == mes_idx:
        estado = str(existente.get("estado_solicitud", ""))

        if estado in ("1", "2"):
            messagebox.showinfo(
                "Solicitud en proceso",
                f"Ya tienes una solicitud vigente para {mes_nombre} {anio}.\n\n"
                "El SAT aún la está procesando. Usa '🔄 Verificar solicitud' "
                "en unos minutos.",
                parent=app)
            return

        if estado == "3":
            # Ya está lista: ir directo a verificar/descargar
            messagebox.showinfo(
                "Descarga pendiente",
                f"Ya hay una descarga lista para {mes_nombre} {anio}.\n\n"
                "Se abrirá la ventana para descargarla.",
                parent=app)
            verificar_solicitud_pendiente(app)
            return

        if estado == "4" or estado == "5":
            # Rechazada/vencida: podemos volver a solicitar
            limpiar_solicitud_activa()

        # Si estado == "" (JSON viejo sin campo): seguimos, la verificación
        # decidirá en el flujo de espera.
    # ──────────────────────────────────────────────────────────

    # Rango de fechas: del primer dia del mes al ultimo dia (23:59:59)
    # IMPORTANTE: el SAT NO acepta fechas futuras.
    from calendar import monthrange

    fecha_inicio = datetime(anio, mes_idx, 1, 0, 0, 0)

    ultimo_dia = monthrange(anio, mes_idx)[1]
    fecha_fin = datetime(anio, mes_idx, ultimo_dia, 23, 59, 59)

    # Si el mes es el actual, recortar a HOY (23:59:59)
    hoy = datetime.now()
    if anio == hoy.year and mes_idx == hoy.month:
        fecha_fin = hoy.replace(hour=23, minute=59, second=59)

    # Si el rango queda en el futuro, avisar
    if fecha_inicio > hoy:
        messagebox.showwarning(
            "Fechas invalidas",
            f"No se puede descargar {mes_nombre} {anio} porque aun no ha pasado.",
            parent=app)
        return

    from sat.descarga import solicitar_descarga

    # 1) Solicitar
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
        # El SAT rechazó la solicitud. Mostrar motivo real.
        cod = resultado.get("cod_estatus", "?")
        msg = resultado.get("mensaje", "Sin mensaje")

        # Traducir los códigos más comunes
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

    # Guardar la solicitud activa para poder retomarla.
    # NUEVO: se incluye estado_solicitud="1" para que el panel
    # muestre "Verificar" de inmediato.
    from config.config_egresos import guardar_solicitud_activa
    guardar_solicitud_activa({
        "id_solicitud": id_solicitud,
        "rfc": rfc,
        "anio": anio,
        "mes_idx": mes_idx,
        "mes_nombre": mes_nombre,
        "fecha_solicitud": datetime.now().isoformat(timespec="seconds"),
        "estado_solicitud": "1",
        "paquetes": [],
    })

    # 2) Abrir ventana de espera con el verificador
    from dialogos.espera_sat import abrir_ventana_espera_sat
    from sat.descarga import verificar_solicitud

    def _verificador():
        res = verificar_solicitud(cer, key, pwd, rfc, id_solicitud)
        _persistir_estado_sat(res)   # ← NUEVO
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

            # Descargar
            from core.rutas_egresos import CARPETA_DATOS
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

            # Limpiar la solicitud activa (ya terminó todo)
            from config.config_egresos import limpiar_solicitud_activa
            limpiar_solicitud_activa()

            # Mostrar resumen
            def _mostrar():
                messagebox.showinfo(
                    "Descarga completa",
                    f"✅ Descarga y procesamiento exitosos\n\n"
                    f"Facturas nuevas: {resumen['nuevas']}\n"
                    f"Duplicadas: {resumen['duplicadas']}\n"
                    f"XMLs movidos: {resumen['movidos']}\n\n"
                    f"Revisa los registros y usa '📊 Generar Excel'\n"
                    f"cuando termines.",
                    parent=app)
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
        _persistir_estado_sat(res)   # ← NUEVO
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