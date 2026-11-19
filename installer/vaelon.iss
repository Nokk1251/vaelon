; Inno Setup script: turns dist\Vaelon (made by scripts\build_app.py) into Vaelon-Setup-<version>.exe
;   "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" /DAppVersion=0.18.0 installer\vaelon.iss
; Installs into Program Files (one administrator prompt): only an administrator can change the program files there, so
; no other program can swap or plant files in Vaelon (white-hat review 2026-11-18). Vaelon itself then runs as the
; normal user. Your data in %USERPROFILE%\.vaelon and Documents\Vaelon is NEVER touched by install, update or uninstall.

#ifndef AppVersion
  #define AppVersion "0.18.0"
#endif

[Setup]
AppId={{6B1E0C52-7C0E-4D0B-9A53-3A6D8B1F0E21}
AppName=Vaelon
AppVersion={#AppVersion}
AppVerName=Vaelon {#AppVersion}
AppPublisher=Nokk_7
AppPublisherURL=https://github.com/Nokk1251
AppCopyright=Copyright (C) 2026 Nokk_7 - GPL-3.0-or-later
DefaultDirName={autopf}\Vaelon
DefaultGroupName=Vaelon
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
MinVersion=10.0
LicenseFile=..\LICENSE
InfoBeforeFile=..\NOTICE
OutputDir=Output
OutputBaseFilename=Vaelon-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Vaelon.exe
UninstallDisplayName=Vaelon
SetupIconFile=..\src\vaelon\data\vaelon.ico
; a running Vaelon is closed (or the user is asked) before files are replaced
AppMutex=VaelonRunning
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; an update replaces the whole program folder: no old or foreign file can stay behind in it
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Vaelon\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Vaelon"; Filename: "{app}\Vaelon.exe"
Name: "{group}\Uninstall Vaelon"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Vaelon"; Filename: "{app}\Vaelon.exe"; Tasks: desktopicon

[Run]
; started as the signed-in user, never with the installer's administrator rights
Filename: "{app}\Vaelon.exe"; Description: "Start Vaelon"; Flags: nowait postinstall skipifsilent runasoriginaluser
