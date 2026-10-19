# -*- coding: utf-8 -*-
"""
dialogos/sincronizar.py
Flujo completo de sincronización con Gmail:
  - Descarga adjuntos del correo.
  - Agrupa por factura.
  - Procesa automáticamente.
  - Guarda registros y adjuntos.

Este módulo recibe la instancia de AppIngresos como `app` y accede a:
  - app.registros, app._anio_cargado
  - app.entradas
  - app._llenar_desde_factura()
  - app._guardar_silencioso()
  - app._refrescar_tabla(), app._nuevo()
"""

import tkinter as tk
import ttkbootstrap as ttk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime

from config.config_ingresos import cargar_config_correo
from core.rutas import _CARPETA_DATOS
from core.persistencia import cargar_db, existe_valor_unico
from modulos.lector_facturas import procesar_factura


def sincronizar_facturas(app):
    """
    Flujo unificado: descarga facturas del correo y pregunta al usuario
    qué hacer con ellas.
    Ofrece la opción de editar la configuración si hay errores.
    """
    from modulos.correo_facturas import descargar_adjuntos_gmail
    from dialogos.gmail_config import pedir_credenciales_correo
    from dialogos.sincronizar_preguntas import (
        preguntar_modo_descarga,
        preguntar_accion_facturas,
    )
    from core.correo_utils import agrupar_facturas_descargadas

    # ---- Bucle: permite reintentar tras editar credenciales ----
    while True:
        # ---- 1. Verificar/obtener configuración ----
        cfg_correo = cargar_config_correo()
        usuario = cfg_correo.get("usuario", "")
        password = cfg_correo.get("password_app", "")
        etiqueta = cfg_correo.get("etiqueta", "FACTURAS BAALAK")
        filtro_remitente = cfg_correo.get("filtro_remitente", "")
        dias_atras = cfg_correo.get("dias_atras", 30)

        # Si no hay configuración, pedirla
        if not usuario or not password:
            usuario, password, etiqueta = pedir_credenciales_correo(app)
            if not usuario:
                return
            cfg_correo = cargar_config_correo()
            filtro_remitente = cfg_correo.get("filtro_remitente", "")
            dias_atras = cfg_correo.get("dias_atras", 30)

        # ---- 2. Preguntar modo ----
        modo = preguntar_modo_descarga(app, dias_atras)
        if modo == "cancelar":
            return
        elif modo == "editar":
            u, p, e = pedir_credenciales_correo(app)
            if u:
                messagebox.showinfo(
                    "Configuración actualizada",
                    f"✅ Datos guardados correctamente\n\n"
                    f"📧 Correo: {u or '(vacío)'}\n"
                    f"🏷️ Etiqueta: {e or '(vacía)'}\n\n"
                    f"Continuando con la sincronización..."
                )
            continue
        else:
            solo_no_leidos = (modo == "no_leidos")
            break

    # ---- 3. Ventana de progreso ----
    ventana_prog = ttk.Toplevel(app)
    ventana_prog.title("⚡ Sincronizando facturas...")
    ventana_prog.geometry("900x700")
    ventana_prog.minsize(700, 500)
    ventana_prog.transient(app)
    ventana_prog.resizable(True, True)

    # Bloquear la ventana padre mientras esta activa
    try:
        ventana_prog.grab_set()
    except Exception:
        pass

    # ---- Estado de cancelación ----
    estado = {"cancelar": False}

    def _al_intentar_cerrar():
        if estado["cancelar"]:
            # Ya se pidió cancelar antes, forzar cierre
            try:
                ventana_prog.destroy()
            except Exception:
                pass
            return

        respuesta = messagebox.askyesno(
            "Cancelar descarga",
            "La descarga está en curso.\n\n"
            "¿Quieres cancelarla y cerrar la ventana?\n\n"
            "Los correos ya descargados quedarán guardados.\n"
            "El proceso se detendrá en el próximo correo.",
            parent=ventana_prog
        )
        if respuesta:
            estado["cancelar"] = True
            try:
                barra_progreso.stop()
                lbl_progreso.configure(text="⚠️ Cancelando... cerrando en 3 segundos")
            except Exception:
                pass
            # Forzar cierre tras 3 segundos (por si el hilo tarda)
            ventana_prog.after(3000, lambda: _forzar_cierre())

    def _forzar_cierre():
        """Fuerza el cierre de la ventana (por si el hilo sigue corriendo)."""
        try:
            estado["cancelar"] = True
        except Exception:
            pass
        try:
            ventana_prog.destroy()
        except Exception:
            pass

    ventana_prog.protocol("WM_DELETE_WINDOW", _al_intentar_cerrar)

    def debe_cancelar():
        return estado["cancelar"]

    # Centrar la ventana
    ventana_prog.update_idletasks()
    x = (ventana_prog.winfo_screenwidth() - 900) // 2
    y = (ventana_prog.winfo_screenheight() - 700) // 2
    ventana_prog.geometry(f"900x700+{x}+{y}")

    # ---- Título ----
    ttk.Label(ventana_prog,
              text="⚡ Sincronizando facturas del correo",
              font=("Segoe UI", 12, "bold")).pack(pady=(10, 5))

    # ---- Contador grande de progreso ----
    lbl_progreso = ttk.Label(
        ventana_prog,
        text="⏳ Preparando...",
        font=("Segoe UI", 11),
        bootstyle="info"
    )
    lbl_progreso.pack(pady=5)

    # ---- Barra de progreso indeterminada ----
    barra_progreso = ttk.Progressbar(
        ventana_prog,
        mode="indeterminate",
        bootstyle="info-striped",
        length=600
    )
    barra_progreso.pack(pady=5, padx=20, fill="x")
    barra_progreso.start(15)

    # ---- Log ----
    frame_log = ttk.LabelFrame(ventana_prog, text="Detalle", padding=5)
    frame_log.pack(fill="both", expand=True, padx=10, pady=5)

    txt_log = tk.Text(frame_log, height=22, width=100,
                      font=("Consolas", 9), wrap="word")
    txt_log.pack(fill="both", expand=True, side="left")

    sb = ttk.Scrollbar(frame_log, orient="vertical", command=txt_log.yview)
    sb.pack(side="right", fill="y")
    txt_log.configure(yscrollcommand=sb.set)

    def log(msg):
        txt_log.insert(tk.END, msg + "\n")
        txt_log.see(tk.END)
        try:
            ventana_prog.update()
        except Exception:
            pass

    def actualizar_progreso(texto):
        try:
            lbl_progreso.configure(text=texto)
            ventana_prog.update()
        except Exception:
            pass

    # ---- 4. Descargar del correo ----
    log("=" * 80)
    log("PASO 1: Descargando adjuntos del correo")
    log("=" * 80)

    carpeta_descargas = _CARPETA_DATOS / "descargas"
    if carpeta_descargas.exists():
        for f in carpeta_descargas.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass

    try:
        barra_progreso.stop()
        barra_progreso.configure(mode="determinate")
        barra_progreso["value"] = 100
    except Exception:
        pass

    descargados, errores, info = descargar_adjuntos_gmail(
        usuario=usuario,
        password_app=password,
        etiqueta=etiqueta,
        carpeta_destino=carpeta_descargas,
        solo_no_leidos=solo_no_leidos,
        filtro_remitente=filtro_remitente if filtro_remitente else None,
        dias_atras=dias_atras if dias_atras else None,
        usar_cache=True,
        callback_log=log,
        callback_progreso=actualizar_progreso,
        callback_cancelado=debe_cancelar,
    )

    # ---- 5. Verificar errores de autenticación ----
    if errores and any("AUTHENTICATIONFAILED" in str(e).upper() or
                        "LOGIN" in str(e).upper() or
                        "IMAP" in str(e).upper() or
                        "authentication" in str(e).lower()
                        for e in errores):
        log("\n" + "=" * 80)
        log("❌ ERROR DE AUTENTICACIÓN")
        log("=" * 80)
        log("Los datos de conexión al correo son incorrectos.")
        log("\nRevisa la configuración.")

        ventana_prog.update_idletasks()

        editar = messagebox.askyesno(
            "Error de autenticación",
            "No se pudo conectar al correo.\n\n"
            "Los datos de conexión son incorrectos (usuario, contraseña "
            "de aplicación, o etiqueta).\n\n"
            "¿Quieres editar la configuración ahora?"
        )
        if editar:
            u, p, e = pedir_credenciales_correo(app)
            if u:
                messagebox.showinfo(
                    "Configuración actualizada",
                    "Datos guardados correctamente.\n\n"
                    "Vuelve a intentar con ⚡ Sincronizar."
                )
        return

    log(f"\n📊 Resumen de descarga:")
    log(f"   Correos encontrados: {info.get('total_correos', 0)}")
    log(f"   Correos procesados:  {info.get('procesados', 0)}")
    log(f"   Omitidos por caché:  {info.get('omitidos_cache', 0)}")
    log(f"   Omitidos por filtro: {info.get('omitidos_filtros', 0)}")
    log(f"   Archivos descargados: {len(descargados)}")
    log(f"   Log completo: {info.get('log', '')}")

    # ---- Si el usuario canceló, salir limpiamente ----
    if estado["cancelar"]:
        log("\n" + "=" * 80)
        log("⚠️ DESCARGA CANCELADA POR EL USUARIO")
        log("=" * 80)
        log(f"Se descargaron {len(descargados)} archivos antes de cancelar.")
        if descargados:
            log(f"Los archivos están en: {carpeta_descargas}")
            log("Puedes procesarlos con '📥 Leer factura' cuando quieras.")
        ventana_prog.protocol("WM_DELETE_WINDOW",
            lambda: ventana_prog.destroy())
        return

    if not descargados:
        log("\n⚠️ No se descargó ningún archivo nuevo.")
        if errores:
            log("Errores:")
            for e in errores:
                log(f"  • {e}")
        ventana_prog.protocol("WM_DELETE_WINDOW",
            lambda: ventana_prog.destroy())
        return

    # ---- 6. Agrupar por No. de factura ----
    log("\n" + "=" * 80)
    log("PASO 2: Agrupando por No. de factura")
    log("=" * 80)

    archivos_por_correo = info.get("archivos_por_correo", {})
    grupos = agrupar_facturas_descargadas(
        carpeta_descargas,
        archivos_por_correo=archivos_por_correo
    )
    log(f"Facturas únicas detectadas: {len(grupos)}")

    # ---- 7. Preguntar qué hacer ----
    ventana_prog.grab_release()
    respuesta_procesar = preguntar_accion_facturas(
        app, len(descargados), len(grupos), carpeta_descargas
    )
    ventana_prog.grab_set()

    if respuesta_procesar == "cancelar":
        log("\n⏸️ Los archivos quedan en disco. Puedes procesarlos con '📥 Leer factura'.")
        log(f"   Carpeta: {carpeta_descargas}")
        return

    if respuesta_procesar == "solo_guardar":
        log("\n📁 Archivos guardados (sin procesar).")
        log(f"   Carpeta: {carpeta_descargas}")
        messagebox.showinfo(
            "Archivos descargados",
            f"Se descargaron {len(descargados)} archivos.\n\n"
            f"Carpeta: {carpeta_descargas}\n\n"
            "Puedes procesarlos con '📥 Leer factura'."
        )
        return

    # Preparar la barra para mostrar progreso de procesamiento
    try:
        barra_progreso.configure(mode="determinate", maximum=len(grupos))
        barra_progreso["value"] = 0
    except Exception:
        pass

    # ---- 8. Procesar todas automáticamente ----
    log("\n" + "=" * 80)
    log("PASO 3: Procesando facturas")
    log("=" * 80)

    uuids_existentes = set()
    for r in app.registros:
        ff = str(r.get("folio_fiscal", "")).strip()
        if ff:
            uuids_existentes.add(ff)

    facturas_procesadas = []
    facturas_duplicadas = []
    facturas_sin_xml = []
    facturas_con_error = []
    todos_avisos = []          # ← Acumular avisos de reclasificación
    vistos_avisos = set()      # ← Para deduplicar mientras se procesan
    todos_no_catalogados = []  # ← NUEVO: acumular productos no catalogados
    vistos_no_cat = set()      # ← NUEVO: para deduplicar

    def _orden_grupo(item):
        clave = item[0]
        try:
            return int(str(clave).replace("grupo_", ""))
        except Exception:
            return 0

    todos_avisos = []
    todos_no_catalogados = []
    for i, (_, files) in enumerate(sorted(grupos.items(), key=_orden_grupo), 1):
        no_factura = files.get("no_factura", "?")
        log(f"\n[{i}/{len(grupos)}] Procesando factura {no_factura}...")
        try:
            barra_progreso["value"] = i
            lbl_progreso.configure(
                text=f"⚙️ Procesando factura {i} de {len(grupos)}: {no_factura}"
            )
            ventana_prog.update()
        except Exception:
            pass

        if not files["xml"]:
            log(f"  ⚠️ No hay XML. Se omite.")
            facturas_sin_xml.append(no_factura)
            continue

        try:
            datos = procesar_factura(
                str(files["xml"]),
                str(files["pdf"]) if files["pdf"] else None
            )

            if existe_valor_unico(app.registros, "no_factura",
                                   datos["no_factura"]):
                log(f"  ⏭️ Ya existe No. de Factura {datos['no_factura']}. Se omite.")
                facturas_duplicadas.append(datos["no_factura"])
                continue

            ff = str(datos.get("folio_fiscal", "")).strip()
            if ff and ff in uuids_existentes:
                log(f"  ⏭️ Ya existe Folio Fiscal {ff[:8]}... Se omite.")
                facturas_duplicadas.append(datos["no_factura"])
                continue

            try:
                anio_factura = int(datos.get("anio", app._anio_cargado))
            except Exception:
                anio_factura = app._anio_cargado

            if anio_factura != app._anio_cargado:
                regs_anio = cargar_db(anio_factura)
            else:
                regs_anio = app.registros

            if existe_valor_unico(regs_anio, "no_factura", datos["no_factura"]):
                log(f"  ⏭️ Ya existe (en año {anio_factura}). Se omite.")
                facturas_duplicadas.append(datos["no_factura"])
                continue

            _, datos_completos, avisos_reclasificacion, no_catalogados = \
                app._llenar_desde_factura(datos)

            # Avisos de reclasificación (VACUNA/CLINICA con IVA, etc.)
            if avisos_reclasificacion:
                for a in avisos_reclasificacion:
                    clave = (a["categoria_actual"], a["producto"].strip().upper())
                    if clave in vistos_avisos:
                        continue
                    vistos_avisos.add(clave)
                    todos_avisos.append(a)
                    log(f"  ⚠️ Reclasificar: [{a['categoria_actual']}] {a['producto']}")

            # Productos no catalogados (nuevos)
            if no_catalogados:
                for n in no_catalogados:
                    clave = ("U", n["producto"].strip().upper())
                    if clave in vistos_no_cat:
                        continue
                    vistos_no_cat.add(clave)
                    todos_no_catalogados.append(n)
                    log(f"  🆕 No catalogado: {n['producto']} "
                        f"(rem {n['remision']})")

            # ============================================================
            # QVET y No. factura: leerlos del asunto del correo
            # ============================================================
            qvet_por_archivo = info.get("qvet_por_archivo", {})
            no_factura_por_archivo = info.get("no_factura_por_archivo", {})
            nombre_xml = Path(files["xml"]).name

            qvet_final = qvet_por_archivo.get(nombre_xml, "")
            no_factura_final = no_factura_por_archivo.get(nombre_xml, "")

            if qvet_final:
                log(f"  🔖 QVET del asunto: {qvet_final}")
            else:
                serie_xml = (datos.get("serie") or "").strip()
                folio_xml = (datos.get("folio") or "").strip()
                if serie_xml and folio_xml:
                    qvet_final = f"{serie_xml}/{folio_xml}".upper()
                log(f"  ⚠️ QVET no encontrado en asunto, usando XML: {qvet_final}")

            if no_factura_final:
                log(f"  🔖 No. factura del asunto: {no_factura_final}")
            else:
                no_factura_final = datos.get("no_factura", "")
                log(f"  ⚠️ No. factura no encontrado en asunto, usando XML: {no_factura_final}")

            # Ya no hay formulario: solo actualizamos el dict
            if qvet_final:
                datos_completos["qvet"] = qvet_final

            if no_factura_final:
                datos_completos["no_factura"] = no_factura_final

            app._ultima_factura_xml = str(files["xml"])
            app._ultima_factura_pdf = str(files["pdf"]) if files["pdf"] else None

            app._guardar_silencioso(datos_completos)

            if ff:
                uuids_existentes.add(ff)

            log(f"  ✅ Guardado: No. {datos['no_factura']} | "
                f"QVET {qvet_final or '(vacío)'} | "
                f"{datos.get('centro', '?')} | "
                f"{datos.get('mes', '?')} {datos.get('anio', '?')} | "
                f"Total: ${datos['total']:,.2f}")
            facturas_procesadas.append(datos)

        except Exception as e:
            log(f"  ❌ Error: {e}")
            facturas_con_error.append((no_factura, str(e)))

    app._refrescar_tabla()

    # ---- 9. Resumen final ----
    log("\n" + "=" * 80)
    log("RESUMEN FINAL")
    log("=" * 80)
    log(f"✅ Facturas guardadas:  {len(facturas_procesadas)}")
    log(f"⏭️ Facturas duplicadas: {len(facturas_duplicadas)}")
    log(f"⚠️ Facturas sin XML:    {len(facturas_sin_xml)}")
    log(f"❌ Facturas con error:  {len(facturas_con_error)}")

    if facturas_procesadas:
        total_procesado = sum(f.get("total", 0) for f in facturas_procesadas)
        log(f"\n💰 Total procesado: ${total_procesado:,.2f}")

        from collections import defaultdict
        resumen = defaultdict(lambda: {"n": 0, "total": 0.0})
        for f in facturas_procesadas:
            key = (f.get("centro", "?"),
                   f.get("mes", "?"),
                   f.get("anio", "?"))
            resumen[key]["n"] += 1
            resumen[key]["total"] += f.get("total", 0)

        log("\n📊 Desglose:")
        for (centro, mes, anio), data in sorted(resumen.items()):
            log(f"   • {centro:<10} {mes:<12} {anio}   "
                f"{data['n']:>3} facturas   ${data['total']:>12,.2f}")

    if facturas_duplicadas:
        log(f"\n⏭️ Facturas duplicadas (omitidas):")
        for nf in facturas_duplicadas:
            log(f"   • {nf}")

    if facturas_sin_xml:
        log(f"\n⚠️ Facturas sin XML:")
        for nf in facturas_sin_xml:
            log(f"   • {nf}")

    if facturas_con_error:
        log(f"\n❌ Errores:")
        for nf, err in facturas_con_error:
            log(f"   • {nf}: {err}")

    log(f"\n📄 Log completo guardado en: {info.get('log', '')}")

    # ---- Ofrecer registrar en el catálogo (reclasificaciones + no catalogados) ----
    total_nuevos = len(todos_no_catalogados)
    total_reclasif = len(todos_avisos)
    hay_pendientes = total_nuevos > 0 or total_reclasif > 0

    mensaje_base = (
        f"✅ {len(facturas_procesadas)} facturas guardadas\n"
        f"⏭️ {len(facturas_duplicadas)} duplicadas\n"
        f"⚠️ {len(facturas_sin_xml)} sin XML\n"
        f"❌ {len(facturas_con_error)} con error"
    )

    if hay_pendientes:
        lineas_extra = []
        if total_nuevos:
            lineas_extra.append(
                f"🆕 {total_nuevos} producto(s) nuevo(s)"
            )
        if total_reclasif:
            lineas_extra.append(
                f"🏷️ {total_reclasif} producto(s) para reclasificar"
            )
        mensaje_avisos = (
            "\n\nSe detectaron:\n  " +
            "\n  ".join(lineas_extra) +
            "\n\n¿Quieres registrarlos en el catálogo ahora?\n"
            "(También puedes hacerlo después desde 🏷️ Reclasificar)"
        )

        respuesta = messagebox.askyesno(
            "Sincronización completa",
            mensaje_base + mensaje_avisos
        )
        if respuesta:
            # UNA SOLA VENTANA con ambos tipos
            todos_pendientes = list(todos_no_catalogados) + list(todos_avisos)
            from dialogos.registrar_productos import (
                abrir_dialogo_registrar_productos
            )
            abrir_dialogo_registrar_productos(app, todos_pendientes)
    else:
        messagebox.showinfo(
            "Sincronización completa",
            mensaje_base + f"\n\nLog: {info.get('log', '')}"
        )

    # Liberar el grab al terminar normalmente
    try:
        ventana_prog.grab_release()
    except Exception:
        pass

    try:
        ventana_prog.protocol("WM_DELETE_WINDOW", ventana_prog.destroy)
    except Exception:
        pass