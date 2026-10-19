# -*- coding: utf-8 -*-
"""
sat/descarga.py
Modulo unificado para descargar CFDIs del SAT.

Reutiliza la logica exacta de los test_*.py que ya funcionaron:
  - test_conversion.py   -> preparar_fiel + autenticar
  - test_solicitud.py    -> solicitar descarga
  - test_verificacion.py -> verificar estado
  - test_descarga.py     -> descargar paquetes y extraer XMLs

NO modifica conversion.py ni la logica de la FIEL.

Cambios v2.1.2:
  - Engancha core.sat_historial para guardar todo lo que viene del SAT.
  - Agrega probar_fiel() para validar credenciales sin gastar solicitud.
"""

import base64
import zipfile
from datetime import datetime
from pathlib import Path

from cfdiclient import (
    Autenticacion,
    DescargaMasiva,
    Fiel,
    SolicitaDescargaRecibidos,
    VerificaSolicitudDescarga,
)

# ← NUEVO
from core import sat_historial


# ============================================================
# PREPARAR LA FIEL (igual que test_conversion.py)
# ============================================================
def _cargar_fiel(ruta_cer, ruta_key, password):
    """Prepara la FIEL y devuelve un objeto Fiel listo para usar."""
    from sat.conversion import preparar_fiel

    ruta_cer_der, ruta_key_der = preparar_fiel(ruta_cer, ruta_key, password)

    with open(ruta_cer_der, "rb") as f:
        cer_der = f.read()
    with open(ruta_key_der, "rb") as f:
        key_der = f.read()

    return Fiel(cer_der, key_der, "")


# ============================================================
# AUTENTICAR (igual que test_conversion.py)
# ============================================================
def obtener_token(ruta_cer, ruta_key, password):
    """Autentica con el SAT y devuelve un token."""
    fiel = _cargar_fiel(ruta_cer, ruta_key, password)
    auth = Autenticacion(fiel)
    return auth.obtener_token()


# ============================================================
# ← NUEVO: PROBAR FIEL (sin gastar solicitud)
# ============================================================
def probar_fiel(ruta_cer, ruta_key, password):
    """
    Valida la FIEL sin gastar solicitud.
    Solo hace Autenticacion, que el SAT NO cuenta como solicitud.

    Devuelve: {"ok": bool, "mensaje": str, "token_preview": str|None}
    """
    for etiqueta, ruta in (("certificado (.cer)", ruta_cer),
                           ("llave (.key)", ruta_key)):
        if not ruta or not Path(ruta).exists():
            return {
                "ok": False,
                "mensaje": f"No se encuentra el {etiqueta}: {ruta}",
                "token_preview": None,
            }

    try:
        token = obtener_token(ruta_cer, ruta_key, password)
        if not token:
            return {
                "ok": False,
                "mensaje": "El SAT no devolvió token. Revisa tu FIEL y contraseña.",
                "token_preview": None,
            }
        return {
            "ok": True,
            "mensaje": "FIEL válida. El SAT autenticó correctamente.",
            "token_preview": token[:20] + "...",
        }
    except Exception as e:
        return {
            "ok": False,
            "mensaje": f"Error al autenticar: {e}",
            "token_preview": None,
        }


# ============================================================
# SOLICITAR DESCARGA
# ============================================================
def solicitar_descarga(ruta_cer, ruta_key, password, rfc,
                       fecha_inicio, fecha_fin,
                       tipo_solicitud="CFDI"):
    """Solicita una descarga de CFDI recibidos."""
    fiel = _cargar_fiel(ruta_cer, ruta_key, password)
    token = Autenticacion(fiel).obtener_token()

    solicitud = SolicitaDescargaRecibidos(fiel)
    try:
        resultado = solicitud.solicitar_descarga(
            token=token,
            rfc_solicitante=rfc,
            fecha_inicial=fecha_inicio,
            fecha_final=fecha_fin,
            rfc_receptor=rfc,
            tipo_solicitud=tipo_solicitud,
        )
    except Exception as e:
        # ← NUEVO
        sat_historial.guardar_error("solicitar_descarga", e, {
            "rfc": rfc,
            "fecha_inicio": str(fecha_inicio),
            "fecha_fin": str(fecha_fin),
            "tipo_solicitud": tipo_solicitud,
        })
        raise

    # ← NUEVO
    id_solicitud = resultado.get("id_solicitud", "")
    sat_historial.guardar_solicitud(id_solicitud, resultado, {
        "rfc": rfc,
        "fecha_desde": str(fecha_inicio),
        "fecha_hasta": str(fecha_fin),
        "tipo_solicitud": tipo_solicitud,
    })

    return resultado


# ============================================================
# VERIFICAR ESTADO
# ============================================================
def verificar_solicitud(ruta_cer, ruta_key, password, rfc, id_solicitud):
    """Verifica el estado de una solicitud (con reintentos por timeout)."""
    import time as _time

    fiel = _cargar_fiel(ruta_cer, ruta_key, password)

    ultimo_error = None
    for intento in range(3):
        try:
            token = Autenticacion(fiel).obtener_token()
            verificacion = VerificaSolicitudDescarga(fiel)
            resultado = verificacion.verificar_descarga(
                token=token,
                rfc_solicitante=rfc,
                id_solicitud=id_solicitud,
            )

            estado = str(resultado.get("estado_solicitud", "?"))
            mensaje_sat = resultado.get("mensaje", "")
            codigo = str(resultado.get("codigo_estado_solicitud", ""))

            mensaje_mostrar = mensaje_sat
            if estado == "5":
                if "aceptada" in mensaje_sat.lower():
                    mensaje_mostrar = (
                        "Solicitud rechazada. Posible causa: ya existe "
                        "una solicitud en proceso para el mismo periodo. "
                        "Espera unos minutos o usa un rango de fechas distinto."
                    )
                else:
                    mensaje_mostrar = f"Solicitud rechazada: {mensaje_sat}"

            salida = {
                "estado": estado,
                "mensaje": mensaje_mostrar,
                "numero_cfdis": str(resultado.get("numero_cfdis", "0")),
                "paquetes": resultado.get("paquetes", []) or [],
                "codigo": codigo,
            }

            # ← NUEVO
            sat_historial.guardar_verificacion(id_solicitud, salida)

            return salida
        except Exception as e:
            ultimo_error = e
            msg = str(e).lower()
            if "timed out" in msg or "timeout" in msg:
                _time.sleep(5)
                continue
            # ← NUEVO
            sat_historial.guardar_error("verificar_solicitud", e, {
                "id_solicitud": id_solicitud,
            })
            raise

    # ← NUEVO: timeout persistente
    salida = {
        "estado": "2",
        "mensaje": "El SAT no responde, reintentando...",
        "numero_cfdis": "0",
        "paquetes": [],
        "codigo": "",
    }
    sat_historial.guardar_verificacion(id_solicitud, salida)
    return salida


# ============================================================
# DESCARGAR PAQUETES
# ============================================================
def descargar_paquetes(ruta_cer, ruta_key, password, rfc,
                       paquetes, carpeta_destino=None,
                       id_solicitud=None):
    from core.rutas_egresos import CARPETA_DATOS
    if carpeta_destino is None:
        carpeta_destino = Path(CARPETA_DATOS) / "descargas"
    carpeta_destino = Path(carpeta_destino)
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    """Descarga los paquetes (ZIP) y extrae los XML."""
    fiel = _cargar_fiel(ruta_cer, ruta_key, password)
    token = Autenticacion(fiel).obtener_token()
    descarga = DescargaMasiva(fiel)

    carpeta_destino = Path(carpeta_destino)
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    for paquete in paquetes:
        paquete = paquete.strip()
        if not paquete:
            continue

        try:
            resultado = descarga.descargar_paquete(
                token=token,
                rfc_solicitante=rfc,
                id_paquete=paquete,
            )
        except Exception as e:
            # ← NUEVO
            sat_historial.guardar_error("descargar_paquete", e, {
                "id_solicitud": id_solicitud,
                "id_paquete": paquete,
            })
            raise

        contenido_b64 = ""
        if isinstance(resultado, dict):
            contenido_b64 = resultado.get("paquete", "")

        if not contenido_b64:
            print(f"WARN: paquete sin contenido: {paquete}")
            continue

        contenido_zip = base64.b64decode(contenido_b64)

        # ← NUEVO
        if id_solicitud:
            sat_historial.guardar_descarga(
                id_solicitud=id_solicitud,
                id_paquete=paquete,
                respuesta={"id_paquete": paquete,
                           "bytes_zip": len(contenido_zip)},
                zip_bytes=contenido_zip,
            )

        ruta_zip = carpeta_destino / f"{paquete}.zip"
        ruta_zip.write_bytes(contenido_zip)

        try:
            with zipfile.ZipFile(ruta_zip, "r") as z:
                z.extractall(carpeta_destino)
            ruta_zip.unlink()
        except Exception as e:
            print(f"WARN: error descomprimiendo {ruta_zip}: {e}")

    return list(carpeta_destino.glob("*.xml"))


# ============================================================
# FLUJO COMPLETO
# ============================================================
def flujo_completo(ruta_cer, ruta_key, password, rfc,
                   fecha_inicio, fecha_fin,
                   carpeta_destino=None,
                   tipo_solicitud="CFDI",
                   callback_estado=None):
    """Flujo completo: solicita -> (espera externa) -> descarga."""
    resultado_sol = solicitar_descarga(
        ruta_cer, ruta_key, password, rfc,
        fecha_inicio, fecha_fin,
        tipo_solicitud=tipo_solicitud,
    )

    id_solicitud = resultado_sol.get("id_solicitud", "")
    if not id_solicitud:
        raise RuntimeError(
            f"El SAT no devolvio id_solicitud: {resultado_sol}"
        )

    if callback_estado:
        callback_estado({
            "estado": "1",
            "mensaje": "Solicitud aceptada",
            "numero_cfdis": "0",
            "paquetes": [],
        })

    return {
        "id_solicitud": id_solicitud,
        "xmls": [],
        "total_cfdis": 0,
    }


# ============================================================
# PRUEBA DIRECTA
# ============================================================
if __name__ == "__main__":
    from config.config_egresos import cargar_config_egresos

    cfg = cargar_config_egresos()
    print("Config SAT:")
    print("  RFC:  " + str(cfg.get("rfc_receptor")))
    print("  CER:  " + str(cfg.get("certificado_cer")))
    print("  KEY:  " + str(cfg.get("certificado_key")))
    print()
    print("Probando autenticacion (NO toca la FIEL, solo usa preparar_fiel)...")
    res = probar_fiel(
        cfg["certificado_cer"],
        cfg["certificado_key"],
        cfg["password_fiel"],
    )
    if res["ok"]:
        print("OK " + res["mensaje"])
        print("Token: " + str(res["token_preview"]))
    else:
        print("ERROR: " + res["mensaje"])