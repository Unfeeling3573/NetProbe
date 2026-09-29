<!-- SIGNATURE : Hub Education -->

# MSG Windows – Couteau suisse réseau

## Structure du projet

```
MSG_Windows/
├── launcher.py        ← Point d'entrée (vérifie les dépendances puis lance l'app)
├── msg_windows.py     ← Application principale (Scanner, Messenger, App)
├── logs/              ← Fichiers de log (1 fichier par session, créé automatiquement)
└── README.md          ← Ce fichier
```

## Lancement

```cmd
python launcher.py
```

Le launcher vérifie automatiquement :
- ✓ Version de Python (>= 3.10)
- ✓ Présence de tkinter
- ✓ Modules de la bibliothèque standard
- ✓ Commandes système (ping, msg)
- ✓ Création du dossier logs/

## Fonctionnalités

### Scan de plage IP
- Ping parallèle (100 threads)
- Résolution de noms d'hôte
- Barre de progression
- Filtre « En ligne » / « Tout afficher »
- Export CSV

### Envoi de messages Windows
- Commande `msg` vers les machines sélectionnées
- Journal horodaté avec logs fichier

### Outils réseau (barre d'outils)
- 🔔 Ping
- 🔀 Traceroute
- 🔍 Nslookup
- 🌐 Infos réseau local (ipconfig / ifconfig)
- 📡 Netstat (ports ouverts)

## Logs

Chaque session crée un fichier dans `logs/` :
```
logs/session_20260928_191300.log
```

## Prérequis pour `msg` à distance

1. Windows Pro/Entreprise (la commande `msg` n'existe pas sur Windows Famille)
2. Clé de registre sur la cible :
   `HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server` → `AllowRemoteRPC = 1`
3. Pare-feu : autoriser RPC (TCP 135 + ports dynamiques)
4. Droits d'administration à distance

## Empaquetage en .exe

```cmd
pip install pyinstaller
pyinstaller --onefile --windowed --name MSG_Windows launcher.py
```
