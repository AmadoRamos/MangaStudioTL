; Script de instalacion para Taller de Rotulacion
; Requiere: Inno Setup 6.1 o superior (usa CreateDownloadPage)
; Compilar con: build_exe.bat  (o: iscc /DAppVersion=1.0.0 installer.iss)

#define AppExeName "Taller de Rotulacion.exe"
; Verificada el 2026-08-15 (50 MB). Si un dia da 404, la release vigente
; esta en https://github.com/UB-Mannheim/tesseract/releases/latest — el
; fallo no rompe la instalacion, solo deja el OCR sin instalar.
#define TesseractUrl "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"

[Setup]
AppName=Taller de Rotulación
AppVersion={#AppVersion}
AppVerName=Taller de Rotulación {#AppVersion}
VersionInfoCompany=AmadoRamos
VersionInfoCopyright=Copyright 2026
AppPublisher=AmadoRamos
DefaultDirName={autopf}\TallerRotulacion
DefaultGroupName=Taller de Rotulación
AllowNoIcons=yes
OutputBaseFilename=TallerRotulacion_v{#AppVersion}_Setup
OutputDir=output\
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallFilesDir={app}
SetupIconFile=src\assets\logo.ico
; El bundle ronda 1,3 GB antes de comprimir; sin esto el compilador se
; queda sin espacio de direcciones en el paso de compresion solida.
LZMAUseSeparateProcess=yes
DiskSpanning=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "tesseract"; Description: "Descargar e instalar Tesseract OCR (necesario para el paso 3, ~60 MB)"; GroupDescription: "Componentes adicionales:"

[Files]
Source: "dist\Taller de Rotulacion\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Taller de Rotulación"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Desinstalar Taller de Rotulación"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Taller de Rotulación"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Interactivo a proposito, sin /S: el instalador de UB-Mannheim trae solo
; ingles por defecto, y hay que marcar «Additional language data > Spanish»
; para que el modo «Español + Ingles» de la app tenga con que trabajar.
;
; shellexec no es opcional: Tesseract se instala en Program Files y su
; manifiesto pide elevacion, pero este setup corre como {autopf} sin
; privilegios (PrivilegesRequired=lowest). CreateProcess —lo que usa Inno
; por defecto— no puede elevar y falla con el codigo 740; ShellExecute si
; honra el manifiesto y lanza el UAC.
Filename: "{tmp}\tesseract-setup.exe"; Description: "Instalar Tesseract OCR"; StatusMsg: "Instalando Tesseract OCR..."; Flags: postinstall skipifsilent shellexec; Tasks: tesseract; Check: TesseractDownloaded
Filename: "{app}\{#AppExeName}"; Description: "Iniciar Taller de Rotulación"; Flags: postinstall skipifsilent nowait

[Code]
var
  DownloadPage: TDownloadWizardPage;
  TesseractOk: Boolean;

function OnDownloadProgress(const Url, FileName: string; const Progress, ProgressMax: Int64): Boolean;
begin
  if Progress = ProgressMax then
    Log('Descarga terminada: ' + FileName);
  Result := True;
end;

procedure InitializeWizard();
begin
  TesseractOk := False;
  DownloadPage := CreateDownloadPage(
    SetupMessage(msgWizardPreparing),
    SetupMessage(msgPreparingDesc),
    @OnDownloadProgress);
end;

function TesseractDownloaded(): Boolean;
begin
  Result := TesseractOk;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID <> wpReady) or (not WizardIsTaskSelected('tesseract')) then
    Exit;

  DownloadPage.Clear;
  DownloadPage.Add('{#TesseractUrl}', 'tesseract-setup.exe', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      TesseractOk := True;
    except
      // Un fallo de red no puede abortar la instalacion: la app detecta
      // sola que Tesseract falta, deshabilita el OCR con instrucciones y
      // ofrece un selector manual de ruta. Se avisa y se sigue.
      Log('Fallo la descarga de Tesseract: ' + GetExceptionMessage);
      MsgBox('No se pudo descargar Tesseract OCR:' + #13#10 + #13#10
             + GetExceptionMessage + #13#10 + #13#10
             + 'La instalacion continua. El paso 3 (OCR) quedara deshabilitado '
             + 'hasta que instales Tesseract por tu cuenta desde:' + #13#10
             + 'https://github.com/UB-Mannheim/tesseract/releases',
             mbInformation, MB_OK);
      TesseractOk := False;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    CreateDir(ExpandConstant('{userappdata}\TallerRotulacion'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataPath: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  // Aqui viven los logs, el historial de carpetas y los perfiles de texto
  // (src/config.py: USER_DATA_DIR). Las paginas traducidas no: esas se
  // guardan junto a los escaneos y no las toca nadie.
  AppDataPath := ExpandConstant('{userappdata}\TallerRotulacion');
  if DirExists(AppDataPath) then
    DelTree(AppDataPath, True, True, True);
end;

function NeedRestart(): Boolean;
begin
  Result := False;
end;
