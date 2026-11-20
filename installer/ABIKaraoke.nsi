; ---------------------------------------------------------------------------
; ABI Karaoke - Windows installer (NSIS 3.x)
;
; Builds a single self-contained setup .exe that installs the portable bundle
; (embedded Python 3.11 + PySide6 + FFmpeg + whisper.cpp + the app) so the
; target machine needs no Python, no FFmpeg and no fonts pre-installed.
;
; Build with:  makensis installer\ABIKaraoke.nsi
; (works from Linux or Windows - NSIS cross-compiles)
; ---------------------------------------------------------------------------

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 32

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define APP_NAME     "ABI Karaoke"
!define APP_VERSION  "1.1.1"
!define APP_PUBLISHER "ABI Karaoke"
!define APP_URL      "https://github.com/ashokthrissur-cmd/karaokeking"
!define APP_EXE      "ABI Karaoke.vbs"
!define APP_ID       "{8E2C4B1A-5D77-4C2E-9A31-6F0B7C3D9E21}"
!define SOURCE_DIR   "..\..\build\portable\app"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "..\dist\ABI-Karaoke-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel user          ; per-user install: no admin prompt
BrandingText "${APP_NAME} ${APP_VERSION}"

VIProductVersion "1.1.1.0"
VIAddVersionKey "ProductName"     "${APP_NAME}"
VIAddVersionKey "ProductVersion"  "${APP_VERSION}"
VIAddVersionKey "FileDescription" "${APP_NAME} Setup"
VIAddVersionKey "FileVersion"     "${APP_VERSION}"
VIAddVersionKey "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright"  "${APP_PUBLISHER}"

!define MUI_ICON   "app.ico"
!define MUI_UNICON "app.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\Launch.bat"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APP_NAME} now"
!define MUI_FINISHPAGE_LINK "Project page"
!define MUI_FINISHPAGE_LINK_LOCATION "${APP_URL}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------
Section "!${APP_NAME} (required)" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; The whole self-contained runtime: python.exe, Lib\site-packages,
  ; ffmpeg\, whisper\, abikaraoke\ and the launchers.
  File /r "${SOURCE_DIR}\*.*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\${APP_NAME}" "Version" "${APP_VERSION}"

  ; Add/Remove Programs entry
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "DisplayName"     "${APP_NAME}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "DisplayVersion"  "${APP_VERSION}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "Publisher"       "${APP_PUBLISHER}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "URLInfoAbout"    "${APP_URL}"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "DisplayIcon"     "$INSTDIR\app.ico"
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}" "EstimatedSize" "$0"
SectionEnd

Section "Start Menu shortcuts" SEC_SM
  SetShellVarContext current
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"

  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
    "$SYSDIR\wscript.exe" '"$INSTDIR\${APP_EXE}"' "$INSTDIR\app.ico" 0 SW_SHOWNORMAL "" "Karaoke videos from any song"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Setup AI (one time).lnk" \
    "$INSTDIR\Setup AI.bat" "" "$INSTDIR\app.ico" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Check installation.lnk" \
    "$INSTDIR\Doctor.bat" "" "$INSTDIR\app.ico" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Troubleshoot.lnk" \
    "$INSTDIR\Troubleshoot.bat" "" "$INSTDIR\app.ico" 0
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" \
    "$INSTDIR\Uninstall.exe" "" "$INSTDIR\app.ico" 0
SectionEnd

Section "Desktop shortcut" SEC_DESKTOP
  SetShellVarContext current
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" \
    "$SYSDIR\wscript.exe" '"$INSTDIR\${APP_EXE}"' "$INSTDIR\app.ico" 0 SW_SHOWNORMAL "" "Karaoke videos from any song"
SectionEnd

Section "AI speech model (~142 MB download)" SEC_MODEL
  DetailPrint "Downloading the whisper.cpp speech model..."
  DetailPrint "This is a one-time download; AI sync works offline afterwards."
  ExecWait '"$INSTDIR\python.exe" -m abikaraoke setup --model base' $0
  ${If} $0 != 0
    DetailPrint "Model download did not finish (exit code $0)."
    DetailPrint "You can retry later from the Start Menu: Setup AI (one time)."
  ${Else}
    DetailPrint "AI model installed."
  ${EndIf}
SectionEnd

; ---------------------------------------------------------------------------
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN}    "The application, embedded Python, FFmpeg, whisper.cpp and fonts."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_SM}      "Add shortcuts to the Start Menu."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} "Add a shortcut on the Desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MODEL}   "Download the speech-recognition model used by AI sync. Needs internet once."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ; Refuse to run a second copy of the installer.
  System::Call 'kernel32::CreateMutex(p 0, i 0, t "ABIKaraokeSetupMutex") p .r1 ?e'
  Pop $R0
  ${If} $R0 != 0
    MessageBox MB_OK|MB_ICONSTOP "${APP_NAME} setup is already running."
    Abort
  ${EndIf}

  ; Offer to remove a previous install in the same place.
  ReadRegStr $R1 HKCU "Software\${APP_NAME}" "InstallDir"
  ${If} $R1 != ""
  ${AndIf} ${FileExists} "$R1\Uninstall.exe"
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "${APP_NAME} is already installed in:$R1$\n$\nRemove the old version first?" \
      IDNO +2
    ExecWait '"$R1\Uninstall.exe" /S _?=$R1'
    Delete "$R1\Uninstall.exe"
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  ; Nothing extra: the finish page launches the app.
FunctionEnd

; ---------------------------------------------------------------------------
Section "Uninstall"
  SetShellVarContext current

  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Setup AI (one time).lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Check installation.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Troubleshoot.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk"
  RMDir  "$SMPROGRAMS\${APP_NAME}"

  ; Remove the whole tree (runtime, models, caches).
  RMDir /r "$INSTDIR\abikaraoke"
  RMDir /r "$INSTDIR\Lib"
  RMDir /r "$INSTDIR\ffmpeg"
  RMDir /r "$INSTDIR\whisper"
  Delete   "$INSTDIR\*.exe"
  Delete   "$INSTDIR\*.dll"
  Delete   "$INSTDIR\*.pyd"
  Delete   "$INSTDIR\*.zip"
  Delete   "$INSTDIR\*._pth"
  Delete   "$INSTDIR\*.bat"
  Delete   "$INSTDIR\*.vbs"
  Delete   "$INSTDIR\*.ico"
  Delete   "$INSTDIR\*.txt"
  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
  DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
