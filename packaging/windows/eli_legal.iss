; ELI Legal - Windows installer (Inno Setup 6).
;
; Built by packaging\windows\build.ps1 after PyInstaller has produced build\dist\eli-legal.
; Installs for the current user by default (no administrator rights needed) or for everyone.
; The program and the user's data are kept apart: matters, the audit ledger and its key live in
; %LOCALAPPDATA%\ELI Legal and are never removed by the uninstaller.

#define AppVersion GetEnv("ELI_LEGAL_VERSION")
#if AppVersion == ""
  #error Set ELI_LEGAL_VERSION (build.ps1 does this)
#endif
#define AppPublisher GetEnv("ELI_LEGAL_PUBLISHER")
#if AppPublisher == ""
  #define AppPublisher "ELI Legal"
#endif
#define Root "..\.."

[Setup]
; Never change AppId: it is how an upgrade finds the installed copy.
AppId={{19F46F18-E864-4146-9A5D-4821B64105A6}
AppName=ELI Legal
AppVersion={#AppVersion}
AppVerName=ELI Legal {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\ELI Legal
DefaultGroupName=ELI Legal
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist\installers
OutputBaseFilename=ELI_Legal-{#AppVersion}-windows-x64-setup
SetupIconFile=eli_legal.ico
UninstallDisplayIcon={app}\eli-legal-gui.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile={#Root}\packaging\INSTALL_NOTICE.txt
#if FileExists(AddBackslash(SourcePath) + Root + "\LICENSE")
LicenseFile={#Root}\LICENSE
#endif
ChangesEnvironment=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "addtopath"; Description: "Add the eli-legal command to PATH"; GroupDescription: "Command line:"; Flags: unchecked

[Files]
Source: "{#Root}\build\dist\eli-legal\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Root}\packaging\INSTALL_NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ELI Legal"; Filename: "{app}\eli-legal-gui.exe"; WorkingDir: "{app}"
Name: "{group}\ELI Legal command line"; Filename: "{cmd}"; Parameters: "/K ""{app}\eli-legal.exe"" --help"; WorkingDir: "{app}"
Name: "{group}\Uninstall ELI Legal"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ELI Legal"; Filename: "{app}\eli-legal-gui.exe"; Tasks: desktopicon

[Registry]
; Per-user PATH entry, only if asked for. Removed again on uninstall.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\eli-legal-gui.exe"; Description: "Start ELI Legal"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=ELI Legal is installed.%n%nYour matters, the audit ledger and its key are kept in your user data folder (%LOCALAPPDATA%\ELI Legal), separate from the program. Uninstalling never removes them.

[Code]
function NeedsAddPath(Dir: string): Boolean;
var
  Existing: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Existing) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(Existing) + ';') = 0;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var
  Existing, Dir: string;
  P: Integer;
begin
  if Step <> usPostUninstall then exit;
  Dir := ExpandConstant('{app}');
  if RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Existing) then
  begin
    P := Pos(';' + Uppercase(Dir), Uppercase(Existing));
    if P > 0 then
    begin
      Delete(Existing, P, Length(Dir) + 1);
      RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Existing);
    end;
  end;
end;
