#define AppName "XTray"
#ifndef AppVersion
#define AppVersion "0.1.1b3"
#endif
#ifndef SourceExe
#define SourceExe "..\dist\XTray.exe"
#endif
#ifndef BackendExe
#define BackendExe "..\dist\XTray.Backend.exe"
#endif

[Setup]
AppId={{7B7988F8-C0D3-4F23-8C4F-5F2B8E64B731}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Arrigo Croce
AppUpdatesURL=https://github.com/Phos69/XTray-Production/releases
DefaultDirName={localappdata}\Programs\XTray
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=XTray-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\XTray.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"; Flags: unchecked
Name: "autostart"; Description: "Start XTray with Windows"; GroupDescription: "Additional options:"; Flags: unchecked
Name: "pcsync"; Description: "Enable PC Sync"; GroupDescription: "Feature options:"; Flags: unchecked
Name: "network_manager_full"; Description: "Enable full Network Manager experimental features"; GroupDescription: "Feature options:"; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "XTray.exe"; Flags: ignoreversion
Source: "{#BackendExe}"; DestDir: "{app}"; DestName: "XTray.Backend.exe"; Flags: ignoreversion
Source: "XTray.ico"; DestDir: "{app}"; DestName: "XTray.ico"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; DestName: "CHANGELOG.md"; Flags: ignoreversion

[Icons]
Name: "{group}\XTray"; Filename: "{app}\XTray.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\XTray"; Filename: "{app}\XTray.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "XTray"; ValueData: """{app}\XTray.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\XTray.exe"; Parameters: "--cli sync configure --enable"; Flags: runhidden waituntilterminated skipifdoesntexist; Tasks: pcsync
Filename: "{app}\XTray.exe"; Parameters: "--cli config experimental --network-manager-full"; Flags: runhidden waituntilterminated skipifdoesntexist; Tasks: network_manager_full
Filename: "{app}\XTray.exe"; Description: "Launch XTray"; Flags: nowait postinstall skipifsilent
