#!/usr/bin/env python3
"""
test/test_procesar_descartados.py

Inspecciona y procesa los XMLs de egresos/descartados/.

Tres categorías:
  - DUPLICADO:   el UUID ya existe en el JSON. No hay nada que hacer.
  - VÁLIDO:      parsea bien, no está en el JSON. Se puede insertar y mover.
  - INVÁLIDO:    no parsea. Requiere revisión manual (o está corrupto).

Uso:
    python3 test/test_procesar_descartados.py --listar
    python3 test/test_procesar_descartados.py --listar --anio 2026
    python3 test/test_procesar_descartados.py --procesar-uno <archivo.xml>
    python3 test/test_procesar_descartados.py --procesar-todos --anio 2026
    python3 test/test_procesar_descartados.py --procesar-todos --anio 2026 --auto
"""

import argparse
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core.rutas_egresos import CARPETA_DATOS
from config.campos import MESES_ES

DESCARTADOS = Path(CARPETA_DATOS) / "descartados"

# Códigos del SAT → nombre de carpeta
FORMAS = {
    "01": "Efectivo",
    "03": "Transferencia",
    "04": "TC",
    "28": "TD",
    "99": "PPD",
}

# ─────────────────────────────────────────────────────────────
# Inspección (no modifica nada)
# ─────────────────────────────────────────────────────────────

def _parsear_xml(ruta_xml: Path) -> dict | None:
    """Parsea un XML aislado usando procesar_carpeta. Devuelve el dict
    de la factura o None si no parsea."""
    from sat.procesar_xml import procesar_carpeta
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy2(ruta_xml, Path(tmp) / ruta_xml.name)
        facturas = procesar_carpeta(tmp)
    return facturas[0] if facturas else None


def _uuid_esta_en_json(uuid: str, anio: int) -> bool:
    """Verifica si un UUID ya está registrado en el JSON del año."""
    from sat.guardar_egresos import cargar_db_egresos
    if not uuid:
        return False
    registros = cargar_db_egresos(anio)
    return any(r.get("uuid") == uuid for r in registros)


def inspeccionar(ruta_xml: Path, anio: int) -> dict:
    """
    Devuelve:
      {
        "ruta": Path,
        "parsea": bool,
        "factura": dict | None,
        "uuid": str | None,
        "metodo": str | None,
        "forma_codigo": str | None,
        "forma_nombre": str | None,
        "duplicado": bool,
        "categoria": "DUPLICADO" | "VÁLIDO" | "INVÁLIDO",
      }
    """
    info = {
        "ruta": ruta_xml,
        "parsea": False,
        "factura": None,
        "uuid": None,
        "metodo": None,
        "forma_codigo": None,
        "forma_nombre": None,
        "duplicado": False,
        "categoria": "INVÁLIDO",
    }

    factura = _parsear_xml(ruta_xml)
    if not factura:
        return info

    info["parsea"] = True
    info["factura"] = factura
    info["uuid"] = factura.get("uuid")
    info["metodo"] = factura.get("metodo_pago")
    forma_cod = str(factura.get("forma_pago") or "").strip()
    info["forma_codigo"] = forma_cod
    info["forma_nombre"] = FORMAS.get(forma_cod, "?")
    info["duplicado"] = _uuid_esta_en_json(info["uuid"], anio)

    if info["duplicado"]:
        info["categoria"] = "DUPLICADO"
    else:
        info["categoria"] = "VÁLIDO"

    return info


# ─────────────────────────────────────────────────────────────
# Listar
# ─────────────────────────────────────────────────────────────

def cmd_listar(anio: int):
    if not DESCARTADOS.exists():
        print(f"No existe la carpeta: {DESCARTADOS}")
        return 0

    xmls = sorted(DESCARTADOS.glob("*.xml"))
    if not xmls:
        print(f"No hay XMLs descartados en: {DESCARTADOS}")
        return 0

    print(f"▶ {len(xmls)} XML(s) descartados en {DESCARTADOS}\n")

    conteo = {"VÁLIDO": 0, "DUPLICADO": 0, "INVÁLIDO": 0}
    for xml in xmls:
        info = inspeccionar(xml, anio)
        conteo[info["categoria"]] += 1

        iconos = {"VÁLIDO": "✅", "DUPLICADO": "⏭️ ", "INVÁLIDO": "❌"}
        print(f"  {iconos[info['categoria']]} {xml.name}  [{info['categoria']}]")
        if info["parsea"]:
            print(f"      UUID:   {info['uuid']}")
            print(f"      Método: {info['metodo']}  "
                  f"Forma:  {info['forma_nombre']} ({info['forma_codigo']})")
        print()

    print("─" * 60)
    print(f"  ✅ Válidos:    {conteo['VÁLIDO']}    (se pueden procesar)")
    print(f"  ⏭️  Duplicados: {conteo['DUPLICADO']}    (ya están en el JSON)")
    print(f"  ❌ Inválidos:  {conteo['INVÁLIDO']}    (revisar a mano)")
    return 0


# ─────────────────────────────────────────────────────────────
# Procesar uno
# ─────────────────────────────────────────────────────────────

def _preguntar_metodo_forma(metodo_default: str, forma_default: str) -> tuple[str, str]:
    """Pregunta al usuario el método y forma si no son confiables."""
    metodos = ["PUE", "PPD"]
    formas = ["Efectivo", "TC", "TD", "Transferencia", "PPD"]

    metodo = metodo_default if metodo_default in metodos else "PUE"
    forma = forma_default if forma_default in formas else "Efectivo"

    print(f"\n  Método detectado: {metodo_default or '?'}")
    print(f"  Forma detectada:  {forma_default or '?'}")

    resp = input(f"  Método [{metodo}]: ").strip().upper()
    if resp in metodos:
        metodo = resp

    # Si es PPD, la forma es forzosamente "PPD"
    if metodo == "PPD":
        return "PPD", "PPD"

    resp = input(f"  Forma [{forma}]: ").strip()
    if resp in formas and resp != "PPD":
        forma = resp

    return metodo, forma


def _mover_xml_y_actualizar(factura: dict, xml_origen: Path, metodo: str, forma: str,
                            anio: int) -> tuple[bool, str]:
    """
    - Añade la factura al JSON del año.
    - Mueve el XML a su carpeta definitiva.
    Devuelve (ok, mensaje).
    """
    from sat.guardar_egresos import (
        cargar_db_egresos,
        guardar_db_egresos,
    )
    from sat.mover_egresos import mover_un_registro, _parsear_fecha_ddmmyyyy

    # Normalizar método/forma en la factura
    factura["metodo_pago"] = metodo
    factura["forma_pago_texto"] = forma

    # Insertar en el JSON si no existe
    registros = cargar_db_egresos(anio)
    if any(r.get("uuid") == factura.get("uuid") for r in registros):
        return False, "El UUID ya está en el JSON (¿duplicado?)"

    # Calcular mes_idx a partir de la fecha de la factura
    anio_f, mes_f = _parsear_fecha_ddmmyyyy(factura.get("fecha", ""))
    if anio_f is None:
        return False, f"Fecha inválida en el XML: {factura.get('fecha')!r}"

    # Asignar id (siguiente) y año/mes reales
    nuevo_id = max((r.get("id", 0) for r in registros), default=0) + 1
    factura["id"] = nuevo_id
    factura["anio"] = anio_f
    factura["mes"] = MESES_ES[mes_f - 1] if 'MESES_ES' in globals() else _mes_nombre(mes_f)

    # Establecer ruta_xml temporal para que mover_un_registro lo encuentre
    factura["ruta_xml"] = str(xml_origen)

    # Mover
    ok, msg = mover_un_registro(factura, anio_f, mes_f)
    if not ok:
        return False, f"mover_un_registro falló: {msg}"

    # Recargar el JSON, agregar la factura, guardar
    registros = cargar_db_egresos(anio)
    registros.append(factura)
    guardar_db_egresos(registros, anio)

    return True, msg


def _mes_nombre(mes_idx: int) -> str:
    from config.campos import MESES_ES
    return MESES_ES[mes_idx - 1]


def cmd_procesar_uno(ruta_xml: Path, anio: int, auto: bool = False):
    if not ruta_xml.exists():
        print(f"✗ No existe: {ruta_xml}")
        return 2

    info = inspeccionar(ruta_xml, anio)
    print(f"\n▶ {ruta_xml.name}  [{info['categoria']}]")

    if info["categoria"] == "INVÁLIDO":
        print("  ❌ No parsea como CFDI. Revisa el XML a mano.")
        return 1

    if info["categoria"] == "DUPLICADO":
        print(f"  ⏭️  UUID ya en el JSON: {info['uuid']}")
        print("     No hay nada que hacer. Puedes borrar el XML.")
        return 0

    # VÁLIDO
    factura = info["factura"]
    print(f"  UUID:   {factura.get('uuid')}")
    print(f"  Folio:  {factura.get('folio')}")
    print(f"  Fecha:  {factura.get('fecha')}")
    print(f"  Emisor: {factura.get('nombre_emisor')}")
    print(f"  Total:  ${factura.get('total', 0):,.2f}")
    print(f"  Método: {info['metodo']}  Forma: {info['forma_nombre']} ({info['forma_codigo']})")

    if auto:
        metodo = info["metodo"] if info["metodo"] in ("PUE", "PPD") else "PUE"
        forma = info["forma_nombre"] if info["forma_nombre"] in FORMAS.values() else "Efectivo"
        if metodo == "PPD":
            forma = "PPD"
        print(f"\n  [auto] Usando método={metodo}, forma={forma}")
    else:
        metodo, forma = _preguntar_metodo_forma(info["metodo"], info["forma_nombre"])

    resp = input("\n  ¿Procesar? [s/N]: ").strip().lower()
    if resp not in ("s", "si", "sí", "y", "yes"):
        print("  Cancelado.")
        return 0

    ok, msg = _mover_xml_y_actualizar(factura, ruta_xml, metodo, forma, anio)
    if ok:
        print(f"\n  ✅ Procesado. {msg}")
        print(f"     XML movido a: {factura.get('ruta_xml')}")
        return 0
    else:
        print(f"\n  ❌ Error: {msg}")
        return 1


# ─────────────────────────────────────────────────────────────
# Procesar todos
# ─────────────────────────────────────────────────────────────

def cmd_procesar_todos(anio: int, auto: bool):
    if not DESCARTADOS.exists():
        print(f"No existe la carpeta: {DESCARTADOS}")
        return 0

    xmls = sorted(DESCARTADOS.glob("*.xml"))
    if not xmls:
        print("No hay XMLs descartados.")
        return 0

    print(f"▶ Procesando {len(xmls)} XML(s) descartados ({'AUTO' if auto else 'INTERACTIVO'})\n")

    procesados = 0
    duplicados = 0
    invalidos = 0
    errores = 0

    for xml in xmls:
        info = inspeccionar(xml, anio)

        if info["categoria"] == "DUPLICADO":
            duplicados += 1
            print(f"  ⏭️  {xml.name}  (duplicado)")
            continue

        if info["categoria"] == "INVÁLIDO":
            invalidos += 1
            print(f"  ❌ {xml.name}  (no parsea)")
            continue

        # VÁLIDO
        if auto:
            metodo = info["metodo"] if info["metodo"] in ("PUE", "PPD") else "PUE"
            forma = info["forma_nombre"] if info["forma_nombre"] in FORMAS.values() else "Efectivo"
            if metodo == "PPD":
                forma = "PPD"
            print(f"  ✅ {xml.name}  → {metodo}/{forma}")
            ok, msg = _mover_xml_y_actualizar(info["factura"], xml, metodo, forma, anio)
            if ok:
                procesados += 1
            else:
                errores += 1
                print(f"     ❌ {msg}")
        else:
            # Interactivo: reusar cmd_procesar_uno
            rc = cmd_procesar_uno(xml, anio, auto=False)
            if rc == 0:
                procesados += 1
            else:
                errores += 1

    print("\n" + "─" * 60)
    print(f"  ✅ Procesados: {procesados}")
    print(f"  ⏭️  Duplicados: {duplicados}")
    print(f"  ❌ Inválidos:  {invalidos}")
    print(f"  ⚠️  Errores:    {errores}")
    return 0


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Procesa los XMLs descartados de Egresos."
    )
    parser.add_argument("--anio", type=int, default=datetime.now().year,
                        help="Año del JSON a consultar (default: año actual).")
    parser.add_argument("--listar", action="store_true",
                        help="Solo listar y clasificar, sin modificar nada.")
    parser.add_argument("--procesar-uno", metavar="ARCHIVO",
                        help="Procesar un XML individual (ruta o nombre).")
    parser.add_argument("--procesar-todos", action="store_true",
                        help="Procesar todos los descartados válidos.")
    parser.add_argument("--auto", action="store_true",
                        help="No preguntar método/forma; usar lo detectado.")
    args = parser.parse_args()

    if args.listar:
        return cmd_listar(args.anio)

    if args.procesar_uno:
        ruta = Path(args.procesar_uno)
        if not ruta.is_absolute():
            ruta = DESCARTADOS / args.procesar_uno
        return cmd_procesar_uno(ruta, args.anio, auto=args.auto)

    if args.procesar_todos:
        return cmd_procesar_todos(args.anio, auto=args.auto)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())