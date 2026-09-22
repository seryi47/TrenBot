#!/usr/bin/env python3
"""Sube al repo los datos de la web, que es lo que dispara el despliegue.

Vercel está conectado a este repositorio: no hace falta ningún token ni
llamar a su CLI, basta con que el commit llegue a main.
"""
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
FICHEROS = ["historico.json", "avisos.json", os.path.join("web", "datos.json"),
            os.path.join("data", "ryanair_version.json"),
            os.path.join("data", "wizz_version.json"),
            os.path.join("data", "wizz_horarios.json")]


class _Fallo:
    returncode = 1
    stdout = stderr = ""


def git(*a):
    """Un git que nunca se queda colgado: si tarda, se da por fallido."""
    try:
        return subprocess.run(("git",) + a, cwd=RAIZ, capture_output=True,
                              text=True,
                              timeout=float(os.environ.get("GIT_TIMEOUT_S", "120")))
    except subprocess.TimeoutExpired:
        print("git %s tardó demasiado" % " ".join(a[:2]))
        return _Fallo()


def soltar_rebase_a_medias():
    """Un rebase interrumpido deja el repo bloqueado: a partir de ahí *todos*
    los commits fallan y la web se congela en silencio mientras el bot sigue
    avisando por Telegram, que es la avería más difícil de detectar. Si
    encontramos uno a medias, lo abortamos antes de seguir."""
    g = os.path.join(RAIZ, ".git")
    if any(os.path.exists(os.path.join(g, d)) for d in ("rebase-merge", "rebase-apply")):
        print("había un rebase a medias; lo aborto")
        git("rebase", "--abort")


def main():
    soltar_rebase_a_medias()
    hay = [f for f in FICHEROS if os.path.exists(os.path.join(RAIZ, f))]
    git("add", *hay)
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("sin cambios que publicar")
        return 0
    if git("commit", "-m", "chore: precios actualizados").returncode != 0:
        print("no se pudo commitear")
        return 1
    git("fetch", "origin", "main")
    if git("rebase", "origin/main").returncode != 0:
        git("rebase", "--abort")
        # Mismo caso que en run.py: estos JSON los tocan a la vez la nube y el
        # Mac, git no sabe fusionarlos y rendirse aquí dejaba la web congelada
        # durante horas. Son lecturas: la más reciente es la buena.
        print("conflicto al rebasar; rehago el commit sobre origin")
        guardados = {}
        for f in hay:
            try:
                with open(os.path.join(RAIZ, f), "rb") as fh:
                    guardados[f] = fh.read()
            except OSError:
                pass
        git("reset", "--hard", "origin/main")
        for f, datos in guardados.items():
            destino = os.path.join(RAIZ, f)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "wb") as fh:
                fh.write(datos)
        git("add", *hay)
        if git("commit", "-m", "chore: precios actualizados").returncode != 0:
            print("tras rehacerlo no quedaba nada que publicar")
            return 1
    if git("push", "origin", "main").returncode != 0:
        print("no se pudo subir")
        return 1
    print("publicado (Vercel desplegará solo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
