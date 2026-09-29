; Inno Setup Script for BitChat
; Defines installer configuration and PATH management for Windows

#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif

#ifndef MyOutputBaseFilename
#define MyOutputBaseFilename "BitChat-0.1.0-windows-x64"
#endif

#define MyAppName "BitChat"
#define MyAppPublisher "Java-Mx"
#define MyAppURL "https://github.com/Java-Mx/bitchat-python"
#define MyAppExeName "bitchat.exe"

[Setup]
; Unique application GUID for BitChat
AppId={{B17CHA70-B1EC-4E87-99B7-4DA78D0B7001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "envPath"; Description: "Add BitChat to PATH environment variable (recommended)"; Flags: checkedonce

[Files]
Source: "..\..\dist\bitchat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
  RootKey: Integer;
  PathKey: string;
  NormParam: string;
begin
  if IsAdminInstallMode then
  begin
    RootKey := HKEY_LOCAL_MACHINE;
    PathKey := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  end
  else
  begin
    RootKey := HKEY_CURRENT_USER;
    PathKey := 'Environment';
  end;

  if not RegQueryStringValue(RootKey, PathKey, 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;

  NormParam := Param;
  if (Length(NormParam) > 0) and (NormParam[Length(NormParam)] = '\') then
    Delete(NormParam, Length(NormParam), 1);

  Result := (Pos(';' + UpperCase(NormParam) + ';', ';' + UpperCase(OrigPath) + ';') = 0) and
            (Pos(';' + UpperCase(NormParam) + '\;', ';' + UpperCase(OrigPath) + ';') = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PathKey: string;
  OrigPath, NewPath: string;
  RootKey: Integer;
  AppDir: string;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('envPath') then
  begin
    if IsAdminInstallMode then
    begin
      RootKey := HKEY_LOCAL_MACHINE;
      PathKey := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
    end
    else
    begin
      RootKey := HKEY_CURRENT_USER;
      PathKey := 'Environment';
    end;

    AppDir := ExpandConstant('{app}');
    if (Length(AppDir) > 0) and (AppDir[Length(AppDir)] = '\') then
      Delete(AppDir, Length(AppDir), 1);

    if RegQueryStringValue(RootKey, PathKey, 'Path', OrigPath) then
    begin
      if NeedsAddPath(AppDir) then
      begin
        if (OrigPath <> '') and (OrigPath[Length(OrigPath)] <> ';') then
          NewPath := OrigPath + ';' + AppDir
        else
          NewPath := OrigPath + AppDir;
        RegWriteExpandStringValue(RootKey, PathKey, 'Path', NewPath);
      end;
    end
    else
    begin
      RegWriteExpandStringValue(RootKey, PathKey, 'Path', AppDir);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  PathKey: string;
  OrigPath, AppDir, CleanPath: string;
  RootKey: Integer;
  P: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if IsAdminInstallMode then
    begin
      RootKey := HKEY_LOCAL_MACHINE;
      PathKey := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
    end
    else
    begin
      RootKey := HKEY_CURRENT_USER;
      PathKey := 'Environment';
    end;

    if RegQueryStringValue(RootKey, PathKey, 'Path', OrigPath) then
    begin
      AppDir := ExpandConstant('{app}');
      if (Length(AppDir) > 0) and (AppDir[Length(AppDir)] = '\') then
        Delete(AppDir, Length(AppDir), 1);

      CleanPath := ';' + OrigPath + ';';

      { Remove path with trailing backslash if present }
      P := Pos(';' + UpperCase(AppDir) + '\;', UpperCase(CleanPath));
      if P > 0 then
        Delete(CleanPath, P, Length(AppDir) + 2);

      { Remove path without trailing backslash if present }
      P := Pos(';' + UpperCase(AppDir) + ';', UpperCase(CleanPath));
      if P > 0 then
        Delete(CleanPath, P, Length(AppDir) + 1);

      { Clean up any duplicate semicolons }
      StringChange(CleanPath, ';;', ';');

      { Clean up leading/trailing semicolon }
      if (Length(CleanPath) > 0) and (CleanPath[1] = ';') then
        Delete(CleanPath, 1, 1);
      if (Length(CleanPath) > 0) and (CleanPath[Length(CleanPath)] = ';') then
        Delete(CleanPath, Length(CleanPath), 1);

      RegWriteExpandStringValue(RootKey, PathKey, 'Path', CleanPath);
    end;
  end;
end;
