import os
import re
import sys
import json
import imaplib
import email
from email.header import decode_header
from pathlib import Path
from datetime import datetime, timedelta

# Importar la carpeta de datos desde core.rutas (fuente de verdad)
from core.rutas import _CARPETA_DATOS


# ============================================================
# CONFIGURACIÓN
# ============================================================
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993


def _carpeta_datos():
    """
    Devuelve la carpeta de datos de Ingresos.
    Delegado a core.rutas para que dev/prod usen la misma lógica:
      - Dev:  <raíz proyecto>/ingresos/
      - Prod: ~/Documents/Vet Suite/ingresos/
    """
    return _CARPETA_DATOS


def _ruta_log():
    carpeta = _carpeta_datos() / "logs"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = datetime.now().strftime("sync_%Y-%m-%d_%H-%M-%S.log")
    return carpeta / nombre


def _ruta_cache_correos():
    return _carpeta_datos() / "correos_procesados.json"


def cargar_cache_correos():
    """Devuelve el set de Message-IDs ya procesados."""
    ruta = _ruta_cache_correos()
    if ruta.exists():
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("ids", []))
        except Exception:
            pass
    return set()


def guardar_cache_correos(ids):
    """Guarda el set de Message-IDs procesados."""
    ruta = _ruta_cache_correos()
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"ids": sorted(ids)}, f, ensure_ascii=False, indent=2)


def _decodificar_cabecera(valor):
    """Decodifica cabeceras MIME."""
    if not valor:
        return ""
    partes = decode_header(valor)
    resultado = []
    for texto, encoding in partes:
        if isinstance(texto, bytes):
            try:
                texto = texto.decode(encoding or "utf-8", errors="ignore")
            except Exception:
                texto = texto.decode("utf-8", errors="ignore")
        resultado.append(texto)
    return "".join(resultado)


def _imap_fecha(dias_atras):
    """
    Devuelve la fecha en formato IMAP (dd-Mon-yyyy).
    Ejemplo: '20-Sep-2026'
    """
    fecha = datetime.now() - timedelta(days=dias_atras)
    meses = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{fecha.day:02d}-{meses[fecha.month-1]}-{fecha.year}"


def normalizar_qvet(serie, folio):
    """
    Normaliza el QVET al formato Serie/Folio.
    
    Reglas:
      - S1 → S1 (todo mayúsculas)
      - Prados / Prado / PRADOS / prados → PRADOS
      - Siempre con '/' entre serie y folio
    
    Ejemplos:
      normalizar_qvet("S1", "8407")     → "S1/8407"
      normalizar_qvet("PRADOS", "197")  → "PRADOS/197"
      normalizar_qvet("prado", "198")   → "PRADOS/198"
    """
    serie = str(serie).strip()
    folio = str(folio).strip()
    
    # Normalizar la serie
    s_upper = serie.upper()
    
    if s_upper == "S1":
        # S1 siempre en mayúsculas
        serie_norm = "S1"
    elif s_upper in ("PRADOS"):
        # Prados siempre en mayúsculas
        serie_norm = s_upper  # "PRADOS"
    else:
        # Otras series: mayúscula
        serie_norm = serie.upper()
    
    return f"{serie_norm}/{folio}"


def descargar_adjuntos_gmail(usuario, password_app, etiqueta,
    carpeta_destino=None,
    solo_no_leidos=False,
    filtro_remitente=None,
    dias_atras=None,
    usar_cache=True,
    callback_log=None,
    callback_progreso=None,
    callback_cancelado=None):
    """
    Descarga los adjuntos XML/PDF de la etiqueta de Gmail.

    Parámetros nuevos:
      - callback_cancelado: función sin argumentos que devuelve True
                            si el usuario canceló la operación.
                            Se llama antes de cada correo.
    """
    """
    Se conecta a Gmail y descarga los adjuntos XML/PDF de la etiqueta indicada.

    Parámetros:
      - usuario: correo completo
      - password_app: contraseña de aplicación
      - etiqueta: nombre de la etiqueta de Gmail
      - carpeta_destino: dónde guardar los adjuntos
      - solo_no_leidos: solo correos no leídos
      - filtro_remitente: substring del remitente (ej. 'qvet')
      - dias_atras: solo correos de los últimos N días (None = todos)
      - usar_cache: si True, omite correos ya procesados anteriormente
      - callback_log: función que recibe strings para mostrar progreso
      - callback_progreso: función que recibe (procesados, total) para mostrar progreso

    Devuelve:
      - (lista_archivos_descargados, lista_errores, info)
    """

    # 1. Definir ruta_log y abrir archivo
    ruta_log = _ruta_log()
    archivo_log = open(ruta_log, "w", encoding="utf-8")

    # 2. Definir función log (usa ruta_log indirectamente)
    def log(msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        linea = f"[{timestamp}] {msg}"
        try:
            archivo_log.write(linea + "\n")
            archivo_log.flush()
        except Exception:
            pass
        if callback_log:
            callback_log(msg)
        else:
            print(linea)

    # 3. Definir función progreso
    def progreso(texto):
        """Actualiza la barra/texto de progreso (independiente del log)."""
        if callback_progreso:
            try:
                callback_progreso(texto)
            except Exception:
                pass

    # 4. Log inicial (ya puede usar ruta_log)
    log(f"Log guardado en: {ruta_log}")

    # 5. Preparar carpeta destino
    carpeta_destino = Path(carpeta_destino) if carpeta_destino else _carpeta_datos() / "descargas"
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    # 6. Inicializar variables
    descargados = []
    errores = []
    qvet_por_archivo = {}
    no_factura_por_archivo = {}
    archivos_por_correo = {}
    info = {
        "total_correos": 0,
        "procesados": 0,
        "omitidos_cache": 0,
        "omitidos_filtros": 0,
        "log": str(ruta_log),
        "qvet_por_archivo": qvet_por_archivo
    }

    # 7. Cargar caché de correos ya procesados
    cache_ids = cargar_cache_correos() if usar_cache else set()
    ids_procesados_esta_vez = set()

    try:
        # ---- Conectar ----
        progreso("🔌 Conectando a Gmail...")
        log(f"Conectando a {IMAP_SERVER}...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(usuario, password_app)
        log("✅ Conexión exitosa")

        # ---- Seleccionar la etiqueta ----
        etiqueta_escaped = etiqueta.replace('"', '\\"')
        log(f"Abriendo etiqueta: {etiqueta}")
        status, data = mail.select(f'"{etiqueta_escaped}"')
        if status != "OK":
            status, data = mail.select(etiqueta_escaped)
        if status != "OK":
            errores.append(f"No se pudo abrir la etiqueta '{etiqueta}'")
            return descargados, errores, info

        # ---- Construir criterio de búsqueda ----
        criterios = []

        if solo_no_leidos:
            criterios.append("UNSEEN")

        if dias_atras is not None:
            fecha = _imap_fecha(dias_atras)
            criterios.append(f'SINCE "{fecha}"')
            log(f"Filtro de fecha: correos desde {fecha}")

        if filtro_remitente:
            criterios.append(f'FROM "{filtro_remitente}"')
            log(f"Filtro de remitente: {filtro_remitente}")

        if not criterios:
            criterio_final = "ALL"
        else:
            criterio_final = "(" + " ".join(criterios) + ")"

        progreso("🔍 Buscando correos en la etiqueta...")
        log(f"Buscando correos con criterio: {criterio_final}")
        status, data = mail.search(None, criterio_final)
        if status != "OK":
            errores.append("Error al buscar correos")
            return descargados, errores, info

        ids = data[0].split()
        info["total_correos"] = len(ids)
        log(f"Correos encontrados: {len(ids)}")
        progreso(f"📬 {len(ids)} correos encontrados. Procesando...")

        ids = data[0].split()
        info["total_correos"] = len(ids)
        log(f"Correos encontrados: {len(ids)}")

        if not ids:
            return descargados, errores, info

        # ---- Procesar cada correo ----
        total_correos = len(ids)
                # ---- Procesar cada correo ----
        total_correos = len(ids)
        cancelado = False
        for i, num in enumerate(ids, 1):
            try:
                # ---- Verificar cancelación ANTES de cada correo ----
                if callback_cancelado and callback_cancelado():
                    log(f"\n⚠️ Cancelación solicitada por el usuario.")
                    log(f"   Correos procesados: {i-1} de {total_correos}")
                    cancelado = True
                    break

                # Actualizar progreso cada correo
                porcentaje = int((i / total_correos) * 100)
                progreso(
                    f"📥 Correo {i} de {total_correos} ({porcentaje}%)  "
                    f"|  Descargados: {len(descargados)} archivos"
                )

                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    errores.append(f"Error al obtener correo {num}")
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # ---- Verificar caché ----
                message_id = (msg.get("Message-ID") or "").strip()
                if usar_cache and message_id and message_id in cache_ids:
                    log(f"[{i}/{len(ids)}] ⏭️ Ya procesado (Message-ID en caché). Se omite.")
                    info["omitidos_cache"] += 1
                    continue

                asunto = _decodificar_cabecera(msg.get("Subject", ""))
                remitente = _decodificar_cabecera(msg.get("From", ""))
                fecha = msg.get("Date", "")

                log(f"[{i}/{len(ids)}] Asunto: {asunto}")
                log(f"          De: {remitente}")
                log(f"          Fecha: {fecha}")

                # ---- Extraer el QVET del asunto del correo ----
                # ============================================================
                # Extraer QVET y No. factura del asunto del correo
                # Formato esperado: "Factura de venta SERIE/FOLIO-FOLIO"
                # Ejemplo: "Factura de venta S1/1234-2346"
                #          "Factura de venta Prados/265-266"
                # ============================================================
                qvet_detectado = ""       # ej. "S1/1234" o "Prados/265"
                no_factura_detectado = "" # ej. "2346" o "266"

                # Patrón: cualquier cosa antes de "-", y luego el número
                # Captura "S1/1234" y "2346" de "S1/1234-2346"
                m_asunto = re.search(
                    r"([A-Za-z0-9]+(?:/[A-Za-z0-9]+)?)\s*-\s*(\d+)",
                    asunto,
                    re.IGNORECASE
                )

                if m_asunto:
                    serie_completa = m_asunto.group(1).strip()   # "S1/1234" o "Prados/265"
                    folio_str = m_asunto.group(2).strip()        # "2346" o "266"

                    # Limpiar ceros a la izquierda del folio
                    if folio_str.isdigit():
                        no_factura_detectado = str(int(folio_str))
                    else:
                        no_factura_detectado = folio_str

                    # Normalizar el QVET
                    # - "S1/1234" → "S1/1234"
                    # - "Prados/265" → "PRADOS/265"
                    # - "prados/0265" → "PRADOS/265"
                    if "/" in serie_completa:
                        serie_parte, num_parte = serie_completa.split("/", 1)
                        serie_norm = serie_parte.strip().upper()
                        if serie_norm == "PRADO":
                            serie_norm = "PRADOS"
                        num_parte = num_parte.strip()
                        if num_parte.isdigit():
                            num_parte = str(int(num_parte))
                        qvet_detectado = f"{serie_norm}/{num_parte}"
                    else:
                        qvet_detectado = serie_completa.upper()

                    log(f"          🔖 QVET detectado: {qvet_detectado}")
                    log(f"          🔖 No. factura detectado: {no_factura_detectado}")
                else:
                    log(f"          ⚠️ No se pudo extraer SERIE-FOLIO del asunto")

                # ---- Verificar filtro de remitente (doble check) ----
                if filtro_remitente:
                    if filtro_remitente.lower() not in remitente.lower():
                        log(f"          ⏭️ Omitido (remitente no coincide)")
                        info["omitidos_filtros"] += 1
                        continue

                # ---- Extraer adjuntos ----
                adjuntos_correo = []
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    if part.get("Content-Disposition") is None:
                        continue

                    nombre_archivo = part.get_filename()
                    if not nombre_archivo:
                        continue
                    nombre_archivo = _decodificar_cabecera(nombre_archivo)

                    ext = Path(nombre_archivo).suffix.lower()
                    if ext not in (".xml", ".pdf"):
                        continue

                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue

                    # Ruta destino (evitar sobrescribir)
                    destino = carpeta_destino / nombre_archivo
                    contador = 1
                    while destino.exists():
                        base = Path(nombre_archivo).stem
                        destino = carpeta_destino / f"{base}_{contador}{ext}"
                        contador += 1

                    with open(destino, "wb") as f:
                        f.write(payload)

                    adjuntos_correo.append(destino)
                    descargados.append(destino)
                    log(f"          📎 {destino.name}")

                    # Guardar QVET y No. factura detectados del asunto
                    if qvet_detectado:
                        qvet_por_archivo[destino.name] = qvet_detectado
                    if no_factura_detectado:
                        no_factura_por_archivo[destino.name] = no_factura_detectado

                    # Guardar en archivos_por_correo
                    if message_id:
                        archivos_por_correo.setdefault(message_id, []).append(str(destino))

                if adjuntos_correo:
                    info["procesados"] += 1
                    if message_id:
                        ids_procesados_esta_vez.add(message_id)

                    # Marcar como leído si aplica
                    if solo_no_leidos:
                        mail.store(num, "+FLAGS", "\\Seen")

            except Exception as e:
                errores.append(f"Correo {num}: {e}")
                log(f"          ❌ Error: {e}")

        # ---- Cerrar conexión ----
        if cancelado:
            progreso(f"⚠️ Cancelado. {len(descargados)} archivos obtenidos.")
        else:
            progreso(f"✅ Descarga completa. {len(descargados)} archivos obtenidos.")
        try:
            mail.close()
        except Exception:
            pass
        mail.logout()
        log(f"✅ Desconectado.")
        if cancelado:
            log(f"⚠️ DESCARGA CANCELADA POR EL USUARIO")
        log(f"   Archivos descargados: {len(descargados)}")
        log(f"   Correos procesados:   {info['procesados']}")
        log(f"   Omitidos por caché:   {info['omitidos_cache']}")
        log(f"   Omitidos por filtros: {info['omitidos_filtros']}")

        # ---- Actualizar caché ----
        if usar_cache and ids_procesados_esta_vez:
            cache_ids.update(ids_procesados_esta_vez)
            guardar_cache_correos(cache_ids)
            log(f"   Caché actualizada: {len(cache_ids)} correos registrados")

    except imaplib.IMAP4.error as e:
        errores.append(f"Error IMAP: {e}")
        log(f"❌ Error IMAP: {e}")
    except Exception as e:
        errores.append(f"Error: {e}")
        log(f"❌ Error: {e}")
    finally:
        try:
            archivo_log.close()
        except Exception:
            pass

    info["qvet_por_archivo"] = qvet_por_archivo
    info["no_factura_por_archivo"] = no_factura_por_archivo
    info["archivos_por_correo"] = archivos_por_correo
    return descargados, errores, info