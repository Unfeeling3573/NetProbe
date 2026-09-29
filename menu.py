#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==========================================
# SIGNATURE : Hub Education
# ==========================================
"""
MSG Windows – Scanner réseau & envoi de messages Windows
=========================================================

Scanne une plage d'adresses IP (ping parallèle), puis envoie un message
Windows (commande `msg`) aux machines sélectionnées.

Prérequis pour que la commande `msg` fonctionne à distance :
  1. Le service « Messagerie réseau » (Messenger) doit être activé sur la
     machine cible (désactivé par défaut depuis Windows Vista).
     OU, sous Windows 10/11/Server, utiliser la clé de registre :
       HKLM\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server
       → AllowRemoteRPC = 1
  2. Le pare-feu Windows de la cible doit autoriser les connexions entrantes
     sur les ports RPC (TCP 135) et les ports dynamiques RPC.
  3. L'utilisateur exécutant ce script doit disposer de droits
     d'administration à distance sur la machine cible.
  4. Le service « Bureau à distance » ou « Services Bureau à distance »
     doit être activé sur la cible.

Empaquetage en .exe (PyInstaller) :
  pip install pyinstaller
  pyinstaller --onefile --windowed --name MSG_Windows msg_windows.py
"""

import csv
import ipaddress
import logging
import os
import queue
import socket
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---------------------------------------------------------------------------
#  Scanner – ping parallèle + résolution de noms d'hôte
# ---------------------------------------------------------------------------

class Scanner:
    """Scanne une plage IP par ping parallèle et résout les noms d'hôte."""

    # Drapeau Windows pour empêcher l'ouverture d'une fenêtre console
    # (disponible uniquement sous Windows ; vaut 0 sinon pour compatibilité)
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    def __init__(self, max_workers: int = 100):
        self.max_workers = max_workers
        self._stop_event = threading.Event()

    # -- méthodes publiques --------------------------------------------------

    def stop(self):
        """Demande l'arrêt du scan en cours."""
        self._stop_event.set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def scan(self, ip_start: str, ip_end: str, result_queue: queue.Queue):
        """Lance le scan de *ip_start* à *ip_end* (inclus).

        Chaque résultat est mis dans *result_queue* sous la forme :
            ("result", ip_str, hostname, status)
        En fin de scan :
            ("done",)
        Progression :
            ("progress", current, total)
        """
        self._stop_event.clear()

        start = int(ipaddress.IPv4Address(ip_start))
        end = int(ipaddress.IPv4Address(ip_end))
        total = end - start + 1
        ips = [str(ipaddress.IPv4Address(i)) for i in range(start, end + 1)]

        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._ping_host, ip): ip for ip in ips}

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    # Annuler les futures restantes
                    for f in futures:
                        f.cancel()
                    result_queue.put(("done",))
                    return

                ip = futures[future]
                try:
                    alive = future.result()
                except Exception:
                    alive = False

                hostname = self._resolve_hostname(ip) if alive else ""
                status = "En ligne" if alive else "Hors ligne"
                result_queue.put(("result", ip, hostname, status))

                completed += 1
                result_queue.put(("progress", completed, total))

        result_queue.put(("done",))

    # -- méthodes internes ---------------------------------------------------

    def _ping_host(self, ip: str) -> bool:
        """Ping une IP (1 paquet, timeout 500 ms). Renvoie True si joignable."""
        if self._stop_event.is_set():
            return False
        try:
            # Adapter la commande ping selon l'OS
            if os.name == "nt":
                # Windows : -n = nombre de paquets, -w = timeout en ms
                cmd = ["ping", "-n", "1", "-w", "500", ip]
                extra = {"creationflags": self._CREATE_NO_WINDOW}
            else:
                # macOS / Linux : -c = nombre de paquets, -W = timeout en s
                cmd = ["ping", "-c", "1", "-W", "1", ip]
                extra = {}

            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **extra,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _resolve_hostname(ip: str) -> str:
        """Résout le nom d'hôte d'une IP. Renvoie '' en cas d'échec."""
        old_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(1)
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except (socket.herror, socket.timeout, OSError):
            return ""
        finally:
            socket.setdefaulttimeout(old_timeout)


# ---------------------------------------------------------------------------
#  Messenger – envoi de messages Windows via la commande `msg`
# ---------------------------------------------------------------------------

class Messenger:
    """Envoie un message Windows (`msg`) à une liste de machines."""

    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    @staticmethod
    def send(ip: str, message: str) -> tuple[bool, str]:
        """Envoie *message* à la machine *ip* via `msg`.

        Retourne (succès: bool, détail: str).
        """
        try:
            result = subprocess.run(
                ["msg", "*", f"/SERVER:{ip}", "/TIME:60", message],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            if result.returncode == 0:
                return True, "Message envoyé"
            else:
                stderr = result.stderr.decode("cp850", errors="replace").strip()
                return False, stderr or f"Code retour {result.returncode}"
        except subprocess.TimeoutExpired:
            return True, "Commande expirée (timeout 10 s)"
        except FileNotFoundError:
            return False, "Commande 'msg' introuvable (Windows Pro/Entreprise requis)"
        except Exception as e:
            return False, str(e)


# ---------------------------------------------------------------------------
#  App – interface graphique principale (tkinter + ttk)
# ---------------------------------------------------------------------------

class App(tk.Tk):
    """Fenêtre principale de l'application."""

    # Caractère utilisé pour simuler une case à cocher dans le Treeview
    CHECK_ON = "☑"
    CHECK_OFF = "☐"

    def __init__(self):
        super().__init__()
        self.title("Couteau suisse réseau")
        self.geometry("900x750")
        self.minsize(750, 600)

        self.scanner = Scanner()
        self.messenger = Messenger()
        self._queue: queue.Queue = queue.Queue()
        self._scan_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._all_results: list[tuple[str, str, str, str, str]] = []  # (check, machine, ip, hostname, status)
        self._filter_online = False  # True = afficher uniquement « En ligne »

        # -- Tracker réseau -------------------------------------------------
        self._tracker_running = False
        self._tracker_stop = threading.Event()
        self._tracker_known: set[tuple[str, str, str, str, str]] = set()  # (proto, local, port_l, remote, port_r)

        # -- Logger fichier (dossier logs/) ---------------------------------
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_filename = datetime.now().strftime("session_%Y%m%d_%H%M%S.log")
        log_path = os.path.join(logs_dir, log_filename)

        self._file_logger = logging.getLogger("msg_windows")
        self._file_logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        self._file_logger.addHandler(handler)
        self._file_logger.info("Session démarrée")

        self._build_ui()
        self._poll_queue()

    # ======================================================================
    #  Construction de l'interface
    # ======================================================================

    def _build_ui(self):
        # -- En-tête (Menu principal) ---------------------------------------
        header_frame = ttk.Frame(self, relief="raised", borderwidth=1)
        header_frame.pack(fill="x", padx=0, pady=0)

        # Création du bouton menu
        self.btn_menu = ttk.Menubutton(header_frame, text="☰ Menu Outils")
        self.btn_menu.pack(side="left", padx=4, pady=4)

        # Création du menu déroulant
        menu = tk.Menu(self.btn_menu, tearoff=0)
        menu.add_command(label="🔔 Ping", command=self._tool_ping)
        menu.add_command(label="🔀 Traceroute", command=self._tool_traceroute)
        menu.add_command(label="🔍 Nslookup", command=self._tool_nslookup)
        menu.add_separator()
        menu.add_command(label="🌐 Infos réseau", command=self._tool_network_info)
        menu.add_command(label="📡 Netstat", command=self._tool_netstat)
        menu.add_command(label="🛡️ Scan Proxy / Kwartz", command=self._tool_proxy_scan)
        menu.add_command(label="📊 Tracker réseau (Démarrer/Arrêter)", command=self._toggle_tracker_from_menu)
        menu.add_command(label="⏻ Arrêt distant", command=self._tool_remote_shutdown)
        menu.add_separator()
        menu.add_command(label="📄 Exporter CSV", command=self._export_csv)
        menu.add_command(label="🧹 Vider journal", command=self._clear_log)
        menu.add_separator()
        menu.add_command(label="ℹ️ À propos", command=self._show_about)

        # Assigner le menu au bouton
        self.btn_menu["menu"] = menu

        # Pour changer dynamiquement le texte du tracker si besoin (optionnel)
        self._tracker_menu_index = 7  # Index de la commande dans le menu

        # -- Cadre scan -----------------------------------------------------
        frame_scan = ttk.LabelFrame(self, text="Scan de plage IP", padding=8)
        frame_scan.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(frame_scan, text="IP de début :").grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        self.entry_ip_start = ttk.Entry(frame_scan, width=18)
        self.entry_ip_start.grid(row=0, column=1, padx=(0, 10))
        self.entry_ip_start.insert(0, "192.168.1.1")

        ttk.Label(frame_scan, text="IP de fin :").grid(
            row=0, column=2, sticky="w", padx=(0, 4)
        )
        self.entry_ip_end = ttk.Entry(frame_scan, width=18)
        self.entry_ip_end.grid(row=0, column=3, padx=(0, 10))
        self.entry_ip_end.insert(0, "192.168.1.254")

        self.btn_scan = ttk.Button(
            frame_scan, text="🔍 Scanner", command=self._on_scan
        )
        self.btn_scan.grid(row=0, column=4, padx=4)

        self.btn_stop = ttk.Button(
            frame_scan, text="⛔ Arrêter", command=self._on_stop, state="disabled"
        )
        self.btn_stop.grid(row=0, column=5, padx=4)

        self.progress = ttk.Progressbar(frame_scan, mode="determinate")
        self.progress.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(8, 0))

        self.label_progress = ttk.Label(frame_scan, text="")
        self.label_progress.grid(row=2, column=0, columnspan=6, sticky="w")

        frame_scan.columnconfigure(4, weight=1)

        # -- Treeview résultats ---------------------------------------------
        frame_tree = ttk.LabelFrame(self, text="Résultats", padding=8)
        frame_tree.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("check", "machine", "ip", "hostname", "status")
        self.tree = ttk.Treeview(
            frame_tree, columns=columns, show="headings", selectmode="none",
            displaycolumns=("check", "machine", "status"),  # Cacher ip et hostname bruts
        )
        self.tree.heading("check", text="✓")
        self.tree.heading("machine", text="Machine")
        self.tree.heading("ip", text="IP")
        self.tree.heading("hostname", text="Nom d'hôte")
        self.tree.heading("status", text="Statut")

        self.tree.column("check", width=40, anchor="center", stretch=False)
        self.tree.column("machine", width=350, anchor="w")
        self.tree.column("ip", width=0, stretch=False)
        self.tree.column("hostname", width=0, stretch=False)
        self.tree.column("status", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(frame_tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Clic sur une ligne = basculer la case à cocher
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # -- Boutons de sélection & export ----------------------------------
        frame_btns = ttk.Frame(self)
        frame_btns.pack(fill="x", padx=10, pady=2)

        ttk.Button(
            frame_btns, text="Tout sélectionner", command=self._select_all
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            frame_btns, text="Tout désélectionner", command=self._deselect_all
        ).pack(side="left", padx=(0, 4))

        self.btn_filter = ttk.Button(
            frame_btns, text="🟢 Filtrer : En ligne", command=self._toggle_filter
        )
        self.btn_filter.pack(side="left", padx=(0, 4))

        ttk.Button(
            frame_btns, text="📄 Exporter CSV", command=self._export_csv
        ).pack(side="right")

        # -- Cadre message --------------------------------------------------
        frame_msg = ttk.LabelFrame(self, text="Envoi de message", padding=8)
        frame_msg.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_msg, text="Message :").pack(anchor="w")
        self.text_message = tk.Text(frame_msg, height=3, wrap="word")
        self.text_message.pack(fill="x", pady=(2, 6))

        self.btn_send = ttk.Button(
            frame_msg, text="📨 Envoyer", command=self._on_send
        )
        self.btn_send.pack(anchor="e")

        # -- Journal --------------------------------------------------------
        frame_log = ttk.LabelFrame(self, text="Journal", padding=8)
        frame_log.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log = scrolledtext.ScrolledText(
            frame_log, height=6, state="disabled", wrap="word"
        )
        self.log.pack(fill="both", expand=True)

        # Tags pour colorer le journal
        self.log.tag_configure("ok", foreground="green")
        self.log.tag_configure("err", foreground="red")
        self.log.tag_configure("info", foreground="blue")

    # ======================================================================
    #  Boucle de traitement de la file (communication threads → UI)
    # ======================================================================

    def _poll_queue(self):
        """Vérifie la file toutes les 50 ms et met à jour l'interface."""
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]

                if kind == "result":
                    _, ip, hostname, status = msg
                    check = self.CHECK_ON if status == "En ligne" else self.CHECK_OFF
                    
                    machine = f"{hostname} ({ip})" if hostname else ip
                    
                    # Stocker tous les résultats avec la nouvelle colonne 'machine'
                    self._all_results.append((check, machine, ip, hostname, status))
                    # N'afficher que si le filtre le permet
                    if not self._filter_online or status == "En ligne":
                        self.tree.insert(
                            "", "end",
                            values=(check, machine, ip, hostname, status),
                        )

                elif kind == "progress":
                    _, current, total = msg
                    self.progress["maximum"] = total
                    self.progress["value"] = current
                    self.label_progress.config(
                        text=f"{current}/{total} adresses scannées"
                    )

                elif kind == "done":
                    self.btn_scan.config(state="normal")
                    self.btn_stop.config(state="disabled")
                    self._log("Scan terminé.", tag="info")

                elif kind == "send_ok":
                    _, ip, detail = msg
                    self._log(f"[{ip}] ✓ {detail}", tag="ok")

                elif kind == "send_err":
                    _, ip, detail = msg
                    self._log(f"[{ip}] ✗ {detail}", tag="err")

                elif kind == "send_done":
                    self.btn_send.config(state="normal")
                    self._log("Envoi terminé.", tag="info")

                # Messages génériques (outils réseau, proxy scan)
                elif kind == "log_info":
                    self._log(msg[1], tag="info")

                elif kind == "log_ok":
                    self._log(msg[1], tag="ok")

                elif kind == "log":
                    self._log(msg[1])

        except queue.Empty:
            pass
        finally:
            self.after(50, self._poll_queue)

    # ======================================================================
    #  Validation
    # ======================================================================

    def _validate_range(self) -> tuple[str, str] | None:
        """Valide les champs IP. Renvoie (ip_start, ip_end) ou None."""
        raw_start = self.entry_ip_start.get().strip()
        raw_end = self.entry_ip_end.get().strip()

        # Vérification de la validité des adresses
        try:
            ip_start = ipaddress.IPv4Address(raw_start)
        except (ipaddress.AddressValueError, ValueError):
            messagebox.showerror(
                "Erreur", f"L'adresse IP de début est invalide :\n{raw_start}"
            )
            return None

        try:
            ip_end = ipaddress.IPv4Address(raw_end)
        except (ipaddress.AddressValueError, ValueError):
            messagebox.showerror(
                "Erreur", f"L'adresse IP de fin est invalide :\n{raw_end}"
            )
            return None

        # Vérification de l'ordre
        if ip_start > ip_end:
            messagebox.showerror(
                "Erreur",
                "La plage est inversée : l'adresse de début doit être "
                "inférieure ou égale à l'adresse de fin.",
            )
            return None

        # Vérification de la taille
        count = int(ip_end) - int(ip_start) + 1
        if count > 1024:
            ok = messagebox.askyesno(
                "Confirmation",
                f"La plage contient {count} adresses (> 1 024).\n"
                "Le scan peut prendre du temps. Continuer ?",
            )
            if not ok:
                return None

        return str(ip_start), str(ip_end)

    # ======================================================================
    #  Callbacks
    # ======================================================================

    # -- Scan ---------------------------------------------------------------

    def _on_scan(self):
        result = self._validate_range()
        if result is None:
            return

        ip_start, ip_end = result

        # Réinitialiser l'interface et les données
        self._all_results.clear()
        self._filter_online = False
        self.btn_filter.config(text="🟢 Filtrer : En ligne")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.progress["value"] = 0
        self.label_progress.config(text="")

        self.btn_scan.config(state="disabled")
        self.btn_stop.config(state="normal")

        self.scanner = Scanner()
        self._log(f"Scan de {ip_start} à {ip_end}…", tag="info")

        self._scan_thread = threading.Thread(
            target=self.scanner.scan,
            args=(ip_start, ip_end, self._queue),
            daemon=True,
        )
        self._scan_thread.start()

    def _on_stop(self):
        self.scanner.stop()
        self.btn_stop.config(state="disabled")
        self._log("Arrêt du scan demandé…", tag="info")

    # -- Cases à cocher (Treeview) ------------------------------------------

    def _on_tree_click(self, event):
        """Bascule la case à cocher de la ligne cliquée."""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        values = list(self.tree.item(item, "values"))
        values[0] = self.CHECK_OFF if values[0] == self.CHECK_ON else self.CHECK_ON
        self.tree.item(item, values=values)
        # Synchroniser dans _all_results
        ip = values[2]
        for i, (c, m, r_ip, h, s) in enumerate(self._all_results):
            if r_ip == ip:
                self._all_results[i] = (values[0], m, r_ip, h, s)
                break

    def _select_all(self):
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = self.CHECK_ON
            self.tree.item(item, values=values)
        # Synchroniser dans _all_results
        self._sync_checks_to_results()

    def _deselect_all(self):
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = self.CHECK_OFF
            self.tree.item(item, values=values)
        # Synchroniser dans _all_results
        self._sync_checks_to_results()

    # -- Filtre : En ligne --------------------------------------------------

    def _toggle_filter(self):
        """Bascule l'affichage entre tous les résultats et les machines en ligne."""
        # Avant de basculer, synchroniser les cases à cocher actuelles
        self._sync_checks_to_results()
        self._filter_online = not self._filter_online
        if self._filter_online:
            self.btn_filter.config(text="📋 Afficher tout")
        else:
            self.btn_filter.config(text="🟢 Filtrer : En ligne")
        self._refresh_tree()

    def _refresh_tree(self):
        """Reconstruit le Treeview à partir de _all_results selon le filtre actif."""
        for item in self.tree.get_children():
            self.tree.delete(item)
        for check, machine, ip, hostname, status in self._all_results:
            if self._filter_online and status != "En ligne":
                continue
            self.tree.insert(
                "", "end",
                values=(check, machine, ip, hostname, status),
            )

    def _sync_checks_to_results(self):
        """Synchronise l'état des cases du Treeview vers _all_results."""
        # Construire un dict IP → état de la case depuis le Treeview affiché
        displayed = {}
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            displayed[values[2]] = values[0]  # ip → check
        # Mettre à jour _all_results
        for i, (check, machine, ip, hostname, status) in enumerate(self._all_results):
            if ip in displayed:
                self._all_results[i] = (displayed[ip], machine, ip, hostname, status)

    # -- Envoi de message ---------------------------------------------------

    def _on_send(self):
        message = self.text_message.get("1.0", "end").strip()
        if not message:
            messagebox.showwarning("Attention", "Le message est vide.")
            return

        # Collecter les IP cochées
        selected_ips: list[str] = []
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if values[0] == self.CHECK_ON:
                selected_ips.append(values[2])

        if not selected_ips:
            messagebox.showwarning(
                "Attention", "Aucune machine n'est sélectionnée."
            )
            return

        ok = messagebox.askyesno(
            "Confirmation",
            f"Envoyer le message à {len(selected_ips)} machine(s) ?",
        )
        if not ok:
            return

        self.btn_send.config(state="disabled")
        self._log(
            f"Envoi du message à {len(selected_ips)} machine(s)…", tag="info"
        )

        self._send_thread = threading.Thread(
            target=self._send_messages,
            args=(selected_ips, message),
            daemon=True,
        )
        self._send_thread.start()

    def _send_messages(self, ips: list[str], message: str):
        """Envoie le message à chaque IP (exécuté dans un thread)."""
        for ip in ips:
            success, detail = self.messenger.send(ip, message)
            if success:
                self._queue.put(("send_ok", ip, detail))
            else:
                self._queue.put(("send_err", ip, detail))
        self._queue.put(("send_done",))

    # -- Export CSV ---------------------------------------------------------

    def _export_csv(self):
        children = self.tree.get_children()
        if not children:
            messagebox.showinfo("Information", "Aucun résultat à exporter.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("Fichiers CSV", "*.csv"), ("Tous les fichiers", "*.*")],
            title="Exporter les résultats",
            initialfile=f"scan_{datetime.now():%Y%m%d_%H%M%S}.csv",
        )
        if not filepath:
            return

        try:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Sélectionné", "IP", "Nom d'hôte", "Statut"])
                for item in children:
                    values = self.tree.item(item, "values")
                    selected = "Oui" if values[0] == self.CHECK_ON else "Non"
                    writer.writerow([selected, values[2], values[3], values[4]])
            self._log(f"Résultats exportés dans : {filepath}", tag="info")
        except OSError as e:
            messagebox.showerror("Erreur", f"Impossible d'écrire le fichier :\n{e}")

    # -- Journal ------------------------------------------------------------

    def _log(self, text: str, tag: str = ""):
        """Ajoute une entrée horodatée dans le journal + fichier log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", f"[{timestamp}] {text}\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")
        # Écrire aussi dans le fichier log
        self._file_logger.info(text)

    def _clear_log(self):
        """Vide le journal."""
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # ======================================================================
    #  Outils réseau (menu Outils)
    # ======================================================================

    def _ask_ip_or_host(self, title: str, label: str = "Adresse IP ou nom d'hôte :") -> str | None:
        """Ouvre une boîte de dialogue simple pour saisir une IP ou un nom d'hôte."""
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("380x120")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        result = {"value": None}

        ttk.Label(dialog, text=label).pack(padx=10, pady=(10, 4), anchor="w")
        entry = ttk.Entry(dialog, width=40)
        entry.pack(padx=10, pady=(0, 10))
        entry.focus_set()

        def on_ok(_event=None):
            val = entry.get().strip()
            if val:
                result["value"] = val
            dialog.destroy()

        entry.bind("<Return>", on_ok)
        ttk.Button(dialog, text="OK", command=on_ok).pack(pady=(0, 10))
        self.wait_window(dialog)
        return result["value"]

    def _run_tool_in_log(self, title: str, cmd: list[str]):
        """Exécute une commande réseau et affiche le résultat dans le journal."""
        self._log(f"── {title} ──", tag="info")
        _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        tool_queue: queue.Queue = queue.Queue()

        def run():
            try:
                extra = {"creationflags": _CREATE_NO_WINDOW} if os.name == "nt" else {}
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    **extra,
                )
                for line in proc.stdout:
                    tool_queue.put(line.rstrip("\n\r"))
                proc.wait()
                tool_queue.put(None)
            except FileNotFoundError:
                tool_queue.put(f"[Erreur] Commande introuvable : {cmd[0]}")
                tool_queue.put(None)
            except Exception as e:
                tool_queue.put(f"[Erreur] {e}")
                tool_queue.put(None)

        def poll():
            try:
                while True:
                    line = tool_queue.get_nowait()
                    if line is None:
                        self._log(f"── Fin : {title} ──", tag="info")
                        return
                    self._log(line)
            except queue.Empty:
                pass
            self.after(50, poll)

        threading.Thread(target=run, daemon=True).start()
        poll()

    def _tool_ping(self):
        """Outil : Ping une adresse."""
        target = self._ask_ip_or_host("Ping")
        if not target:
            return
        if os.name == "nt":
            cmd = ["ping", "-n", "4", "-w", "1000", target]
        else:
            cmd = ["ping", "-c", "4", "-W", "1", target]
        self._run_tool_in_log(f"Ping – {target}", cmd)

    def _tool_traceroute(self):
        """Outil : Traceroute vers une adresse."""
        target = self._ask_ip_or_host("Traceroute")
        if not target:
            return
        if os.name == "nt":
            cmd = ["tracert", "-d", "-w", "1000", target]
        else:
            cmd = ["traceroute", "-n", "-w", "1", target]
        self._run_tool_in_log(f"Traceroute – {target}", cmd)

    def _tool_nslookup(self):
        """Outil : Résolution DNS (nslookup)."""
        target = self._ask_ip_or_host("Nslookup", "Nom d'hôte ou adresse IP :")
        if not target:
            return
        cmd = ["nslookup", target]
        self._run_tool_in_log(f"Nslookup – {target}", cmd)

    def _tool_network_info(self):
        """Outil : Affiche les informations réseau locales."""
        if os.name == "nt":
            cmd = ["ipconfig", "/all"]
        else:
            cmd = ["ifconfig"]
        self._run_tool_in_log("Infos réseau local", cmd)

    def _tool_netstat(self):
        """Outil : Affiche les connexions et ports ouverts."""
        if os.name == "nt":
            cmd = ["netstat", "-an"]
        else:
            cmd = ["netstat", "-an"]
        self._run_tool_in_log("Ports ouverts – Netstat", cmd)

    # ======================================================================
    #  Scan Proxy / Kwartz
    # ======================================================================

    # Ports proxy courants avec leur description
    PROXY_PORTS = {
        80:    "HTTP",
        443:   "HTTPS",
        1080:  "SOCKS",
        3128:  "Squid / Kwartz",
        3129:  "Squid (alt)",
        3130:  "Squid (alt)",
        8080:  "HTTP Proxy",
        8443:  "HTTPS Proxy",
        8888:  "HTTP Proxy (alt)",
        9090:  "Proxy / Web admin",
        9091:  "Proxy (alt)",
        # Ports spécifiques Kwartz
        10000: "Webmin (Kwartz)",
        389:   "LDAP (Kwartz)",
        636:   "LDAPS (Kwartz)",
        445:   "SMB (Kwartz)",
        139:   "NetBIOS (Kwartz)",
        4242:  "Kwartz admin",
    }

    def _tool_proxy_scan(self):
        """Outil : Scanner les proxy / Kwartz sur une adresse ou la plage scannée."""
        # Proposer de scanner une IP ou toutes les machines en ligne
        dialog = tk.Toplevel(self)
        dialog.title("Scan Proxy / Kwartz")
        dialog.geometry("420x200")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        result = {"mode": None, "ip": None}

        ttk.Label(dialog, text="Scanner les ports proxy et détecter Kwartz",
                  font=("", 11, "bold")).pack(padx=10, pady=(10, 8))

        # Option 1 : IP unique
        frame_ip = ttk.Frame(dialog)
        frame_ip.pack(fill="x", padx=10, pady=4)
        ttk.Label(frame_ip, text="Adresse IP :").pack(side="left")
        entry_ip = ttk.Entry(frame_ip, width=20)
        entry_ip.pack(side="left", padx=(6, 6))

        def on_scan_single():
            ip = entry_ip.get().strip()
            if ip:
                result["mode"] = "single"
                result["ip"] = ip
            dialog.destroy()

        ttk.Button(frame_ip, text="Scanner", command=on_scan_single).pack(side="left")
        entry_ip.bind("<Return>", lambda _: on_scan_single())

        # Séparateur
        ttk.Separator(dialog, orient="horizontal").pack(fill="x", padx=10, pady=8)

        # Option 2 : Toutes les machines en ligne
        online_count = sum(1 for _, _, _, _, s in self._all_results if s == "En ligne")

        def on_scan_all():
            result["mode"] = "all"
            dialog.destroy()

        btn_all = ttk.Button(
            dialog,
            text=f"Scanner les {online_count} machine(s) en ligne",
            command=on_scan_all,
        )
        btn_all.pack(pady=4)
        if online_count == 0:
            btn_all.config(state="disabled")

        self.wait_window(dialog)

        if result["mode"] is None:
            return

        if result["mode"] == "single":
            ips = [result["ip"]]
        else:
            ips = [ip for _, _, ip, _, s in self._all_results if s == "En ligne"]

        # Lancer le scan dans un thread
        self._log("── Scan Proxy / Kwartz ──", tag="info")
        threading.Thread(
            target=self._proxy_scan_worker,
            args=(ips,),
            daemon=True,
        ).start()

    def _proxy_scan_worker(self, ips: list[str]):
        """Scanne les ports proxy sur les IPs données (thread secondaire)."""
        for ip in ips:
            self._queue.put(("log_info", f"Scan proxy de {ip}…"))
            open_ports = []
            is_kwartz = False

            # Scanner les ports en parallèle
            with ThreadPoolExecutor(max_workers=30) as executor:
                futures = {
                    executor.submit(self._check_port, ip, port): (port, desc)
                    for port, desc in self.PROXY_PORTS.items()
                }
                for future in as_completed(futures):
                    port, desc = futures[future]
                    try:
                        is_open, banner = future.result()
                    except Exception:
                        is_open, banner = False, ""
                    if is_open:
                        open_ports.append((port, desc, banner))

            # Trier par numéro de port
            open_ports.sort(key=lambda x: x[0])

            # Détecter Kwartz : présence de ports caractéristiques
            kwartz_ports = {3128, 10000, 389, 445}
            ports_ouverts_set = {p for p, _, _ in open_ports}
            kwartz_score = len(kwartz_ports & ports_ouverts_set)
            if kwartz_score >= 2:
                is_kwartz = True

            # Vérifier aussi les bannières pour Kwartz
            for port, desc, banner in open_ports:
                if "kwartz" in banner.lower():
                    is_kwartz = True

            # Résultats
            if open_ports:
                for port, desc, banner in open_ports:
                    info = f"  Port {port:>5} ({desc}) : OUVERT"
                    if banner:
                        info += f"  │ {banner}"
                    self._queue.put(("log_ok", info))
            else:
                self._queue.put(("log", f"  Aucun port proxy ouvert sur {ip}"))

            # Verdict Kwartz
            if is_kwartz:
                self._queue.put(("log_ok",
                    f"  🛡️ {ip} → KWARTZ DÉTECTÉ "
                    f"(score: {kwartz_score}/{len(kwartz_ports)} ports caractéristiques)"
                ))
            elif ports_ouverts_set & {3128, 8080, 8888}:
                self._queue.put(("log_ok", f"  🔄 {ip} → Proxy détecté (non-Kwartz)"))

            # Tenter d'identifier le proxy via HTTP
            proxy_type = self._identify_proxy_http(ip, open_ports)
            if proxy_type:
                self._queue.put(("log_ok", f"  📋 Type identifié : {proxy_type}"))

        self._queue.put(("log_info", "── Fin : Scan Proxy / Kwartz ──"))

    @staticmethod
    def _check_port(ip: str, port: int, timeout: float = 1.5) -> tuple[bool, str]:
        """Teste si un port est ouvert et récupère la bannière."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
            # Tenter de lire une bannière
            banner = ""
            try:
                sock.settimeout(1)
                # Envoyer une requête HTTP minimale pour les ports web/proxy
                if port in (80, 443, 3128, 8080, 8443, 8888, 9090, 10000):
                    sock.sendall(b"HEAD / HTTP/1.0\r\nHost: test\r\n\r\n")
                data = sock.recv(512)
                banner = data.decode("utf-8", errors="replace").split("\r\n")[0].strip()
                if len(banner) > 80:
                    banner = banner[:80] + "…"
            except (socket.timeout, OSError):
                pass
            sock.close()
            return True, banner
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False, ""

    @staticmethod
    def _identify_proxy_http(ip: str, open_ports: list[tuple[int, str, str]]) -> str:
        """Identifie le type de proxy à partir des bannières HTTP."""
        for port, desc, banner in open_ports:
            banner_lower = banner.lower()
            if "kwartz" in banner_lower:
                return "Kwartz"
            if "squid" in banner_lower:
                return "Squid"
            if "apache" in banner_lower:
                return "Apache (mod_proxy)"
            if "nginx" in banner_lower:
                return "Nginx (reverse proxy)"
            if "microsoft" in banner_lower and "isa" in banner_lower:
                return "Microsoft ISA Server"
            if "tinyproxy" in banner_lower:
                return "TinyProxy"
            if "privoxy" in banner_lower:
                return "Privoxy"
            if "ccproxy" in banner_lower:
                return "CCProxy"
            if "wingate" in banner_lower:
                return "WinGate"
            if "argo" in banner_lower or "cloudflare" in banner_lower:
                return "Cloudflare Tunnel"
        return ""

    # ======================================================================
    #  Arrêt / Redémarrage distant
    # ======================================================================

    @staticmethod
    def _resolve_host(host: str) -> tuple[str, str]:
        """Résout un nom d'hôte ou une IP. Renvoie (ip, nom_affiché).

        Accepte une IP ou un nom DNS.
        """
        host = host.strip()
        if not host:
            return "", ""

        # Vérifier si c'est déjà une IP valide
        try:
            ipaddress.IPv4Address(host)
            # C'est une IP, tenter la résolution inverse
            try:
                socket.setdefaulttimeout(1)
                hostname, _, _ = socket.gethostbyaddr(host)
                return host, f"{host} ({hostname})"
            except (socket.herror, socket.timeout, OSError):
                return host, host
            finally:
                socket.setdefaulttimeout(None)
        except (ipaddress.AddressValueError, ValueError):
            pass

        # C'est un nom d'hôte, résoudre en IP
        try:
            socket.setdefaulttimeout(2)
            ip = socket.gethostbyname(host)
            return ip, f"{host} → {ip}"
        except (socket.gaierror, socket.timeout, OSError):
            return "", f"{host} (résolution DNS échouée)"
        finally:
            socket.setdefaulttimeout(None)

    def _tool_remote_shutdown(self):
        """Ouvre la fenêtre d'arrêt / redémarrage distant."""
        win = tk.Toplevel(self)
        win.title("Arrêt / Redémarrage distant")
        win.geometry("550x520")
        win.resizable(True, True)
        win.transient(self)

        # -- Liste des machines cibles --------------------------------------
        frame_targets = ttk.LabelFrame(win, text="Machines cibles (IP ou nom d'hôte)", padding=8)
        frame_targets.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        # Listbox avec scrollbar
        frame_list = ttk.Frame(frame_targets)
        frame_list.pack(fill="both", expand=True)

        listbox = tk.Listbox(frame_list, height=8, selectmode="extended")
        scrollbar = ttk.Scrollbar(frame_list, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Boutons d'ajout
        frame_add = ttk.Frame(frame_targets)
        frame_add.pack(fill="x", pady=(6, 0))

        entry_host = ttk.Entry(frame_add, width=25)
        entry_host.pack(side="left", padx=(0, 4))
        entry_host.insert(0, "IP ou nom d'hôte")
        entry_host.bind("<FocusIn>", lambda e: (
            entry_host.delete(0, "end") if entry_host.get() == "IP ou nom d'hôte" else None
        ))

        def add_host(_event=None):
            host = entry_host.get().strip()
            if host and host != "IP ou nom d'hôte":
                # Accepter plusieurs entrées séparées par des virgules ou espaces
                for h in host.replace(",", " ").split():
                    h = h.strip()
                    if h:
                        ip, label = self._resolve_host(h)
                        if ip:
                            listbox.insert("end", label)
                        else:
                            listbox.insert("end", f"⚠ {label}")
                entry_host.delete(0, "end")

        entry_host.bind("<Return>", add_host)
        ttk.Button(frame_add, text="Ajouter", command=add_host).pack(side="left", padx=2)

        def add_from_scan():
            """Importe les machines en ligne depuis le scan."""
            count = 0
            for check, machine, ip, hostname, status in self._all_results:
                if status == "En ligne":
                    label = f"{ip} ({hostname})" if hostname else ip
                    listbox.insert("end", label)
                    count += 1
            if count == 0:
                messagebox.showinfo("Information", "Aucune machine en ligne dans le scan.", parent=win)

        ttk.Button(frame_add, text="📥 Depuis le scan", command=add_from_scan).pack(side="left", padx=2)

        def remove_selected():
            for idx in reversed(listbox.curselection()):
                listbox.delete(idx)

        ttk.Button(frame_add, text="🗑️ Supprimer", command=remove_selected).pack(side="left", padx=2)

        def clear_list():
            listbox.delete(0, "end")

        ttk.Button(frame_add, text="Tout vider", command=clear_list).pack(side="left", padx=2)

        # -- Options --------------------------------------------------------
        frame_options = ttk.LabelFrame(win, text="Options", padding=8)
        frame_options.pack(fill="x", padx=10, pady=5)

        # Action
        ttk.Label(frame_options, text="Action :").grid(row=0, column=0, sticky="w", padx=(0, 6))
        action_var = tk.StringVar(value="shutdown")
        ttk.Radiobutton(frame_options, text="Éteindre", variable=action_var, value="shutdown").grid(
            row=0, column=1, padx=4
        )
        ttk.Radiobutton(frame_options, text="Redémarrer", variable=action_var, value="restart").grid(
            row=0, column=2, padx=4
        )
        ttk.Radiobutton(frame_options, text="Déconnecter", variable=action_var, value="logoff").grid(
            row=0, column=3, padx=4
        )
        ttk.Radiobutton(frame_options, text="Annuler arrêt", variable=action_var, value="abort").grid(
            row=0, column=4, padx=4
        )

        # Délai
        ttk.Label(frame_options, text="Délai (secondes) :").grid(row=1, column=0, sticky="w", pady=(6, 0))
        delay_var = tk.StringVar(value="60")
        ttk.Entry(frame_options, textvariable=delay_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )

        # Forcer
        force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_options, text="Forcer la fermeture des applications", variable=force_var).grid(
            row=1, column=2, columnspan=3, sticky="w", pady=(6, 0)
        )

        # Message
        ttk.Label(frame_options, text="Message (optionnel) :").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        msg_entry = ttk.Entry(frame_options, width=40)
        msg_entry.grid(row=2, column=1, columnspan=4, sticky="ew", pady=(6, 0))

        # -- Bouton exécuter ------------------------------------------------
        frame_exec = ttk.Frame(win)
        frame_exec.pack(fill="x", padx=10, pady=10)

        def execute():
            items = listbox.get(0, "end")
            if not items:
                messagebox.showwarning("Attention", "La liste est vide.", parent=win)
                return

            # Extraire les IPs des labels
            targets = []
            for item in items:
                if item.startswith("⚠"):
                    continue
                # Extraire l'IP du format "IP (hostname)" ou "hostname → IP"
                ip = self._extract_ip_from_label(item)
                if ip:
                    targets.append((ip, item))

            if not targets:
                messagebox.showwarning("Attention", "Aucune cible valide.", parent=win)
                return

            action = action_var.get()
            action_names = {
                "shutdown": "éteindre",
                "restart": "redémarrer",
                "logoff": "déconnecter",
                "abort": "annuler l'arrêt de",
            }

            ok = messagebox.askyesno(
                "Confirmation",
                f"Voulez-vous {action_names[action]} {len(targets)} machine(s) ?\n\n"
                "Cette action est irréversible !",
                parent=win,
            )
            if not ok:
                return

            delay = delay_var.get()
            try:
                delay_int = int(delay)
            except ValueError:
                delay_int = 60

            force = force_var.get()
            message = msg_entry.get().strip()

            self._log(f"── Arrêt distant : {action_names[action]} {len(targets)} machine(s) ──", tag="info")

            threading.Thread(
                target=self._shutdown_worker,
                args=(targets, action, delay_int, force, message),
                daemon=True,
            ).start()

        ttk.Button(
            frame_exec, text="⏻ Exécuter", command=execute
        ).pack(side="right")

        ttk.Button(
            frame_exec, text="Fermer", command=win.destroy
        ).pack(side="right", padx=(0, 6))

    @staticmethod
    def _extract_ip_from_label(label: str) -> str:
        """Extrait l'IP d'un label comme 'IP (hostname)' ou 'hostname → IP'."""
        # Format "hostname → IP"
        if "→" in label:
            parts = label.split("→")
            ip_part = parts[-1].strip()
            try:
                ipaddress.IPv4Address(ip_part)
                return ip_part
            except (ipaddress.AddressValueError, ValueError):
                pass

        # Format "IP (hostname)" ou juste "IP"
        parts = label.split()
        if parts:
            ip_candidate = parts[0].strip()
            try:
                ipaddress.IPv4Address(ip_candidate)
                return ip_candidate
            except (ipaddress.AddressValueError, ValueError):
                pass

        return ""

    def _shutdown_worker(self, targets: list[tuple[str, str]], action: str,
                         delay: int, force: bool, message: str):
        """Exécute l'arrêt/redémarrage sur chaque cible (thread secondaire)."""
        _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        for ip, label in targets:
            # Construire la commande shutdown
            if os.name == "nt":
                cmd = ["shutdown"]
                if action == "shutdown":
                    cmd.append("/s")
                elif action == "restart":
                    cmd.append("/r")
                elif action == "logoff":
                    cmd.append("/l")
                elif action == "abort":
                    cmd.extend(["/a", f"/m", f"\\\\{ip}"])
                    # Abort n'a pas de délai ni de message
                    try:
                        result = subprocess.run(
                            cmd, capture_output=True, timeout=10,
                            creationflags=_CREATE_NO_WINDOW,
                        )
                        if result.returncode == 0:
                            self._queue.put(("log_ok", f"  ✓ {label} : arrêt annulé"))
                        else:
                            err = result.stderr.decode("cp850", errors="replace").strip()
                            self._queue.put(("log", f"  ✗ {label} : {err}"))
                    except Exception as e:
                        self._queue.put(("log", f"  ✗ {label} : {e}"))
                    continue

                cmd.extend([f"/m", f"\\\\{ip}", f"/t", str(delay)])
                if force:
                    cmd.append("/f")
                if message:
                    cmd.extend(["/c", message])
            else:
                # macOS/Linux : ssh shutdown (pour test local uniquement)
                if action == "abort":
                    cmd = ["ssh", ip, "sudo", "shutdown", "-c"]
                elif action == "restart":
                    cmd = ["ssh", ip, "sudo", "shutdown", "-r", f"+{delay // 60 or 1}", message or "Redémarrage distant"]
                elif action == "logoff":
                    self._queue.put(("log", f"  ⚠ {label} : déconnexion non supportée sur macOS/Linux"))
                    continue
                else:
                    cmd = ["ssh", ip, "sudo", "shutdown", "-h", f"+{delay // 60 or 1}", message or "Arrêt distant"]

            try:
                extra = {"creationflags": _CREATE_NO_WINDOW} if os.name == "nt" else {}
                result = subprocess.run(
                    cmd, capture_output=True, timeout=15,
                    text=True, errors="replace", **extra,
                )
                if result.returncode == 0:
                    action_labels = {
                        "shutdown": "arrêt programmé",
                        "restart": "redémarrage programmé",
                        "logoff": "déconnexion envoyée",
                    }
                    self._queue.put(("log_ok",
                        f"  ✓ {label} : {action_labels.get(action, action)} (délai : {delay} s)"
                    ))
                else:
                    err = result.stderr.strip() if result.stderr else f"Code {result.returncode}"
                    self._queue.put(("log", f"  ✗ {label} : {err}"))
            except subprocess.TimeoutExpired:
                self._queue.put(("log", f"  ✗ {label} : timeout (15 s)"))
            except FileNotFoundError:
                self._queue.put(("log", f"  ✗ {label} : commande 'shutdown' introuvable"))
            except Exception as e:
                self._queue.put(("log", f"  ✗ {label} : {e}"))

        self._queue.put(("log_info", "── Fin : Arrêt distant ──"))

    # ======================================================================
    #  Tracker réseau (surveillance des connexions en temps réel)
    # ======================================================================

    def _toggle_tracker_from_menu(self):
        """Démarre ou arrête le tracker réseau depuis le menu."""
        if self._tracker_running:
            # Arrêter
            self._tracker_stop.set()
            self._tracker_running = False
            self.btn_menu["menu"].entryconfigure(self._tracker_menu_index, label="📊 Tracker réseau (Démarrer)")
            self._log("Tracker réseau arrêté.", tag="info")
        else:
            # Démarrer
            self._tracker_stop.clear()
            self._tracker_known.clear()
            self._tracker_running = True
            self.btn_menu["menu"].entryconfigure(self._tracker_menu_index, label="⏹️ Tracker réseau (Arrêter)")
            self._log("── Tracker réseau démarré (intervalle : 2 s) ──", tag="info")
            threading.Thread(
                target=self._tracker_worker,
                daemon=True,
            ).start()

    def _tracker_worker(self):
        """Thread de surveillance : parse netstat toutes les 2 secondes."""
        _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        first_run = True
        stats_counter = 0

        while not self._tracker_stop.is_set():
            try:
                extra = {"creationflags": _CREATE_NO_WINDOW} if os.name == "nt" else {}
                result = subprocess.run(
                    ["netstat", "-an"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=5,
                    **extra,
                )
                current = self._parse_netstat(result.stdout)
            except Exception as e:
                self._queue.put(("log", f"  [Tracker] Erreur netstat : {e}"))
                self._tracker_stop.wait(5)
                continue

            if first_run:
                # Première capture : enregistrer l'état initial
                self._tracker_known = current
                self._queue.put(("log_info",
                    f"  État initial : {len(current)} connexion(s) active(s)"
                ))
                first_run = False
            else:
                # Détecter les nouvelles connexions
                nouvelles = current - self._tracker_known
                fermees = self._tracker_known - current

                for proto, local, port_l, remote, port_r in nouvelles:
                    port_name = self._port_to_service(port_r)
                    label = f" ({port_name})" if port_name else ""
                    self._queue.put(("log_ok",
                        f"  ▶ NOUVELLE  {proto:<4}  {local}:{port_l} → {remote}:{port_r}{label}"
                    ))

                for proto, local, port_l, remote, port_r in fermees:
                    self._queue.put(("log",
                        f"  ◀ FERMÉE    {proto:<4}  {local}:{port_l} → {remote}:{port_r}"
                    ))

                self._tracker_known = current

            # Afficher les stats toutes les 5 itérations (10 secondes)
            stats_counter += 1
            if stats_counter % 5 == 0:
                self._tracker_stats(current)

            # Attendre 2 secondes (interruptible)
            self._tracker_stop.wait(2)

        # Fin du tracker : afficher un résumé
        self._queue.put(("log_info", "── Tracker réseau terminé ──"))

    def _tracker_stats(self, connections: set):
        """Calcule et envoie les statistiques des connexions."""
        if not connections:
            return

        # Compter par protocole
        proto_count: dict[str, int] = {}
        remote_count: dict[str, int] = {}
        port_count: dict[str, int] = {}

        for proto, local, port_l, remote, port_r in connections:
            proto_count[proto] = proto_count.get(proto, 0) + 1
            if remote not in ("0.0.0.0", "*", "127.0.0.1", "::1", "::"):
                remote_count[remote] = remote_count.get(remote, 0) + 1
            port_name = self._port_to_service(port_r)
            if port_name:
                port_count[port_name] = port_count.get(port_name, 0) + 1

        # Protocoles
        proto_str = ", ".join(f"{p}: {n}" for p, n in sorted(proto_count.items()))
        self._queue.put(("log_info", f"  📊 Stats │ Total: {len(connections)} │ {proto_str}"))

        # Top 5 IPs distantes
        if remote_count:
            top_ips = sorted(remote_count.items(), key=lambda x: -x[1])[:5]
            top_str = ", ".join(f"{ip} ({n})" for ip, n in top_ips)
            self._queue.put(("log_info", f"  📊 Top IP │ {top_str}"))

        # Top services
        if port_count:
            top_ports = sorted(port_count.items(), key=lambda x: -x[1])[:5]
            top_str = ", ".join(f"{svc} ({n})" for svc, n in top_ports)
            self._queue.put(("log_info", f"  📊 Top services │ {top_str}"))

    @staticmethod
    def _parse_netstat(output: str) -> set[tuple[str, str, str, str, str]]:
        """Parse la sortie de netstat -an en un ensemble de connexions.

        Chaque connexion = (protocole, adresse_locale, port_local, adresse_distante, port_distant)
        """
        connections: set[tuple[str, str, str, str, str]] = set()

        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue

            proto = parts[0].upper()
            if proto not in ("TCP", "UDP", "TCP4", "TCP6", "UDP4", "UDP6", "TCP46"):
                continue

            # Normaliser le protocole
            if proto.startswith("TCP"):
                proto = "TCP"
            elif proto.startswith("UDP"):
                proto = "UDP"

            # Parser les adresses (format IP:port ou IP.port)
            local_raw = parts[3] if len(parts) >= 5 else parts[1]
            remote_raw = parts[4] if len(parts) >= 5 else parts[2]

            # Sur macOS/Linux netstat -an, le format est différent
            # Essayer les deux formats
            local_addr, local_port = _split_address(local_raw)
            remote_addr, remote_port = _split_address(remote_raw)

            if local_addr and remote_addr:
                connections.add((proto, local_addr, local_port, remote_addr, remote_port))

        return connections

    @staticmethod
    def _port_to_service(port: str) -> str:
        """Convertit un numéro de port en nom de service connu."""
        services = {
            "20": "FTP-Data", "21": "FTP", "22": "SSH", "23": "Telnet",
            "25": "SMTP", "53": "DNS", "67": "DHCP", "68": "DHCP",
            "80": "HTTP", "110": "POP3", "123": "NTP", "135": "RPC",
            "137": "NetBIOS", "138": "NetBIOS", "139": "NetBIOS",
            "143": "IMAP", "161": "SNMP", "389": "LDAP",
            "443": "HTTPS", "445": "SMB", "465": "SMTPS",
            "587": "SMTP", "636": "LDAPS", "993": "IMAPS",
            "995": "POP3S", "1080": "SOCKS", "1433": "MSSQL",
            "1434": "MSSQL", "3128": "Proxy", "3306": "MySQL",
            "3389": "RDP", "5432": "PostgreSQL", "5900": "VNC",
            "8080": "HTTP-Proxy", "8443": "HTTPS-Alt",
            "8888": "HTTP-Alt", "9090": "Web-Admin",
            "10000": "Webmin",
        }
        return services.get(port, "")


def _split_address(raw: str) -> tuple[str, str]:
    """Sépare une adresse brute (IP:port, IP.port, [IPv6]:port) en (adresse, port)."""
    if not raw or raw == "*.*":
        return "", ""

    # Format IPv6 [::1]:port
    if raw.startswith("["):
        bracket = raw.rfind("]")
        if bracket != -1 and bracket + 1 < len(raw):
            addr = raw[1:bracket]
            port = raw[bracket + 2:]  # saute ]:
            return addr, port

    # Format IP:port (Windows) ou IP.port (macOS/Linux)
    # Trouver le dernier séparateur (. ou :)
    last_colon = raw.rfind(":")
    last_dot = raw.rfind(".")

    # Préférer : comme séparateur (Windows)
    if last_colon > 0:
        addr = raw[:last_colon]
        port = raw[last_colon + 1:]
        # Vérifier que le port est un nombre ou *
        if port == "*" or port.isdigit():
            return addr, port

    # Sinon essayer . (macOS)
    if last_dot > 0:
        addr = raw[:last_dot]
        port = raw[last_dot + 1:]
        if port == "*" or port.isdigit():
            return addr, port

    return "", ""


class _AboutMixin:
    """Placeholder pour ne pas casser l'import — la vraie méthode est dans App."""
    pass


# Remonter _show_about dans la classe App : on le fait via un patch
def _show_about(self):
    """Affiche la boîte À propos avec le lien vers le dépôt GitHub."""
    messagebox.showinfo(
        "À propos",
        "NetProbe © – Couteau suisse réseau\n"
        "Éditeur : Hub Education\n"
        "Version 1.1.0\n\n"
        "• Scan de plage IP (ping parallèle)\n"
        "• Envoi de messages Windows (msg)\n"
        "• Ping, Traceroute, Nslookup\n"
        "• Infos réseau, Netstat\n"
        "• Scan Proxy / Kwartz\n"
        "• Tracker réseau temps réel\n"
        "• Arrêt & Redémarrage distant + DNS\n"
        "• Export CSV & Logs horodatés\n\n"
        "Dépôt GitHub / Nouvelles versions :\n"
        "https://github.com/Unfeeling3573/NetProbe\n\n"
        "Python 3 – tkinter – Aucune dépendance externe",
    )


App._show_about = _show_about


# ---------------------------------------------------------------------------
#  Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
