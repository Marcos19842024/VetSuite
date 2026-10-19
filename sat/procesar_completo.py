# -*- coding: utf-8 -*-
"""
sat/procesar_completo.py
Orquesta el procesamiento completo de los XML descargados del SAT:

  1. procesar_carpeta()        -> leer XMLs y construir facturas
  2. guardar_facturas()        -> guardar en JSON
  3. mover_y_renombrar_egresos -> mover XMLs a PUE/PPD/Animalia
  4. actualizar_lineas + rutas -> actualizar JSON con lineas y rutas
  5. generar Excel PUE + PPD   -> en Deposito_Egreso/

NO modifica ningun modulo existente. Solo los usa.
"""

from datetime import datetime
from pathlib import Path
import shutil

from config.campos import MESES_ES
from sat.guardar_egresos import (
    cargar_db_egresos,
    guardar_db_egresos,
)
from sat.mover_egresos import (
    mover_y_renombrar_egresos,
    ruta_egreso,
)
from sat.procesar_xml import procesar_carpeta
from excel.egresos import generar_excel_pue, generar_excel_ppd


# ============================================================
# PASO 1 + 2: Procesar XML y guardar en JSON
# ============================================================
def procesar_y_guardar(carpeta_xml, anio):
    """
    Procesa todos los XML de la carpeta y los guarda en el JSON.

    Devuelve: (nuevas, duplicadas, facturas)
    """
    facturas = procesar_carpeta(carpeta_xml)

    if not facturas:
        return 0, 0, []

    from sat.guardar_egresos import guardar_facturas
    nuevas, duplicadas = guardar_facturas(facturas, anio=anio)

    return nuevas, duplicadas, facturas


# ============================================================
# PASO 3: Mover XMLs a PUE/PPD/Animalia
# ============================================================
def mover_xmls(anio, mes_idx, carpeta_origen="/tmp/sat_descargas"):
    """
    Mueve y renombra los XML a las carpetas PUE/PPD/Animalia.
    Devuelve (movidos, errores).
    """
    registros = cargar_db_egresos(anio)

    movidos, errores = mover_y_renombrar_egresos(
        registros,
        anio=anio,
        mes_idx=mes_idx,
        carpeta_origen=carpeta_origen,
    )

    return movidos, errores


# ============================================================
# PASO 4: Actualizar lineas y rutas en el JSON
# ============================================================
def actualizar_json(anio, mes_nombre):
    """
    Actualiza los campos 'ruta_xml' en el JSON buscando
    los XMLs ya movidos en las carpetas del mes.

    Ya NO asigna 'linea' (se calcula al vuelo).
    """
    import re

    base_egreso = (
        Path.home() / "Documents"
        / f"Contabilidad {anio}"
        / f"Contabilidad {mes_nombre}"
        / "Egreso"
    )

    registros = cargar_db_egresos(anio)

    # Indexar XML por nombre de archivo
    xml_por_folio = {}
    for sucursal in ["Baalak", "Animalia"]:
        for metodo in ["PUE", "PPD"]:
            for forma in ["Efectivo", "TC", "TD", "Transferencia", "PPD"]:
                carpeta = base_egreso / sucursal / metodo / forma
                if not carpeta.exists():
                    continue
                for ruta in carpeta.glob("*.xml"):
                    # Nombre: <serie>-<folio>.xml o <folio>.xml
                    stem = ruta.stem
                    if "-" in stem:
                        partes = stem.split("-", 1)
                        if len(partes) == 2 and partes[0].upper() == "S1":
                            folio = partes[1]
                        else:
                            folio = stem
                    else:
                        folio = stem
                    xml_por_folio[folio] = {
                        "ruta": str(ruta),
                        "carpeta": f"{sucursal}/{metodo}/{forma}",
                    }

    actualizados = 0
    no_encontrados = 0
    for reg in registros:
        folio = str(reg.get("folio", "")).strip()
        if not folio:
            continue

        info = xml_por_folio.get(folio)
        if info:
            reg["ruta_xml"] = info["ruta"]
            reg["ruta_xml_destino"] = info["ruta"]
            reg["carpeta"] = info["carpeta"]
            actualizados += 1
        else:
            no_encontrados += 1

    guardar_db_egresos(registros, anio)

    return actualizados, no_encontrados


# ============================================================
# ORQUESTADOR COMPLETO
# ============================================================
def procesar_todo(anio, mes_idx, carpeta_xml="/tmp/sat_descargas",
                  callback=None):
    """
    Ejecuta la secuencia completa:
      1. Procesar XML y guardar en JSON
      2. Mover XMLs a PUE/PPD/Animalia
      3. Actualizar lineas/rutas en JSON
      4. Generar Excel PUE + PPD

    Parametros:
      - anio: int, ej. 2026
      - mes_idx: int (1-12), ej. 9
      - carpeta_xml: carpeta donde estan los XML descargados
      - callback: funcion(mensaje) opcional para reportar progreso

    Devuelve un dict con el resumen de cada paso.
    """
    mes_nombre = MESES_ES[mes_idx - 1]

    def _log(msg):
        print(msg)
        if callback:
            try:
                callback(msg)
            except Exception:
                pass

    resumen = {
        "anio": anio,
        "mes": mes_nombre,
        "nuevas": 0,
        "duplicadas": 0,
        "movidos": 0,
        "errores_mover": 0,
        "actualizados": 0,
        "no_encontrados": 0,
        "descartados": 0,               # ← NUEVO
        "carpeta_descartados": None,    # ← NUEVO
        "excel": {},
    }

    # 1 + 2) Procesar y guardar
    _log("→ Procesando XMLs...")
    nuevas, duplicadas, facturas = procesar_y_guardar(carpeta_xml, anio)
    resumen["nuevas"] = nuevas
    resumen["duplicadas"] = duplicadas
    _log(f"   Nuevas: {nuevas} | Duplicadas: {duplicadas}")

    # 3) Mover XMLs
    _log("→ Moviendo XMLs a PUE/PPD/Animalia...")
    movidos, errores = mover_xmls(anio, mes_idx, carpeta_xml)
    resumen["movidos"] = len(movidos)
    resumen["errores_mover"] = len(errores)
    _log(f"   Movidos: {len(movidos)} | Errores: {len(errores)}")

    # 3b) NUEVO: rescatar XMLs que no se pudieron mover
    try:
        carpeta_origen = Path(carpeta_xml)
        sobran = list(carpeta_origen.glob("*.xml")) if carpeta_origen.exists() else []
        if sobran:
            descartados_dir = carpeta_origen.parent / "descartados"
            descartados_dir.mkdir(parents=True, exist_ok=True)
            for xml in sobran:
                try:
                    shutil.copy2(xml, descartados_dir / xml.name)
                except Exception as e:
                    _log(f"   ⚠ No se pudo copiar {xml.name}: {e}")
            resumen["descartados"] = len(sobran)
            resumen["carpeta_descartados"] = str(descartados_dir)
            _log(f"   ⚠ Descartados (no se movieron): {len(sobran)}")
            _log(f"     Guardados en: {descartados_dir}")
        else:
            _log("   ✓ No hay XMLs descartados")
    except Exception as e:
        _log(f"   ⚠ Error revisando descartados: {e}")

    # 4) Actualizar lineas/rutas
    _log("→ Actualizando JSON con lineas y rutas...")
    actualizados, no_encontrados = actualizar_json(anio, mes_nombre)
    resumen["actualizados"] = actualizados
    resumen["no_encontrados"] = no_encontrados
    _log(f"   Actualizados: {actualizados} | No encontrados: {no_encontrados}")

    # 5) Excel: NO se genera aquí.
    # El usuario lo genera con el botón "Generar Excel" tras revisar.
    resumen["excel"] = {
        "carpeta": None, "pue": None, "ppd": None,
        "total_pue": 0, "total_ppd": 0, "total_animalia": 0,
    }

    return resumen


if __name__ == "__main__":
    # Prueba con valores por defecto (ajustar si es necesario)
    procesar_todo(anio=2026, mes_idx=9)