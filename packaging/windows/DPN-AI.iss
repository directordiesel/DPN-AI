; DPN AI v8 Windows installer (Inno Setup)
; Build only through build-installer.ps1 so package integrity/version checks run first.

#ifndef AppVersion
  #error AppVersion must be supplied by build-installer.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build-installer.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build-installer.ps1
#endif

#define AppName "DPN AI"
#define AppPublisher "DPN Technology"
#define AppExeName "DPN-AI.exe"
#define AppId "{{9E6D64D2-47F6-4D62-B73D-7D9AB758F31A}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\DPN Technology\DPN AI
DefaultGroupName=DPN Technology\DPN AI
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=DPN-AI-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
ChangesAssociations=no
ChangesEnvironment=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
AllowNoIcons=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DPN AI"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\DPN AI"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch DPN AI"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; Only installer-owned cache/temp content inside {app} may be removed explicitly.
; Persistent projects, memory, databases, logs, backups, and settings belong outside
; the application directory and are intentionally preserved on uninstall.
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
