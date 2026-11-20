; Inno Setup script for ABI Karaoke.
;
; Packages the portable bundle produced by build/Build-Portable.ps1 (or the
; PyInstaller output) into a normal Windows application with Start-menu
; entries, an uninstaller and an optional desktop icon.
;
; Build with:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\ABIKaraoke.iss

#define AppName "ABI Karaoke"
#define AppVersion "1.1.0"
#define AppPublisher "ABI Karaoke"
#define AppExe "ABI Karaoke.vbs"

[Setup]
AppId={{8E2C4B1A-5D77-4C2E-9A31-6F0B7C3D9E21}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\ABI Karaoke
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ABI-Karaoke-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\app.ico
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\LICENSE
SetupIconFile=app.ico
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "aimodel"; Description: "Download the AI speech model now (~140 MB, enables AI auto-sync)"; GroupDescription: "AI features:"

[Files]
; Everything produced by the portable build.
Source: "..\dist\ABI Karaoke\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppExe}"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{group}\Doctor (check installed tools)"; Filename: "{app}\python.exe"; Parameters: "-m abikaraoke doctor"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppExe}"""; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#AppExe}"""; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\python.exe"; Parameters: "-m abikaraoke setup --model base"; \
    Description: "Download the AI speech model"; Flags: runhidden waituntilterminated; Tasks: aimodel

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
