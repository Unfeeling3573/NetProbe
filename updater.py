#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==========================================
# SIGNATURE : Hub Education
# ==========================================
"""
Module de mise à jour depuis un dépôt GitHub Privé
==================================================
Permet de se connecter à l'API GitHub d'un dépôt privé, de lister les releases
et de télécharger la dernière version du logiciel.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------------------------------------------------------
#  CONFIGURATION GITHUB
# ---------------------------------------------------------------------------
# Remplacez par vos informations de dépôt privé
GITHUB_OWNER = "Unfeeling3573"
GITHUB_REPO = "NetProbe"

# Fichier local de configuration pour conserver le Token (ou variable d'environnement)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "github_config.json")


def load_config() -> dict:
    """Charge la configuration locale (contient le token GitHub)."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"token": "", "repo": GITHUB_REPO, "owner": GITHUB_OWNER}


def save_config(config: dict):
    """Sauvegarde la configuration locale."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[ERREUR] Impossible de sauvegarder la configuration : {e}")


def get_github_releases(owner: str, repo: str, token: str) -> list[dict]:
    """Récupère la liste des releases d'un dépôt GitHub privé via l'API REST."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MSG-Windows-Updater",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Exception("Dépôt introuvable ou Token invalide (Erreur 404).")
        elif e.code == 401:
            raise Exception("Token GitHub invalide ou expiré (Erreur 401).")
        else:
            raise Exception(f"Erreur HTTP GitHub ({e.code}) : {e.reason}")
    except Exception as e:
        raise Exception(f"Impossible de contacter GitHub : {e}")

    return []


def download_asset(asset_url: str, token: str, destination_path: str, progress_callback=None):
    """Télécharge un fichier (asset) de release GitHub privé."""
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": "MSG-Windows-Updater",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(asset_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as response, open(destination_path, "wb") as out_file:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 8192

            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                downloaded += len(buffer)
                out_file.write(buffer)
                if progress_callback and total_size > 0:
                    progress_callback(downloaded, total_size)
    except Exception as e:
        raise Exception(f"Erreur lors du téléchargement : {e}")


# ---------------------------------------------------------------------------
#  INTERFACE GRAPHIQUE DÉDIÉE À LA MISE À JOUR
# ---------------------------------------------------------------------------

class UpdaterWindow(tk.Toplevel):
    """Fenêtre de sélection et téléchargement des versions depuis GitHub."""

    def __init__(self, parent, current_version="1.0.0"):
        super().__init__(parent)
        self.title("Mise à jour GitHub Privé – Hub Education")
        self.geometry("520x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.current_version = current_version
        self.config = load_config()
        self.releases = []

        self._build_ui()

    def _build_ui(self):
        # Configuration Token / Repo
        frame_config = ttk.LabelFrame(self, text="Paramètres GitHub Privé", padding=10)
        frame_config.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_config, text="Dépôt (Propriétaire/Nom) :").grid(row=0, column=0, sticky="w")
        self.entry_repo = ttk.Entry(frame_config, width=30)
        repo_str = f"{self.config.get('owner', GITHUB_OWNER)}/{self.config.get('repo', GITHUB_REPO)}"
        self.entry_repo.insert(0, repo_str)
        self.entry_repo.grid(row=0, column=1, sticky="w", padx=5)

        ttk.Label(frame_config, text="Token d'accès (PAT) :").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.entry_token = ttk.Entry(frame_config, width=30, show="*")
        self.entry_token.insert(0, self.config.get("token", ""))
        self.entry_token.grid(row=1, column=1, sticky="w", padx=5, pady=(5, 0))

        btn_fetch = ttk.Button(frame_config, text="🔄 Rechercher versions", command=self._fetch_releases)
        btn_fetch.grid(row=0, column=2, rowspan=2, padx=10, sticky="ns")

        # Liste des Releases
        frame_releases = ttk.LabelFrame(self, text="Versions disponibles sur GitHub", padding=10)
        frame_releases.pack(fill="both", expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(
            frame_releases,
            columns=("tag", "name", "date"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("tag", text="Version")
        self.tree.heading("name", text="Nom de la Release")
        self.tree.heading("date", text="Date")

        self.tree.column("tag", width=80, anchor="center")
        self.tree.column("name", width=260, anchor="w")
        self.tree.column("date", width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, side="left")

        scrollbar = ttk.Scrollbar(frame_releases, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        # Progression & Téléchargement
        frame_bottom = ttk.Frame(self, padding=10)
        frame_bottom.pack(fill="x")

        self.progress = ttk.Progressbar(frame_bottom, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 5))

        self.label_status = ttk.Label(frame_bottom, text=f"Version actuelle installée : v{self.current_version}")
        self.label_status.pack(side="left")

        btn_download = ttk.Button(frame_bottom, text="⬇️ Télécharger la version", command=self._download_selected)
        btn_download.pack(side="right")

    def _fetch_releases(self):
        """Récupère les releases depuis l'API GitHub."""
        repo_input = self.entry_repo.get().strip()
        token = self.entry_token.get().strip()

        if "/" not in repo_input:
            messagebox.showwarning("Attention", "Format du dépôt invalide (utilisez : proprio/depot).", parent=self)
            return

        owner, repo = repo_input.split("/", 1)

        # Sauvegarder la config
        self.config["owner"] = owner
        self.config["repo"] = repo
        self.config["token"] = token
        save_config(self.config)

        # Vider la liste
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.label_status.config(text="Connexion à GitHub…")
        self.update_idletasks()

        try:
            self.releases = get_github_releases(owner, repo, token)
            if not self.releases:
                messagebox.showinfo("Information", "Aucune version/release trouvée sur ce dépôt.", parent=self)
                self.label_status.config(text="Aucune release disponible.")
                return

            for rel in self.releases:
                tag = rel.get("tag_name", "v1.0")
                name = rel.get("name", "Sans nom")
                date = rel.get("published_at", "")[:10]
                self.tree.insert("", "end", values=(tag, name, date), iid=rel["id"])

            self.label_status.config(text=f"{len(self.releases)} version(s) disponible(s).")
        except Exception as e:
            messagebox.showerror("Erreur GitHub", str(e), parent=self)
            self.label_status.config(text="Erreur de connexion.")

    def _download_selected(self):
        """Télécharge la release sélectionnée."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Attention", "Veuillez sélectionner une version dans la liste.", parent=self)
            return

        rel_id = int(selected[0])
        rel_data = next((r for r in self.releases if r["id"] == rel_id), None)
        if not rel_data:
            return

        assets = rel_data.get("assets", [])
        if not assets:
            messagebox.showwarning("Attention", "Cette release ne contient aucun fichier d'installation (asset).", parent=self)
            return

        # Prendre le premier fichier disponible (ex: MSG_Windows_Setup.exe ou .zip)
        asset = assets[0]
        asset_url = asset["url"]  # URL API pour download binaire privé
        file_name = asset["name"]

        from tkinter import filedialog
        save_path = filedialog.asksaveasfilename(
            defaultextension=os.path.splitext(file_name)[1],
            initialfile=file_name,
            title="Enregistrer la nouvelle version",
            parent=self,
        )
        if not save_path:
            return

        def update_progress(downloaded, total):
            pct = int((downloaded / total) * 100)
            self.progress["value"] = pct
            self.label_status.config(text=f"Téléchargement : {pct}% ({downloaded // 1024} KB / {total // 1024} KB)")
            self.update_idletasks()

        token = self.config.get("token", "")
        try:
            self.label_status.config(text="Téléchargement en cours…")
            download_asset(asset_url, token, save_path, progress_callback=update_progress)
            messagebox.showinfo(
                "Succès",
                f"La version {rel_data.get('tag_name')} a été téléchargée avec succès dans :\n{save_path}",
                parent=self,
            )
            self.label_status.config(text="Téléchargement terminé !")
        except Exception as e:
            messagebox.showerror("Erreur de téléchargement", str(e), parent=self)
            self.label_status.config(text="Erreur lors du téléchargement.")


# ---------------------------------------------------------------------------
# Test direct du module
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    win = UpdaterWindow(root)
    root.mainloop()
