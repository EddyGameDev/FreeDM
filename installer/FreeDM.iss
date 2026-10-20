; Inno Setup script for the FreeDM installer (free: https://jrsoftware.org/isdl.php)
;
; Build it with:  iscc installer\FreeDM.iss   (Inno Setup 6 must be installed)
;
; The result is dist\FreeDM-Setup-<version>.exe: a normal installer with a
; Start-menu shortcut, an uninstaller and no system-wide changes.

#define AppName "FreeDM"
#define AppVersion "1.5.0"
#define AppPublisher "outlawproductionstwo-hash"
#define AppURL "https://github.com/EddyGameDev/FreeDM"
#define AppExeName "FreeDM.exe"
#define CliExeName "FreeDM-cli.exe"

[Setup]
AppId={{7E4C2B0A-9C1E-4C4B-9C4E-2B0F5D9A1E77}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=FreeDM-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The app is a portable program: it never writes outside %APPDATA%\FreeDM.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The application and the console build.
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#CliExeName}"; DestDir: "{app}"; Flags: ignoreversion
; The licence and the notice must travel with the program.
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; The browser extension, so the user can load it without the app.
Source: "..\extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} (command line)"; Filename: "{app}\{#CliExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The queue and the settings live in %APPDATA%\FreeDM; they are the user's
; data, so they are NOT deleted automatically.
Type: filesandordirs; Name: "{app}\extension"
