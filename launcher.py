#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==========================================
# SIGNATURE : Hub Education
# ==========================================
"""
NetProbe – Launcher
====================
Point d'entrée de l'application.
Vérifie les dépendances et l'environnement avant de lancer l'interface.

Usage :
  python launcher.py

Empaquetage en .exe (PyInstaller) :
  pip install pyinstaller
  pyinstaller --onefile --windowed --name NetProbe launcher.py
"""

import sys
import os
import platform


# ---------------------------------------------------------------------------
#  Vérification des dépendances
# ---------------------------------------------------------------------------

def check_python_version():
    """Vérifie que Python >= 3.10 est utilisé."""
    if sys.version_info < (3, 10):
        print(
            f"[ERREUR] Python 3.10 ou supérieur est requis.\n"
            f"         Version détectée : {platform.python_version()}\n"
            f"         Téléchargez Python sur : https://www.python.org/downloads/"
        )
        return False
    return True


def check_tkinter():
    """Vérifie que tkinter est disponible."""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        print(
            "[ERREUR] Le module 'tkinter' n'est pas installé.\n"
            "         Sous Windows : réinstallez Python en cochant 'tcl/tk'.\n"
            "         Sous Linux   : sudo apt install python3-tk\n"
            "         Sous macOS   : brew install python-tk"
        )
        return False


def check_standard_modules():
    """Vérifie que tous les modules de la bibliothèque standard sont présents."""
    modules_requis = [
        "csv", "ipaddress", "queue", "socket", "subprocess",
        "threading", "concurrent.futures", "datetime",
    ]
    manquants = []
    for mod in modules_requis:
        try:
            __import__(mod)
        except ImportError:
            manquants.append(mod)

    if manquants:
        print(
            f"[ERREUR] Modules manquants : {', '.join(manquants)}\n"
            f"         Votre installation Python semble incomplète."
        )
        return False
    return True


def check_os_tools():
    """Vérifie la disponibilité des commandes système (ping, msg)."""
    import subprocess

    warnings = []

    # Vérifier ping
    try:
        if os.name == "nt":
            cmd = ["ping", "-n", "1", "-w", "100", "127.0.0.1"]
            extra = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
        else:
            cmd = ["ping", "-c", "1", "-W", "1", "127.0.0.1"]
            extra = {}
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra
        )
    except FileNotFoundError:
        warnings.append("  ⚠ Commande 'ping' introuvable")

    # Vérifier msg (Windows uniquement)
    if os.name == "nt":
        try:
            subprocess.run(
                ["msg", "/?"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        except FileNotFoundError:
            warnings.append(
                "  ⚠ Commande 'msg' introuvable\n"
                "    → Windows Pro/Entreprise requis pour l'envoi de messages"
            )

    return warnings


def create_logs_directory():
    """Crée le dossier de logs s'il n'existe pas."""
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


# ---------------------------------------------------------------------------
#  Rapport de vérification
# ---------------------------------------------------------------------------

def run_checks():
    """Exécute toutes les vérifications. Renvoie True si tout est OK."""
    print("=" * 55)
    print("  NetProbe – Vérification des dépendances")
    print("=" * 55)
    print()

    all_ok = True

    # 1. Python
    print(f"  Python      : {platform.python_version()}", end="")
    if check_python_version():
        print("  ✓")
    else:
        print("  ✗")
        all_ok = False

    # 2. OS
    print(f"  Système     : {platform.system()} {platform.release()}", end="")
    print("  ✓")

    # 3. tkinter
    print("  tkinter     : ", end="")
    if check_tkinter():
        import tkinter
        print(f"{tkinter.TkVersion}  ✓")
    else:
        print("manquant  ✗")
        all_ok = False

    # 4. Modules standard
    print("  Modules std : ", end="")
    if check_standard_modules():
        print("complets  ✓")
    else:
        print("incomplets  ✗")
        all_ok = False

    # 5. Outils système
    print("  Outils OS   : ", end="")
    warnings = check_os_tools()
    if not warnings:
        print("OK  ✓")
    else:
        print("attention  ⚠")
        for w in warnings:
            print(w)

    # 6. Dossier logs
    logs_dir = create_logs_directory()
    print(f"  Dossier logs: {logs_dir}  ✓")

    print()

    if not all_ok:
        print("  ✗ Des dépendances sont manquantes. Corrigez les erreurs ci-dessus.")
        print()
        return False

    print("  ✓ Toutes les dépendances sont satisfaites.")
    print()
    return True


# ---------------------------------------------------------------------------
#  Lancement de l'application
# ---------------------------------------------------------------------------

def _show_error(msg: str):
    """Affiche une erreur via messagebox graphique ou console selon l'environnement."""
    print(f"\n[ERREUR] {msg}")
    try:
        import tkinter.messagebox as mb
        mb.showerror("NetProbe – Erreur", msg)
    except Exception:
        pass
    if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        try:
            input("\nAppuyez sur Entrée pour quitter...")
        except (EOFError, OSError):
            pass


def main():
    """Point d'entrée principal."""
    if not run_checks():
        _show_error("Certaines dépendances sont manquantes. Vérifiez la console.")
        sys.exit(1)

    # Importer et lancer l'application
    try:
        from menu import App
        print("  Lancement de l'interface…\n")
        app = App()
        app.mainloop()
    except Exception as e:
        _show_error(f"Impossible de lancer l'application :\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
