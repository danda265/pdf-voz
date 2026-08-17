; ============================================================
;  PDF VOZ - Instalador (Inno Setup)
;  Gera um setup.exe com atalhos + desinstalador.
;  AppVersion DEVE bater com APP_VERSION em gui.py.
; ============================================================

#define MyAppName "PDF VOZ"
#define MyAppVersion "1.2.0"
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

[Registry]
; Registra o PDF VOZ como aplicativo capaz de abrir PDF/Word. Sem isto ele nem aparece
; na lista "Abrir com" do Explorer nem em Configuracoes > Aplicativos padrao.
; Tudo em HKCU porque a instalacao e por usuario (PrivilegesRequired=lowest).
; O Windows NAO permite que um app se torne padrao sozinho — quem confirma e o usuario,
; uma vez, pelo dialogo "Abrir com" ou por Configuracoes.
Root: HKCU; Subkey: "Software\Classes\PDFVOZ.Documento"; ValueType: string; ValueName: ""; ValueData: "Documento do PDF VOZ"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\PDFVOZ.Documento\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\PDFVOZ.Documento\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

; Aparece no "Abrir com" de cada extensao suportada
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgIds";  ValueType: string; ValueName: "PDFVOZ.Documento"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.docx\OpenWithProgIds"; ValueType: string; ValueName: "PDFVOZ.Documento"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.doc\OpenWithProgIds";  ValueType: string; ValueName: "PDFVOZ.Documento"; ValueData: ""; Flags: uninsdeletevalue

; Declara as capacidades para Configuracoes > Aplicativos padrao
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Leitor e editor de PDF com voz neural brasileira"
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf";  ValueData: "PDFVOZ.Documento"
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".docx"; ValueData: "PDFVOZ.Documento"
Root: HKCU; Subkey: "Software\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".doc";  ValueData: "PDFVOZ.Documento"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\{#MyAppName}\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
