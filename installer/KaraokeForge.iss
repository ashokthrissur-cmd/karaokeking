#define AppName "ABI Karaoke"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExeName "ABI_Karaoke.exe"

[Setup]
AppId={{D85666AD-7002-40E6-9F08-8940C776836E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ABI Karaoke
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=..\publish\installer
OutputBaseFilename=ABI_Karaoke_Setup_{#AppVersion}_x64
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
InfoBeforeFile=Prerequisites.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\publish\ABI_Karaoke.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ABI Karaoke"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\ABI Karaoke"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch ABI Karaoke"; Flags: postinstall nowait skipifsilent
