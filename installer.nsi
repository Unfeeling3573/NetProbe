; ============================================================================
; NSIS Installer Script – NetProbe © / Hub Education
; Version 1.1.5
; ============================================================================

!define APP_NAME "NetProbe"
!define APP_VERSION "1.1.5"
!define APP_PUBLISHER "Hub Education"
!define APP_EXE "NetProbe.exe"         ; Nom de l'exécutable compilé par PyInstaller
!define APP_DIR "NetProbe"

; Dépôt GitHub (pas de token ici – voir README pour les mises à jour)
!define GITHUB_REPO "https://github.com/Unfeeling3573/NetProbe"

; ----------------------------------------------------------------------------
; Configuration Générale
; ----------------------------------------------------------------------------
Name "${APP_NAME}"
OutFile "NetProbe_Setup_v${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES\${APP_DIR}"
InstallDirRegKey HKLM "Software\${APP_PUBLISHER}\${APP_NAME}" "Install_Dir"
RequestExecutionLevel admin

; ----------------------------------------------------------------------------
; Inclusions Modern UI 2
; ----------------------------------------------------------------------------
!include "MUI2.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

; Pages de l'assistant (Wizard)
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Lancer ${APP_NAME} maintenant"
!insertmacro MUI_PAGE_FINISH

; Pages du désinstallateur
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "French"

; ----------------------------------------------------------------------------
; Section d'installation
; ----------------------------------------------------------------------------
Section "Installation Principale" SecMain

    SetOutPath "$INSTDIR"

    ; 1. Copie de l'exécutable compilé par PyInstaller (dossier compiled/)
    File /nonfatal "compiled\${APP_EXE}"

    ; Copie des scripts Python (si utilisation sans compilation)
    File /nonfatal "launcher.py"
    File /nonfatal "menu.py"
    File /nonfatal "README.md"
    File /nonfatal "LICENSE.txt"
    CreateDirectory "$INSTDIR\assets"
    File /nonfatal /r "assets\*.*"

    ; 2. Création et configuration du dossier de logs
    DetailPrint "Création du dossier de logs..."
    CreateDirectory "$INSTDIR\logs"
    File /nonfatal /oname=logs\.gitkeep "logs\.gitkeep"

    ; 3. Signature du logiciel (Hub Education)
    FileOpen $0 "$INSTDIR\.hub_education" w
    FileWrite $0 "Hub Education"
    FileClose $0
    ; Rendre le fichier de signature caché sous Windows
    SetFileAttributes "$INSTDIR\.hub_education" HIDDEN

    ; 4. Écriture du Registre Windows (pour le désinstallateur)
    WriteRegStr HKLM "Software\${APP_PUBLISHER}\${APP_NAME}" "Install_Dir" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME} (${APP_PUBLISHER})"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "HelpLink" "${GITHUB_REPO}"

    ; 5. Création du désinstallateur
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; 6. Création des raccourcis
    ; Menu Démarrer
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
    CreateShortcut "$SMPROGRAMS\${APP_NAME}\Désinstaller.lnk" "$INSTDIR\Uninstall.exe"

    ; Raccourci Bureau
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

SectionEnd

; ----------------------------------------------------------------------------
; Section de Désinstallation
; ----------------------------------------------------------------------------
Section "Uninstall"

    ; Suppression des fichiers
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\launcher.py"
    Delete "$INSTDIR\menu.py"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\LICENSE.txt"
    Delete "$INSTDIR\.hub_education"
    Delete "$INSTDIR\assets\*.*"
    RMDir "$INSTDIR\assets"
    Delete "$INSTDIR\logs\*.*"
    RMDir "$INSTDIR\logs"
    Delete "$INSTDIR\Uninstall.exe"

    ; Suppression du dossier d'installation s'il est vide
    RMDir "$INSTDIR"

    ; Suppression des raccourcis
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Désinstaller.lnk"
    RMDir "$SMPROGRAMS\${APP_NAME}"

    ; Suppression des clés de Registre
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKLM "Software\${APP_PUBLISHER}\${APP_NAME}"

SectionEnd
