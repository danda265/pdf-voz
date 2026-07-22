; ============================================================
;  PDF VOZ - Instalador (Inno Setup)
;  Gera um setup.exe com atalhos + desinstalador.
;  AppVersion DEVE bater com APP_VERSION em gui.py.
; ============================================================

#define MyAppName "PDF VOZ"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Anderson Rodrigo Costa"
#define MyAppExeName "PDF VOZ.exe"
#define MySrcDir "dist\PDF VOZ"

[Setup]
; AppId fixo — NUNCA mudar entre versoes (garante upgrade/desinstalacao corretos)
AppId={{7F3A1C92-4B6E-4E2A-9E1D-2C7A9B4E5D01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Instalacao por usuario (sem admin) — sempre em local gravavel (%LOCALAPPDATA%\Programs)
; para o app poder escrever seus mp3 temporarios em _internal\temp
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Saida do instalador
OutputDir=installer
OutputBaseFilename=PDF-VOZ-Setup-{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; Compressao
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; Copia toda a pasta gerada pelo PyInstaller (exe + _internal com Tesseract, Qt, etc.)
; Exclui mp3 temporarios e a pasta temp (lixo de runtime) para nao ir junto no instalador
Source: "{#MySrcDir}\*"; DestDir: "{app}"; Excludes: "temp\*,*.mp3"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";                Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}";     Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
