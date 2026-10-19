#!/usr/bin/env python3
"""
Test interactivo del pipeline de Egresos (SAT → XMLs → procesar_todo).

Credenciales: se leen de config.config_egresos (config_egresos.json).
Período y rutas: se leen de test/test_egresos.json.

Flujo completo (con pausas entre etapas):
    python3 test/test_egresos.py

Config alternativa:
    python3 test/test_egresos.py --config otro.json

Sin pausas entre etapas (auto-continúa):
    python3 test/test_egresos.py --sin-pausas

Solo una etapa (usa el estado guardado en _estado_test.json):
    python3 test/test_egresos.py --solo solicitar
    python3 test/test_egresos.py --solo verificar
    python3 test/test_egresos.py --solo descargar
    python3 test/test_egresos.py --solo extraer
    python3 test/test_egresos.py --solo procesar

Combinaciones:
    python3 test/test_egresos.py --solo descargar --sin-pausas
    python3 test/test_egresos.py --config sept.json --solo procesar
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from config.config_egresos import cargar_config_egresos
from cfdiclient import (
    Fiel, Autenticacion,
    SolicitaDescargaRecibidos,
    VerificaSolicitudDescarga,
    DescargaMasiva,
)


ETAPAS = ["solicitar", "verificar", "descargar", "extraer", "procesar"]


# ─── Config ──────────────────────────────────────────────────

def cargar_test_config(ruta: Path) -> dict:
    if not ruta.exists():
        print(f"✗ No existe: {ruta}")
        print("  Crea uno con el formato de test_egresos_config.json")
        sys.exit(2)
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def crear_fiel(cfg_egresos: dict) -> Fiel:
    return Fiel(
        open(cfg_egresos["certificado_cer"], "rb").read(),
        open(cfg_egresos["certificado_key"], "rb").read(),
        cfg_egresos["password_fiel"],
    )


# ─── Estado persistido ───────────────────────────────────────

def ruta_estado(tcfg: dict) -> Path:
    return Path(tcfg["salida"]["archivo_estado"])


def leer_estado(tcfg: dict) -> dict:
    r = ruta_estado(tcfg)
    if r.exists():
        return json.loads(r.read_text(encoding="utf-8"))
    return {}


def guardar_estado(tcfg: dict, datos: dict):
    r = ruta_estado(tcfg)
    r.parent.mkdir(parents=True, exist_ok=True)
    actual = leer_estado(tcfg)
    actual.update(datos)
    r.write_text(json.dumps(actual, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Pausa ───────────────────────────────────────────────────

def pausa(mensaje: str, sin_pausas: bool) -> bool:
    if sin_pausas:
        print(f"\n▶ {mensaje} → (auto-continuar)")
        return True
    respuesta = input(f"\n⏸  {mensaje} [s/N]: ").strip().lower()
    return respuesta in ("s", "si", "sí", "y", "yes")


# ─── Etapas ──────────────────────────────────────────────────

def etapa_solicitar(fiel: Fiel, token: str, cfg_egresos: dict, tcfg: dict) -> str | None:
    periodo = tcfg["periodo"]
    fecha_ini = datetime.fromisoformat(periodo["fecha_inicial"])
    fecha_fin = datetime.fromisoformat(periodo["fecha_final"])
    rfc = cfg_egresos["rfc_receptor"]

    print(f"\n📤 SOLICITANDO descarga")
    print(f"   RFC:     {rfc}")
    print(f"   Período: {fecha_ini.date()} → {fecha_fin.date()}")

    solicitud = SolicitaDescargaRecibidos(fiel)
    resp = solicitud.solicitar_descarga(
        token,
        rfc,
        fecha_ini,
        fecha_fin,
        rfc_receptor=rfc,
        tipo_solicitud="CFDI",
    )

    print("\n   Respuesta del SAT:")
    for k, v in resp.items():
        print(f"     {k}: {v}")

    if resp.get("cod_estatus") == "5000":
        id_sol = resp["id_solicitud"]
        print(f"\n   ✓ Aceptada. id_solicitud: {id_sol}")
        guardar_estado(tcfg, {"id_solicitud": id_sol, "etapa": "solicitada"})
        return id_sol

    if resp.get("cod_estatus") == "5005":
        print("\n   ⚠ Ya existe una solicitud vigente para este período.")
        print("     Espera a que caduque o reutiliza un id_solicitud existente.")
    elif resp.get("cod_estatus") == "5002":
        print("\n   ✗ Solicitudes agotadas para este período.")
    else:
        print(f"\n   ✗ Código inesperado: {resp.get('mensaje', 'sin mensaje')}")
    return None


def etapa_verificar(fiel: Fiel, token: str, cfg_egresos: dict,
                    tcfg: dict, id_solicitud: str) -> list[str] | None:
    rfc = cfg_egresos["rfc_receptor"]
    print(f"\n🔍 VERIFICANDO {id_solicitud}")

    verificador = VerificaSolicitudDescarga(fiel)
    resp = verificador.verificar_descarga(token, rfc, id_solicitud)

    print("   Respuesta del SAT:")
    for k, v in resp.items():
        print(f"     {k}: {v}")

    estado = str(resp.get("estado_solicitud", ""))
    if estado == "3":
        paquetes = resp.get("paquetes") or []
        print(f"\n   ✓ Terminada. {len(paquetes)} paquete(s).")
        guardar_estado(tcfg, {"paquetes": paquetes, "etapa": "verificada"})
        return paquetes
    if estado in ("1", "2"):
        print(f"\n   ⏳ Estado {estado}. Aún no termina. Espera y reintenta con --solo verificar.")
    else:
        print(f"\n   ✗ Estado {estado}: {resp.get('mensaje', '')}")
    return None


def etapa_descargar(fiel: Fiel, token: str, cfg_egresos: dict,
                    tcfg: dict, paquetes: list[str]) -> list[Path]:
    rfc = cfg_egresos["rfc_receptor"]
    carpeta = Path(tcfg["salida"]["carpeta_descarga"])
    carpeta.mkdir(parents=True, exist_ok=True)

    descarga = DescargaMasiva(fiel)
    zips: list[Path] = []

    for id_paquete in paquetes:
        print(f"\n📥 DESCARGANDO {id_paquete}")
        resp = descarga.descargar_paquete(token, rfc, id_paquete)

        if resp.get("cod_estatus") != "5000":
            print(f"   ✗ Error: {resp}")
            continue

        zip_bytes = base64.b64decode(resp["paquete_b64"])
        ruta_zip = carpeta / f"{id_paquete}.zip"
        ruta_zip.write_bytes(zip_bytes)
        print(f"   ✓ {ruta_zip} ({len(zip_bytes):,} bytes)")
        zips.append(ruta_zip)

    if zips:
        guardar_estado(tcfg, {"zips": [str(z) for z in zips], "etapa": "descargada"})
    return zips


def etapa_extraer(tcfg: dict, zips: list[Path]) -> Path | None:
    destino = Path(tcfg["salida"]["carpeta_xmls"])
    destino.mkdir(parents=True, exist_ok=True)

    for z in zips:
        print(f"\n📦 EXTRAYENDO {z.name}")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(destino)

    xmls = sorted(destino.glob("*.xml"))
    print(f"\n   Total XMLs en {destino}: {len(xmls)}")
    if xmls:
        guardar_estado(tcfg, {"carpeta_xmls": str(destino), "num_xmls": len(xmls),
                              "etapa": "extraida"})
        return destino
    return None


def etapa_procesar(tcfg: dict, carpeta_xmls: Path):
    from sat.procesar_completo import procesar_todo

    p = tcfg["periodo"]
    print(f"\n⚙️  PROCESANDO con procesar_todo({p['anio']}, {p['mes']})")
    print(f"   Carpeta: {carpeta_xmls}")

    resumen = procesar_todo(p["anio"], p["mes"], carpeta_xml=str(carpeta_xmls))
    print(f"\n   ✓ Resumen: {resumen}")
    guardar_estado(tcfg, {"resumen_procesar": str(resumen), "etapa": "procesada"})


# ─── Flujo principal ─────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test interactivo del pipeline de Egresos (SAT → procesar_todo)",
    )
    parser.add_argument("--config", default="test/test_egresos.json",
                        help="JSON con período y rutas de salida.")
    parser.add_argument("--solo", choices=ETAPAS,
                        help="Ejecutar solo esa etapa (usa estado previo).")
    parser.add_argument("--sin-pausas", action="store_true",
                        help="No pedir confirmación entre etapas.")
    args = parser.parse_args()

    tcfg = cargar_test_config(Path(args.config))
    cfg_egresos = cargar_config_egresos()

    print("=" * 64)
    print("  TEST INTERACTIVO — PIPELINE DE EGRESOS")
    print("=" * 64)
    print(f"  RFC:       {cfg_egresos['rfc_receptor']}")
    print(f"  Período:   {tcfg['periodo']['fecha_inicial']} → {tcfg['periodo']['fecha_final']}")
    print(f"  Descargas: {tcfg['salida']['carpeta_descarga']}")
    print(f"  XMLs:      {tcfg['salida']['carpeta_xmls']}")
    print("=" * 64)

    estado = leer_estado(tcfg)
    if estado:
        print(f"  Estado previo: etapa={estado.get('etapa')}")
        if estado.get("id_solicitud"):
            print(f"    id_solicitud: {estado['id_solicitud']}")
        if estado.get("paquetes"):
            print(f"    paquetes: {estado['paquetes']}")
    print()

    if not pausa("¿Iniciar el flujo?", args.sin_pausas):
        print("Cancelado.")
        return 0

    fiel = crear_fiel(cfg_egresos)
    token = Autenticacion(fiel).obtener_token()
    print(f"✓ Token obtenido: {token[:30]}...")

    # 1) Solicitar
    if args.solo == "solicitar" or (not args.solo and not estado.get("id_solicitud")):
        id_sol = etapa_solicitar(fiel, token, cfg_egresos, tcfg)
        if not id_sol:
            return 1
        estado["id_solicitud"] = id_sol
        if args.solo == "solicitar":
            return 0
        if not pausa("¿Verificar la solicitud?", args.sin_pausas):
            return 0
    else:
        id_sol = estado.get("id_solicitud")
        if not id_sol:
            print("✗ No hay id_solicitud. Corre primero la etapa 'solicitar'.")
            return 2
        print(f"\nℹ Reutilizando id_solicitud: {id_sol}")

    # 2) Verificar
    if args.solo == "verificar" or (not args.solo and not estado.get("paquetes")):
        paquetes = etapa_verificar(fiel, token, cfg_egresos, tcfg, id_sol)
        if not paquetes:
            return 1
        estado["paquetes"] = paquetes
        if args.solo == "verificar":
            return 0
        if not pausa("¿Descargar paquetes?", args.sin_pausas):
            return 0
    else:
        paquetes = estado.get("paquetes")
        if not paquetes:
            print("✗ No hay paquetes. Corre primero 'verificar'.")
            return 2
        print(f"\nℹ Reutilizando {len(paquetes)} paquete(s)")

    # 3) Descargar
    if args.solo == "descargar" or (not args.solo and not estado.get("zips")):
        zips = etapa_descargar(fiel, token, cfg_egresos, tcfg, paquetes)
        if not zips:
            return 1
        estado["zips"] = [str(z) for z in zips]
        if args.solo == "descargar":
            return 0
        if not pausa("¿Extraer ZIPs?", args.sin_pausas):
            return 0
    else:
        zips = [Path(z) for z in estado["zips"]]
        print(f"\nℹ Reutilizando {len(zips)} ZIP(s)")

    # 4) Extraer
    if args.solo == "extraer" or (not args.solo and not estado.get("carpeta_xmls")):
        carpeta = etapa_extraer(tcfg, zips)
        if not carpeta:
            return 1
        estado["carpeta_xmls"] = str(carpeta)
        if args.solo == "extraer":
            return 0
        if not pausa("¿Procesar XMLs con procesar_todo?", args.sin_pausas):
            return 0
    else:
        carpeta = Path(estado["carpeta_xmls"])
        print(f"\nℹ Reutilizando carpeta de XMLs: {carpeta}")

    # 5) Procesar
    etapa_procesar(tcfg, carpeta)

    print("\n" + "=" * 64)
    print("  ✓ FLUJO COMPLETO")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())