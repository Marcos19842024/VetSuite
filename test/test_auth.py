#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_auth.py
Pruebas manuales de autenticación, sesión, perfiles y usuarios.

Usa una carpeta temporal: NO toca el usuarios.json real.

Uso:
    python3 test/test_auth.py             # todas las pruebas
    python3 test/test_auth.py --verbose   # con detalle
    python3 test/test_auth.py --solo hash # solo un grupo
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Asegurar que la raíz del proyecto está en sys.path
_raiz = Path(__file__).resolve().parent.parent
if str(_raiz) not in sys.path:
    sys.path.insert(0, str(_raiz))


# ---------------------------------------------------------------
# Aislamiento: forzar carpeta temporal
# ---------------------------------------------------------------

_tmpdir = None


def _aislar():
    """Redirige USUARIOS_FILE a una carpeta temporal."""
    global _tmpdir
    _tmpdir = tempfile.mkdtemp(prefix="vet_suite_test_")
    os.environ["VET_SUITE_TEST_DIR"] = _tmpdir

    # Parchear core.usuarios antes de que se importe en cualquier sitio
    import core.usuarios as usuarios_mod
    usuarios_mod.USUARIOS_FILE = Path(_tmpdir) / "usuarios.json"

    # Asegurar que config_ui también use la carpeta temporal (por si acaso)
    import core.config_ui as config_ui_mod
    config_ui_mod.CONFIG_UI_FILE = Path(_tmpdir) / "config_ui.json"


def _limpiar():
    if _tmpdir and Path(_tmpdir).exists():
        shutil.rmtree(_tmpdir, ignore_errors=True)


# ---------------------------------------------------------------
# Mini framework de tests
# ---------------------------------------------------------------

class Runner:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.ok = 0
        self.fail = 0
        self.errores = []

    def check(self, cond, msg):
        if cond:
            self.ok += 1
            if self.verbose:
                print(f"    ✓ {msg}")
        else:
            self.fail += 1
            self.errores.append(msg)
            print(f"    ✗ {msg}")

    def grupo(self, nombre):
        print(f"\n[{nombre}]")


# ---------------------------------------------------------------
# Pruebas por grupo
# ---------------------------------------------------------------

def test_hash(r: Runner):
    r.grupo("hash de contraseñas")
    from core.auth import hashear_password, verificar_password, hash_es_valido

    h = hashear_password("Secreta123")
    r.check(hash_es_valido(h), "hash tiene formato válido")
    r.check(h.startswith("pbkdf2_sha256$600000$"), "prefijo y rondas correctos")

    h2 = hashear_password("Secreta123")
    r.check(h != h2, "dos hashes de la misma contraseña son distintos (salt)")

    r.check(verificar_password("Secreta123", h), "verifica correcto")
    r.check(not verificar_password("secreta123", h), "rechaza mayúsculas distintas")
    r.check(not verificar_password("Secreta124", h), "rechaza 1 char distinto")
    r.check(not verificar_password("", h), "rechaza vacío")
    r.check(not verificar_password("Secreta123", ""), "rechaza hash vacío")
    r.check(not verificar_password("Secreta123", "basura"), "rechaza hash basura")
    r.check(not verificar_password("Secreta123", "pbkdf2_sha256$1$x$y"), "rechaza hash mal formado")


def test_password_temporal(r: Runner):
    r.grupo("password temporal legible")
    from core.auth import generar_password_temporal

    vistos = set()
    fallos_local = []
    for _ in range(200):
        p = generar_password_temporal()
        if len(p) < 12:
            fallos_local.append(f"corta: {p!r}")
        if not (p[-1].isdigit() and p[-2].isdigit()):
            fallos_local.append(f"no termina en 2 dígitos: {p!r}")
        if p in vistos:
            fallos_local.append(f"colisión inmediata: {p!r}")
        vistos.add(p)

    r.check(not fallos_local, f"200 passwords, todas válidas ({len(vistos)} únicas)")
    if fallos_local:
        for f in fallos_local[:5]:
            print(f"      → {f}")


def test_crear_admin(r: Runner):
    r.grupo("crear admin inicial")
    from core import usuarios

    r.check(not usuarios.existe(), "usuarios.json no existe al inicio")

    usuario, password = usuarios.crear_admin_inicial("Admin Test")
    r.check(usuarios.existe(), "usuarios.json creado")
    r.check(usuario["id"] == "admin", "id = admin")
    r.check(usuario["perfil"] == "admin", "perfil = admin")
    r.check(usuario["activo"] is True, "activo = True")
    r.check(len(password) >= 12, "password temporal devuelta")
    r.check(usuario["password_hash"].startswith("pbkdf2_sha256$"), "hash guardado")

    # Reintento: debe fallar
    try:
        usuarios.crear_admin_inicial()
        r.check(False, "no debería permitir crear admin 2 veces")
    except FileExistsError:
        r.check(True, "rechaza crear admin si ya existe")


def test_crear_usuarios(r: Runner):
    r.grupo("crear y listar usuarios")
    from core import usuarios
    from core.auth import hashear_password

    h = hashear_password("clave123")
    u = usuarios.crear("luis", "Luis Pérez", "cajero", h)
    r.check(u["id"] == "luis", "id guardado")
    r.check(u["perfil"] == "cajero", "perfil guardado")
    r.check(u["activo"] is True, "activo por default")

    r.check(len(usuarios.listar()) == 2, "hay 2 usuarios")

    r.check(usuarios.obtener("luis") is not None, "obtener por id")
    r.check(usuarios.obtener("nadie") is None, "obtener inexistente = None")

    # ids inválidos
    for uid in ("Luis", "lu", "luis perez", "1luis", "luis-", "a" * 40, ""):
        try:
            usuarios.crear(uid, "X", "cajero", h)
            r.check(False, f"debería rechazar id {uid!r}")
        except ValueError:
            r.check(True, f"rechaza id inválido {uid!r}")

    # duplicado
    try:
        usuarios.crear("luis", "Otro", "cajero", h)
        r.check(False, "no debería permitir id duplicado")
    except ValueError:
        r.check(True, "rechaza id duplicado")


def test_actualizar_eliminar(r: Runner):
    r.grupo("actualizar y eliminar usuarios")
    from core import usuarios

    u = usuarios.actualizar("luis", nombre="Luis P.", perfil="medico")
    r.check(u["nombre"] == "Luis P.", "nombre actualizado")
    r.check(u["perfil"] == "medico", "perfil actualizado")

    try:
        usuarios.actualizar("luis", id="otro")
        r.check(False, "no debería permitir editar id")
    except ValueError:
        r.check(True, "rechaza editar campo id")

    try:
        usuarios.actualizar("nadie", nombre="X")
        r.check(False, "no debería permitir actualizar inexistente")
    except KeyError:
        r.check(True, "rechaza actualizar inexistente")

    usuarios.marcar_login("luis")
    u = usuarios.obtener("luis")
    r.check(u["ultimo_login"] is not None, "ultimo_login sellado")

    usuarios.eliminar("luis")
    r.check(usuarios.obtener("luis") is None, "eliminado")

    try:
        usuarios.eliminar("luis")
        r.check(False, "no debería permitir eliminar 2 veces")
    except KeyError:
        r.check(True, "rechaza eliminar inexistente")


def test_admins(r: Runner):
    r.grupo("regla: no quedar sin admins")
    from core import usuarios
    from core.auth import hashear_password

    h = hashear_password("x123456")
    usuarios.crear("ana", "Ana", "admin", h)
    usuarios.crear("beto", "Beto", "admin", h)

    r.check(len(usuarios.admins_activos()) == 3, "hay 3 admins activos")

    # Si quitamos a ana, quedarían 2
    r.check(usuarios.quedarian_admins_sin("ana") == 2, "quedarian_admins_sin(ana) = 2")

    # Desactivamos a beto, quedan 2 activos
    usuarios.actualizar("beto", activo=False)
    r.check(len(usuarios.admins_activos()) == 2, "beto desactivado, 2 admins")
    r.check(usuarios.quedarian_admins_sin("beto") == 2, "quedarian_admins_sin(beto) = 2")


def test_sesion(r: Runner):
    r.grupo("sesión en memoria")
    from core import sesion
    from core import usuarios

    r.check(not sesion.hay_sesion(), "sin sesión al inicio")
    r.check(sesion.actual() is None, "actual() = None")
    r.check(not sesion.es_admin(), "es_admin() = False sin sesión")

    admin = usuarios.obtener("admin")
    sesion.iniciar_sesion(admin)
    r.check(sesion.hay_sesion(), "hay sesión tras iniciar")
    r.check(sesion.actual().usuario_id == "admin", "usuario_id correcto")
    r.check(sesion.actual().perfil_id == "admin", "perfil_id correcto")
    r.check(sesion.es_admin(), "es_admin() = True")

    sesion.cerrar_sesion()
    r.check(not sesion.hay_sesion(), "sin sesión tras cerrar")

    # Campos faltantes
    try:
        sesion.iniciar_sesion({"id": "x"})
        r.check(False, "debería exigir nombre y perfil")
    except ValueError:
        r.check(True, "rechaza usuario sin campos")


def test_perfiles(r: Runner):
    r.grupo("perfiles y módulos permitidos")
    from core import sesion
    from shared.perfiles import (
        perfiles, perfil_por_id, perfil_actual, modulo_permitido,
        puede_configurar, ids_perfiles,
    )

    r.check(len(perfiles()) == 5, "hay 5 perfiles declarados")
    r.check("admin" in ids_perfiles(), "existe admin")
    for pid in ("admin", "contabilidad", "almacen", "cajero", "medico"):
        r.check(perfil_por_id(pid) is not None, f"existe perfil {pid}")

    # Sin sesión
    r.check(perfil_actual() is None, "sin sesión no hay perfil")
    r.check(not modulo_permitido("ingresos"), "sin sesión nada permitido")
    r.check(not puede_configurar(), "sin sesión no se configura")

    # Sesión admin
    sesion.iniciar_sesion({"id": "a", "nombre": "A", "perfil": "admin"})
    r.check(modulo_permitido("ingresos"), "admin ve ingresos")
    r.check(modulo_permitido("recordatorios"), "admin ve recordatorios")
    r.check(modulo_permitido("cualquier_cosa"), "admin ve todo")
    r.check(puede_configurar(), "admin configura")

    # Cajero
    sesion.iniciar_sesion({"id": "c", "nombre": "C", "perfil": "cajero"})
    r.check(modulo_permitido("estetica_transportes"), "cajero ve estética")
    r.check(modulo_permitido("recordatorios"), "cajero ve recordatorios")
    r.check(not modulo_permitido("ingresos"), "cajero NO ve ingresos")
    r.check(not modulo_permitido("egresos"), "cajero NO ve egresos")
    r.check(not puede_configurar(), "cajero NO configura")

    # Contabilidad
    sesion.iniciar_sesion({"id": "k", "nombre": "K", "perfil": "contabilidad"})
    r.check(modulo_permitido("ingresos"), "contabilidad ve ingresos")
    r.check(modulo_permitido("egresos"), "contabilidad ve egresos")
    r.check(not modulo_permitido("recordatorios"), "contabilidad NO ve recordatorios")

    # Médico
    sesion.iniciar_sesion({"id": "m", "nombre": "M", "perfil": "medico"})
    r.check(modulo_permitido("recordatorios"), "médico ve recordatorios")
    r.check(not modulo_permitido("ingresos"), "médico NO ve ingresos")

    sesion.cerrar_sesion()


def test_modulos_visibles(r: Runner):
    r.grupo("modulos_visibles() combina activo ∧ permitido")
    from core import sesion
    from core import config_ui
    from shared.registro_modulos import modulos_visibles, modulos_por_categoria

    ids = lambda ms: tuple(m.id for m in ms)

    # Sin sesión: nada visible
    sesion.cerrar_sesion()
    r.check(ids(modulos_visibles()) == (), "sin sesión: cero módulos")

    # Admin: todos los activos (todos por default)
    sesion.iniciar_sesion({"id": "a", "nombre": "A", "perfil": "admin"})
    todos = ids(modulos_visibles())
    r.check(set(todos) == {"ingresos", "egresos", "estetica_transportes", "recordatorios"},
            "admin ve los 4")

    # Admin desactiva estética en config
    config_ui.set_modulo_activo("estetica_transportes", False)
    visibles = ids(modulos_visibles())
    r.check("estetica_transportes" not in visibles, "estética desactivada, no visible")
    r.check("ingresos" in visibles, "ingresos sigue visible")

    # Cajero: solo los suyos, y estética está desactivada
    sesion.iniciar_sesion({"id": "c", "nombre": "C", "perfil": "cajero"})
    visibles_cajero = ids(modulos_visibles())
    r.check(visibles_cajero == ("recordatorios",),
            f"cajero solo ve recordatorios (estética desactivada): {visibles_cajero}")

    # Reactivamos estética
    config_ui.set_modulo_activo("estetica_transportes", True)
    visibles_cajero = ids(modulos_visibles())
    r.check(set(visibles_cajero) == {"estetica_transportes", "recordatorios"},
            f"cajero ve estética + recordatorios: {visibles_cajero}")

    # Categorías vacías desaparecen
    sesion.iniciar_sesion({"id": "m", "nombre": "M", "perfil": "medico"})
    cats = modulos_por_categoria()
    r.check("comunicacion" in cats, "médico: categoría comunicación presente")
    r.check("operacion" not in cats, "médico: categoría operación ausente")
    r.check("clientes" not in cats, "médico: categoría clientes ausente")

    sesion.cerrar_sesion()


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------

GRUPOS = {
    "hash":       [test_hash, test_password_temporal],
    "usuarios":   [test_crear_admin, test_crear_usuarios,
                   test_actualizar_eliminar, test_admins],
    "sesion":     [test_sesion, test_perfiles],
    "modulos":    [test_modulos_visibles],
}


def main():
    parser = argparse.ArgumentParser(description="Pruebas de auth/sesión/perfiles")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--solo", choices=list(GRUPOS.keys()),
                        help="Correr solo un grupo")
    args = parser.parse_args()

    print("=" * 64)
    print("PRUEBAS DE AUTENTICACIÓN, SESIÓN Y PERFILES")
    print(f"  carpeta temporal: {_tmpdir or '(por crear)'}")
    print("=" * 64)

    _aislar()

    # Forzar recreación del admin para cada grupo que lo necesite
    # (los grupos son secuenciales y comparten estado; ver nota abajo)
    r = Runner(verbose=args.verbose)

    grupos_a_correr = (
        {args.solo: GRUPOS[args.solo]} if args.solo else GRUPOS
    )

    # Orden importante: crear_admin debe ir primero
    for nombre, tests in grupos_a_correr.items():
        for t in tests:
            try:
                # Antes de test_crear_admin, borrar usuarios.json si existe
                if t is test_crear_admin:
                    from core import usuarios
                    if usuarios.existe():
                        usuarios.USUARIOS_FILE.unlink()
                # Después de test_modulos_visibles, dejar todo cerrado
                t(r)
            except Exception as e:
                r.fail += 1
                r.errores.append(f"{t.__name__} excepción: {e}")
                print(f"    ✗ {t.__name__} EXCEPCIÓN: {e}")
                import traceback
                traceback.print_exc()

    print("\n" + "=" * 64)
    total = r.ok + r.fail
    if r.fail == 0:
        print(f"✅ TODO OK — {r.ok} checks pasaron")
    else:
        print(f"❌ {r.fail} de {total} checks fallaron")
        for e in r.errores:
            print(f"   - {e}")
    print("=" * 64)

    _limpiar()
    sys.exit(0 if r.fail == 0 else 1)


if __name__ == "__main__":
    main()