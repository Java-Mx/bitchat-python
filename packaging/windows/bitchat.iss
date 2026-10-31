; =============================================================================
; BitChat Windows Installer 2.0 — Inno Setup 6 Script
; Repository: https://github.com/Java-Mx/bitchat-python
; Package Identifier: Java-Mx.BitChat
; =============================================================================

#ifndef MyAppVersion
#define MyAppVersion "0.2.1"
#endif

#ifndef MyOutputBaseFilename
#define MyOutputBaseFilename "BitChat-0.2.1-windows-x64"
#endif

#define MyAppName "BitChat"
#define MyAppPublisher "Java-Mx"
#define MyAppURL "https://github.com/Java-Mx/bitchat-python"
#define MyTermsURL "https://github.com/Java-Mx/bitchat-python/blob/main/TERMS_OF_USE.md"
#define MyPrivacyURL "https://github.com/Java-Mx/bitchat-python/blob/main/PRIVACY_POLICY.md"
#define MyAppExeName "bitchat.exe"
#define MyAppId "{{B17CHA70-B1EC-4E87-99B7-4DA78D0B7001}"
#define MyAppRegKey "Software\Java-Mx\BitChat"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppCopyright=Copyright (c) 2026 BitChat Contributors (MIT License)
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=BitChat Setup — Private Peer-to-Peer Terminal Messenger
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
SetupIconFile=assets\bitchat.ico
WizardImageFile=assets\wizard-large.bmp
WizardSmallImageFile=assets\wizard-small.bmp
OutputDir=..\..\dist
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
CreateUninstallRegKey=WizardIsTaskSelected('uninstallentry')
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\assets\bitchat.ico
ExtraDiskSpaceRequired=10485760
#ifdef SignToolConfigured
SignTool=signtool
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to {#MyAppName} Setup
WelcomeLabel2=Install {#MyAppName} {#MyAppVersion}, a private peer-to-peer terminal messaging application operating over Bluetooth Low Energy (BLE) and Local Area Networks (LAN).%n%nPublisher: {#MyAppPublisher}%nVersion: {#MyAppVersion}%nOfficial Repository: {#MyAppURL}%n%nThis self-contained installer bundles the complete {#MyAppName} runtime. No manual Python, Git, or dependency installation is required.%n%nClick Next to review the Terms of Use and Privacy Policy.
SelectDirDesc=Where should {#MyAppName} be installed?
SelectTasksDesc=Configure shortcuts, command-line PATH access, and Windows startup integration.
FinishedHeadingLabel=Completing the {#MyAppName} {#MyAppVersion} Setup Wizard

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Shortcuts:"
Name: "envPath"; Description: "Add {#MyAppName} to the current user's &PATH (run 'bitchat' from PowerShell or Command Prompt)"; GroupDescription: "Command-Line & System Integration:"
Name: "launchapp"; Description: "&Launch {#MyAppName} immediately after installation"; GroupDescription: "Post-Installation:"
Name: "startupicon"; Description: "Start {#MyAppName} automatically when &Windows starts (launches after user sign-in)"; GroupDescription: "Windows Startup Integration:"; Flags: unchecked
Name: "uninstallentry"; Description: "Create an &uninstaller entry in Windows Installed Apps"; GroupDescription: "Command-Line & System Integration:"

[InstallDelete]
; Clean stale internal runtime libraries during upgrades without touching user data
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Temporary legal files for custom wizard screens
Source: "legal\TERMS_OF_USE.txt"; Flags: dontcopy
Source: "legal\PRIVACY_POLICY.txt"; Flags: dontcopy
; Application runtime bundle
Source: "..\..\dist\bitchat\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Official BitChat branding and icon assets
Source: "assets\bitchat.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\Bitchat-Icon-Framed.svg"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-icon-16.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-icon-32.svg"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-icon-48.svg"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-symbol-dark.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-symbol-light.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-wordmark-dark.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\bitchat-wordmark-light.png"; DestDir: "{app}\assets"; Flags: ignoreversion
; Bundled legal and license documentation in installation directory
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\..\TERMS_OF_USE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\PRIVACY_POLICY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\bitchat.ico"; Comment: "BitChat Peer-to-Peer Encrypted Terminal Messenger"; Tasks: startmenuicon
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; IconFilename: "{app}\assets\bitchat.ico"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\bitchat.ico"; Comment: "BitChat Peer-to-Peer Encrypted Terminal Messenger"; Tasks: desktopicon
Name: "{code:GetStartupFolder}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--startup-launch"; WorkingDir: "{app}"; IconFilename: "{app}\assets\bitchat.ico"; Comment: "Start BitChat after Windows user sign-in"; Tasks: startupicon

[UninstallDelete]
Type: files; Name: "{code:GetStartupFolder}\{#MyAppName}.lnk"
Type: files; Name: "{autodesktop}\{#MyAppName}.lnk"
Type: filesandordirs; Name: "{group}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallRegPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B17CHA70-B1EC-4E87-99B7-4DA78D0B7001}_is1';
  MinFreeDiskSpaceMB = 80;

var
  TermsPage: TWizardPage;
  TermsMemo: TNewMemo;
  TermsLinkLabel: TNewStaticText;
  TermsCheckBox: TNewCheckBox;

  PrivacyPage: TWizardPage;
  PrivacyMemo: TNewMemo;
  PrivacyLinkLabel: TNewStaticText;
  PrivacyNoteLabel: TNewStaticText;
  PrivacyCheckBox: TNewCheckBox;

  UpgradeStatusLabel: TNewStaticText;
  ExistingInstalledVersion: string;
  ExistingInstalledLocation: string;
  HadStartupShortcutBeforeInstall: Boolean;

function GetEnvironmentRootKey(): Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function GetEnvironmentSubKey(): string;
var
  OverrideKey: string;
begin
  OverrideKey := Trim(GetEnv('BITCHAT_TEST_ENV_SUBKEY'));
  if OverrideKey <> '' then
  begin
    Result := OverrideKey;
    exit;
  end;

  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

function NormalizeDirPath(const DirPath: string): string;
begin
  Result := Trim(DirPath);
  if (Length(Result) > 3) and (Result[Length(Result)] = '\') then
    Delete(Result, Length(Result), 1);
end;

function GetStartupFolder(Param: string): string;
var
  OverrideDir: string;
begin
  OverrideDir := Trim(GetEnv('BITCHAT_STARTUP_DIR'));
  if OverrideDir <> '' then
  begin
    Result := NormalizeDirPath(OverrideDir);
    ForceDirectories(Result);
    exit;
  end;
  Result := ExpandConstant('{userstartup}');
end;

function GetUserDataDir(): string;
var
  OverrideDir: string;
  UserProfile: string;
begin
  OverrideDir := Trim(GetEnv('BITCHAT_USER_DATA_DIR'));
  if OverrideDir <> '' then
  begin
    Result := NormalizeDirPath(OverrideDir);
    exit;
  end;

  UserProfile := Trim(GetEnv('USERPROFILE'));
  if UserProfile = '' then
    UserProfile := ExpandConstant('{%USERPROFILE}');
  if UserProfile <> '' then
    Result := NormalizeDirPath(AddBackslash(UserProfile) + '.bitchat')
  else
    Result := NormalizeDirPath(ExpandConstant('{userpf}\..\..\.bitchat'));
end;

function HasCommandLineSwitch(const SwitchName: string): Boolean;
var
  I: Integer;
  Param: string;
  Target: string;
begin
  Result := False;
  Target := UpperCase(SwitchName);
  for I := 1 to ParamCount do
  begin
    Param := UpperCase(ParamStr(I));
    if (Param = '/' + Target) or (Param = '-' + Target) or
       (Pos('/' + Target + '=', Param) = 1) or
       (Pos('-' + Target + '=', Param) = 1) then
    begin
      Result := True;
      exit;
    end;
  end;
end;

procedure DetectExistingInstallation();
begin
  ExistingInstalledVersion := '';
  ExistingInstalledLocation := '';

  if not RegQueryStringValue(HKEY_CURRENT_USER, UninstallRegPath, 'DisplayVersion', ExistingInstalledVersion) then
    RegQueryStringValue(HKEY_LOCAL_MACHINE, UninstallRegPath, 'DisplayVersion', ExistingInstalledVersion);

  if not RegQueryStringValue(HKEY_CURRENT_USER, UninstallRegPath, 'Inno Setup: App Path', ExistingInstalledLocation) then
    RegQueryStringValue(HKEY_LOCAL_MACHINE, UninstallRegPath, 'Inno Setup: App Path', ExistingInstalledLocation);
end;

function IsLaunchAppSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('launchapp');
end;

procedure OnTermsLinkClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', '{#MyTermsURL}', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure OnPrivacyLinkClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', '{#MyPrivacyURL}', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure OnTermsCheckBoxClick(Sender: TObject);
begin
  WizardForm.NextButton.Enabled := TermsCheckBox.Checked;
end;

procedure OnPrivacyCheckBoxClick(Sender: TObject);
begin
  WizardForm.NextButton.Enabled := PrivacyCheckBox.Checked;
end;

procedure CreateTermsAndPrivacyPages();
var
  TermsFile: string;
  PrivacyFile: string;
  Lines: TArrayOfString;
  I: Integer;
  Content: string;
begin
  ExtractTemporaryFile('TERMS_OF_USE.txt');
  ExtractTemporaryFile('PRIVACY_POLICY.txt');
  TermsFile := ExpandConstant('{tmp}\TERMS_OF_USE.txt');
  PrivacyFile := ExpandConstant('{tmp}\PRIVACY_POLICY.txt');

  { Screen 2: Terms of Use }
  TermsPage := CreateCustomPage(
    wpWelcome,
    'Terms of Use',
    'Please review and accept the {#MyAppName} Terms of Use before continuing.'
  );

  TermsMemo := TNewMemo.Create(TermsPage);
  TermsMemo.Parent := TermsPage.Surface;
  TermsMemo.Left := 0;
  TermsMemo.Top := 0;
  TermsMemo.Width := TermsPage.SurfaceWidth;
  TermsMemo.Height := TermsPage.SurfaceHeight - ScaleY(60);
  TermsMemo.ScrollBars := ssVertical;
  TermsMemo.ReadOnly := True;
  TermsMemo.Font.Name := 'Consolas';
  TermsMemo.Font.Size := 9;
  if LoadStringsFromFile(TermsFile, Lines) then
  begin
    Content := '';
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      if I > 0 then
        Content := Content + #13#10;
      Content := Content + Lines[I];
    end;
    TermsMemo.Text := Content;
  end;

  TermsLinkLabel := TNewStaticText.Create(TermsPage);
  TermsLinkLabel.Parent := TermsPage.Surface;
  TermsLinkLabel.Left := 0;
  TermsLinkLabel.Top := TermsMemo.Top + TermsMemo.Height + ScaleY(8);
  TermsLinkLabel.Caption := 'Read the complete Terms of Use online (' + '{#MyTermsURL}' + ')';
  TermsLinkLabel.Font.Color := clHighlight;
  TermsLinkLabel.Font.Style := [fsUnderline];
  TermsLinkLabel.Cursor := crHand;
  TermsLinkLabel.OnClick := @OnTermsLinkClick;

  TermsCheckBox := TNewCheckBox.Create(TermsPage);
  TermsCheckBox.Parent := TermsPage.Surface;
  TermsCheckBox.Left := 0;
  TermsCheckBox.Top := TermsLinkLabel.Top + TermsLinkLabel.Height + ScaleY(8);
  TermsCheckBox.Width := TermsPage.SurfaceWidth;
  TermsCheckBox.Caption := 'I have read and agree to the BitChat Terms of Use.';
  TermsCheckBox.Checked := False;
  TermsCheckBox.OnClick := @OnTermsCheckBoxClick;

  { Screen 3: Privacy Policy }
  PrivacyPage := CreateCustomPage(
    TermsPage.ID,
    'Privacy Policy',
    'Please review the {#MyAppName} Privacy Policy before continuing.'
  );

  PrivacyMemo := TNewMemo.Create(PrivacyPage);
  PrivacyMemo.Parent := PrivacyPage.Surface;
  PrivacyMemo.Left := 0;
  PrivacyMemo.Top := 0;
  PrivacyMemo.Width := PrivacyPage.SurfaceWidth;
  PrivacyMemo.Height := PrivacyPage.SurfaceHeight - ScaleY(78);
  PrivacyMemo.ScrollBars := ssVertical;
  PrivacyMemo.ReadOnly := True;
  PrivacyMemo.Font.Name := 'Consolas';
  PrivacyMemo.Font.Size := 9;
  if LoadStringsFromFile(PrivacyFile, Lines) then
  begin
    Content := '';
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      if I > 0 then
        Content := Content + #13#10;
      Content := Content + Lines[I];
    end;
    PrivacyMemo.Text := Content;
  end;

  PrivacyLinkLabel := TNewStaticText.Create(PrivacyPage);
  PrivacyLinkLabel.Parent := PrivacyPage.Surface;
  PrivacyLinkLabel.Left := 0;
  PrivacyLinkLabel.Top := PrivacyMemo.Top + PrivacyMemo.Height + ScaleY(6);
  PrivacyLinkLabel.Caption := 'Read the complete Privacy Policy online (' + '{#MyPrivacyURL}' + ')';
  PrivacyLinkLabel.Font.Color := clHighlight;
  PrivacyLinkLabel.Font.Style := [fsUnderline];
  PrivacyLinkLabel.Cursor := crHand;
  PrivacyLinkLabel.OnClick := @OnPrivacyLinkClick;

  PrivacyNoteLabel := TNewStaticText.Create(PrivacyPage);
  PrivacyNoteLabel.Parent := PrivacyPage.Surface;
  PrivacyNoteLabel.Left := 0;
  PrivacyNoteLabel.Top := PrivacyLinkLabel.Top + PrivacyLinkLabel.Height + ScaleY(4);
  PrivacyNoteLabel.Width := PrivacyPage.SurfaceWidth;
  PrivacyNoteLabel.WordWrap := True;
  PrivacyNoteLabel.Caption := 'BitChat collects no analytics, telemetry, or account data. This acknowledgment is informational only and is not consent to optional tracking or marketing.';

  PrivacyCheckBox := TNewCheckBox.Create(PrivacyPage);
  PrivacyCheckBox.Parent := PrivacyPage.Surface;
  PrivacyCheckBox.Left := 0;
  PrivacyCheckBox.Top := PrivacyNoteLabel.Top + PrivacyNoteLabel.Height + ScaleY(6);
  PrivacyCheckBox.Width := PrivacyPage.SurfaceWidth;
  PrivacyCheckBox.Caption := 'I have read the BitChat Privacy Policy.';
  PrivacyCheckBox.Checked := False;
  PrivacyCheckBox.OnClick := @OnPrivacyCheckBoxClick;
end;

procedure InitializeWizard();
begin
  DetectExistingInstallation();
  HadStartupShortcutBeforeInstall := FileExists(AddBackslash(GetStartupFolder('')) + '{#MyAppName}.lnk');
  CreateTermsAndPrivacyPages();

  UpgradeStatusLabel := TNewStaticText.Create(WizardForm);
  UpgradeStatusLabel.Parent := WizardForm.SelectDirPage;
  UpgradeStatusLabel.Left := 0;
  UpgradeStatusLabel.Top := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(14);
  UpgradeStatusLabel.Width := WizardForm.SelectDirPage.ClientWidth;
  UpgradeStatusLabel.WordWrap := True;
  if ExistingInstalledVersion <> '' then
    UpgradeStatusLabel.Caption :=
      'Existing installation detected: BitChat ' + ExistingInstalledVersion +
      ' at ' + ExistingInstalledLocation + '.' + #13#10 +
      'Upgrading will preserve your cryptographic identity keys, configuration (~/.bitchat), and startup preferences.'
  else
    UpgradeStatusLabel.Caption :=
      'Default user-scope location requires no administrator privileges (%LOCALAPPDATA%\Programs\BitChat).';
end;

function FindNearestExistingParent(DirPath: string): string;
var
  Current: string;
  ParentDir: string;
begin
  Current := NormalizeDirPath(DirPath);
  while (Current <> '') and (not DirExists(Current)) do
  begin
    ParentDir := ExtractFileDir(Current);
    if (ParentDir = '') or (ParentDir = Current) then
      break;
    Current := ParentDir;
  end;
  Result := Current;
end;

function IsDirectoryWritable(const DirPath: string): Boolean;
var
  ProbeDir: string;
  ProbeFile: string;
begin
  Result := False;
  ProbeDir := FindNearestExistingParent(DirPath);
  if (ProbeDir = '') or (not DirExists(ProbeDir)) then
    exit;

  ProbeFile := AddBackslash(ProbeDir) + '.bitchat_setup_write_test.tmp';
  if SaveStringToFile(ProbeFile, 'probe', False) then
  begin
    DeleteFile(ProbeFile);
    Result := True;
  end;
end;

function ValidateDestinationDir(const DestDir: string; var ErrorMsg: string): Boolean;
var
  NormDest: string;
  UpperDest: string;
  UpperWin: string;
  UpperSys: string;
  UpperUserData: string;
  FreeMB, TotalMB: Cardinal;
begin
  Result := False;
  NormDest := NormalizeDirPath(DestDir);
  if (NormDest = '') or (Length(NormDest) <= 3) then
  begin
    ErrorMsg := 'Cannot install BitChat directly into a drive root directory (' + NormDest + '). Please choose a dedicated folder such as ' + ExpandConstant('{localappdata}\Programs\{#MyAppName}') + '.';
    exit;
  end;

  UpperDest := UpperCase(NormDest);
  UpperWin := UpperCase(NormalizeDirPath(ExpandConstant('{win}')));
  UpperSys := UpperCase(NormalizeDirPath(ExpandConstant('{sys}')));
  UpperUserData := UpperCase(GetUserDataDir());

  if (UpperDest = UpperWin) or (Pos(UpperWin + '\', UpperDest + '\') = 1) or
     (UpperDest = UpperSys) or (Pos(UpperSys + '\', UpperDest + '\') = 1) then
  begin
    ErrorMsg := 'Cannot install BitChat into a protected Windows system directory (' + NormDest + ').';
    exit;
  end;

  if (UpperDest = UpperUserData) or (Pos(UpperUserData + '\', UpperDest + '\') = 1) then
  begin
    ErrorMsg := 'Cannot install BitChat application binaries inside the user data and cryptographic identity directory (' + GetUserDataDir() + '). Please choose a separate program directory.';
    exit;
  end;

  if not IsDirectoryWritable(NormDest) then
  begin
    ErrorMsg := 'Setup does not have write permission for "' + NormDest + '".' + #13#10 + #13#10 +
                'Please choose a user-writable directory such as "' + ExpandConstant('{localappdata}\Programs\{#MyAppName}') + '", or run Setup as Administrator if installing to a machine-wide folder.';
    exit;
  end;

  if GetSpaceOnDisk(FindNearestExistingParent(NormDest), True, FreeMB, TotalMB) then
  begin
    if FreeMB < MinFreeDiskSpaceMB then
    begin
      ErrorMsg := 'Insufficient disk space on the selected drive. At least ' + IntToStr(MinFreeDiskSpaceMB) + ' MB of free space is required, but only ' + IntToStr(FreeMB) + ' MB is available.';
      exit;
    end;
  end;

  Result := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if WizardSilent() and ((PageID = TermsPage.ID) or (PageID = PrivacyPage.ID)) then
    Result := True;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  StartupSummary: string;
  PathSummary: string;
  DataSummary: string;
begin
  if CurPageID = TermsPage.ID then
  begin
    if not WizardSilent() then
      WizardForm.NextButton.Enabled := TermsCheckBox.Checked;
  end
  else if CurPageID = PrivacyPage.ID then
  begin
    if not WizardSilent() then
      WizardForm.NextButton.Enabled := PrivacyCheckBox.Checked;
  end
  else if CurPageID = wpFinished then
  begin
    if WizardForm.RunList.Items.Count > 0 then
      WizardForm.RunList.Checked[0] := WizardIsTaskSelected('launchapp');

    if FileExists(AddBackslash(GetStartupFolder('')) + '{#MyAppName}.lnk') then
      StartupSummary := 'Enabled (launches after user sign-in)'
    else
      StartupSummary := 'Disabled';

    if WizardIsTaskSelected('envPath') then
      PathSummary := 'Enabled (reopen existing terminals to run "bitchat")'
    else
      PathSummary := 'Disabled';

    if DirExists(GetUserDataDir()) then
      DataSummary := 'Preserved at ' + GetUserDataDir()
    else
      DataSummary := 'Initialized on first launch (' + GetUserDataDir() + ')';

    WizardForm.FinishedLabel.AutoSize := False;
    WizardForm.FinishedLabel.Caption :=
      '{#MyAppName} {#MyAppVersion} has been successfully installed.' + #13#10 + #13#10 +
      'Installed Version:    {#MyAppVersion}' + #13#10 +
      'Installation Path:    ' + ExpandConstant('{app}') + #13#10 +
      'PATH Integration:     ' + PathSummary + #13#10 +
      'Start with Windows:   ' + StartupSummary + #13#10 +
      'User Identity & Data: ' + DataSummary;
    if WizardForm.RunList.Top > WizardForm.FinishedLabel.Top + ScaleY(40) then
      WizardForm.FinishedLabel.Height := WizardForm.RunList.Top - WizardForm.FinishedLabel.Top - ScaleY(4);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  ErrorMsg: string;
begin
  Result := True;

  if WizardSilent() then
  begin
    if CurPageID = wpSelectDir then
    begin
      if not ValidateDestinationDir(WizardDirValue, ErrorMsg) then
      begin
        Log('Destination validation failed: ' + ErrorMsg);
        Result := False;
      end;
    end;
    exit;
  end;

  if CurPageID = TermsPage.ID then
  begin
    if not TermsCheckBox.Checked then
    begin
      MsgBox('You must read and agree to the BitChat Terms of Use before proceeding.', mbError, MB_OK);
      Result := False;
      exit;
    end;
  end
  else if CurPageID = PrivacyPage.ID then
  begin
    if not PrivacyCheckBox.Checked then
    begin
      MsgBox('Please confirm that you have read the BitChat Privacy Policy before proceeding.', mbError, MB_OK);
      Result := False;
      exit;
    end;
  end
  else if CurPageID = wpSelectDir then
  begin
    if not ValidateDestinationDir(WizardDirValue, ErrorMsg) then
    begin
      MsgBox(ErrorMsg, mbError, MB_OK);
      Result := False;
      exit;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: string): string;
var
  S: string;
begin
  S := '';
  if ExistingInstalledVersion <> '' then
  begin
    S := S + 'Installation Mode:' + NewLine +
         Space + 'Upgrade / Maintenance from BitChat ' + ExistingInstalledVersion + NewLine +
         Space + 'User identity keys and config (~/.bitchat) will be preserved' + NewLine + NewLine;
  end
  else
  begin
    S := S + 'Installation Mode:' + NewLine +
         Space + 'Fresh Installation (BitChat {#MyAppVersion})' + NewLine + NewLine;
  end;

  if MemoDirInfo <> '' then
    S := S + MemoDirInfo + NewLine + NewLine;

  if MemoTasksInfo <> '' then
    S := S + MemoTasksInfo + NewLine + NewLine;

  S := S + 'Legal Agreements:' + NewLine +
       Space + 'BitChat Terms of Use: Accepted' + NewLine +
       Space + 'BitChat Privacy Policy: Acknowledged';

  Result := S;
end;

procedure StopRunningBitChatInDir(const AppDir: string);
var
  TargetExe: string;
  ResultCode: Integer;
  PsCmd: string;
begin
  TargetExe := AddBackslash(NormalizeDirPath(AppDir)) + '{#MyAppExeName}';
  if not FileExists(TargetExe) then
    exit;

  PsCmd :=
    '$target = [System.IO.Path]::GetFullPath(''' + TargetExe + '''); ' +
    'Get-Process -Name bitchat -ErrorAction SilentlyContinue | ForEach-Object { ' +
    '  try { ' +
    '    if ($_.Path -and ([System.IO.Path]::GetFullPath($_.Path) -ieq $target)) { ' +
    '      Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue ' +
    '    } ' +
    '  } catch {} ' +
    '}; Start-Sleep -Milliseconds 400';

  Exec('powershell.exe', '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + PsCmd + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): string;
var
  ErrorMsg: string;
begin
  Result := '';
  if not ValidateDestinationDir(ExpandConstant('{app}'), ErrorMsg) then
  begin
    Result := ErrorMsg;
    exit;
  end;

  { Safely close any running instance of bitchat.exe in the target directory before overwriting files }
  StopRunningBitChatInDir(ExpandConstant('{app}'));
end;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
  RootKey: Integer;
  PathKey: string;
  NormParam: string;
begin
  RootKey := GetEnvironmentRootKey();
  PathKey := GetEnvironmentSubKey();

  if not RegQueryStringValue(RootKey, PathKey, 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;

  NormParam := NormalizeDirPath(Param);
  Result := (Pos(';' + UpperCase(NormParam) + ';', ';' + UpperCase(OrigPath) + ';') = 0) and
            (Pos(';' + UpperCase(NormParam) + '\;', ';' + UpperCase(OrigPath) + ';') = 0);
end;

procedure RemoveDirFromPathIfAddedByInstaller(const AppDir: string);
var
  RootKey: Integer;
  PathKey: string;
  OrigPath, NormDir, CleanPath, RecordedDir: string;
  P: Integer;
begin
  RecordedDir := '';
  if not RegQueryStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'PathAddedByInstaller', RecordedDir) then
  begin
    { Do not remove PATH entries that were not added by the BitChat installer }
    exit;
  end;

  RootKey := GetEnvironmentRootKey();
  PathKey := GetEnvironmentSubKey();
  NormDir := NormalizeDirPath(AppDir);
  if RecordedDir <> '' then
    NormDir := NormalizeDirPath(RecordedDir);

  if RegQueryStringValue(RootKey, PathKey, 'Path', OrigPath) then
  begin
    CleanPath := ';' + OrigPath + ';';

    P := Pos(';' + UpperCase(NormDir) + '\;', UpperCase(CleanPath));
    while P > 0 do
    begin
      Delete(CleanPath, P, Length(NormDir) + 2);
      P := Pos(';' + UpperCase(NormDir) + '\;', UpperCase(CleanPath));
    end;

    P := Pos(';' + UpperCase(NormDir) + ';', UpperCase(CleanPath));
    while P > 0 do
    begin
      Delete(CleanPath, P, Length(NormDir) + 1);
      P := Pos(';' + UpperCase(NormDir) + ';', UpperCase(CleanPath));
    end;

    StringChange(CleanPath, ';;', ';');

    if (Length(CleanPath) > 0) and (CleanPath[1] = ';') then
      Delete(CleanPath, 1, 1);
    if (Length(CleanPath) > 0) and (CleanPath[Length(CleanPath)] = ';') then
      Delete(CleanPath, Length(CleanPath), 1);

    RegWriteExpandStringValue(RootKey, PathKey, 'Path', CleanPath);
  end;

  RegDeleteValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'PathAddedByInstaller');
end;

procedure AddDirToPath(const AppDir: string);
var
  RootKey: Integer;
  PathKey: string;
  OrigPath, NewPath, NormDir, PreviousDir: string;
begin
  RootKey := GetEnvironmentRootKey();
  PathKey := GetEnvironmentSubKey();
  NormDir := NormalizeDirPath(AppDir);

  { If upgrading from a different custom directory, clean up the previous installer PATH entry first }
  PreviousDir := '';
  if RegQueryStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'PathAddedByInstaller', PreviousDir) then
  begin
    if (PreviousDir <> '') and (UpperCase(NormalizeDirPath(PreviousDir)) <> UpperCase(NormDir)) then
      RemoveDirFromPathIfAddedByInstaller(PreviousDir);
  end;

  if RegQueryStringValue(RootKey, PathKey, 'Path', OrigPath) then
  begin
    if NeedsAddPath(NormDir) then
    begin
      if (OrigPath <> '') and (OrigPath[Length(OrigPath)] <> ';') then
        NewPath := OrigPath + ';' + NormDir
      else
        NewPath := OrigPath + NormDir;
      RegWriteExpandStringValue(RootKey, PathKey, 'Path', NewPath);
    end;
  end
  else
  begin
    RegWriteExpandStringValue(RootKey, PathKey, 'Path', NormDir);
  end;

  RegWriteStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'PathAddedByInstaller', NormDir);
  RegWriteStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'InstallScope', 'user');
  if IsAdminInstallMode then
    RegWriteStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'InstallScope', 'admin');
end;

procedure SyncStartupShortcutOnPostInstall();
var
  StartupLnk: string;
  ExplicitTasksSwitch: Boolean;
begin
  StartupLnk := AddBackslash(GetStartupFolder('')) + '{#MyAppName}.lnk';
  ExplicitTasksSwitch := HasCommandLineSwitch('TASKS') or HasCommandLineSwitch('MERGETASKS');

  if WizardIsTaskSelected('startupicon') then
  begin
    RegWriteDWordValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'StartupEnabled', 1);
  end
  else if HadStartupShortcutBeforeInstall and WizardSilent() and (not ExplicitTasksSwitch) then
  begin
    { Preserve existing startup preference during silent upgrades when /TASKS was not overridden }
    CreateShellLink(
      StartupLnk,
      'Start BitChat after Windows user sign-in',
      ExpandConstant('{app}\{#MyAppExeName}'),
      '--startup-launch',
      ExpandConstant('{app}'),
      ExpandConstant('{app}\assets\bitchat.ico'),
      0,
      SW_SHOWNORMAL
    );
    RegWriteDWordValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'StartupEnabled', 1);
  end
  else
  begin
    if FileExists(StartupLnk) then
      DeleteFile(StartupLnk);
    RegWriteDWordValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'StartupEnabled', 0);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir: string;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := NormalizeDirPath(ExpandConstant('{app}'));
    RegWriteStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'InstalledVersion', '{#MyAppVersion}');
    RegWriteStringValue(HKEY_CURRENT_USER, '{#MyAppRegKey}', 'InstallLocation', AppDir);

    { Synchronize PATH task }
    if WizardIsTaskSelected('envPath') then
      AddDirToPath(AppDir)
    else
      RemoveDirFromPathIfAddedByInstaller(AppDir);

    { Synchronize Desktop shortcut if unchecked on reinstall }
    if not WizardIsTaskSelected('desktopicon') then
    begin
      if FileExists(ExpandConstant('{autodesktop}\{#MyAppName}.lnk')) then
        DeleteFile(ExpandConstant('{autodesktop}\{#MyAppName}.lnk'));
    end;

    { Synchronize Start Menu shortcuts if unchecked on reinstall }
    if not WizardIsTaskSelected('startmenuicon') then
    begin
      if DirExists(ExpandConstant('{group}')) then
        DelTree(ExpandConstant('{group}'), True, True, True);
    end;

    { Synchronize Windows startup registration }
    SyncStartupShortcutOnPostInstall();
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  StopRunningBitChatInDir(ExpandConstant('{app}'));
end;

function ShouldRemoveUserDataOnUninstall(): Boolean;
var
  UserDataDir: string;
  PromptText: string;
begin
  Result := False;
  UserDataDir := GetUserDataDir();
  if (UserDataDir = '') or (not DirExists(UserDataDir)) then
    exit;

  { Allow explicit CLI opt-in (/REMOVEUSERDATA) for automated tests or power users }
  if HasCommandLineSwitch('REMOVEUSERDATA') then
  begin
    Result := True;
    exit;
  end;

  { By default in silent uninstall, always preserve user data and cryptographic keys }
  if UninstallSilent() then
  begin
    Result := False;
    exit;
  end;

  PromptText :=
    'By default, BitChat preserves your personal data directory at:' + #13#10 +
    '  ' + UserDataDir + #13#10 + #13#10 +
    'This folder contains:' + #13#10 +
    '  • Your cryptographic identity and private keys (identity.json)' + #13#10 +
    '  • Your node configuration, nickname, and keybindings (config.json)' + #13#10 +
    '  • Any local peer or message history' + #13#10 + #13#10 +
    'WARNING: Permanently deleting your cryptographic identity keys cannot be undone. ' +
    'Other peers will no longer recognize your node fingerprint.' + #13#10 + #13#10 +
    'Do you want to permanently DELETE your BitChat user data and private identity keys?' + #13#10 +
    '(Click "No" to keep your identity and settings safe — Recommended)';

  if SuppressibleMsgBox(PromptText, mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    Result := True;
end;

procedure SafeRemoveUserDataDir();
var
  UserDataDir: string;
  UpperDir: string;
begin
  UserDataDir := GetUserDataDir();
  UpperDir := UpperCase(UserDataDir);
  { Safety guard: only delete if path explicitly ends with \.BITCHAT }
  if (Length(UpperDir) > 10) and
     (Copy(UpperDir, Length(UpperDir) - 8, 9) = '\.BITCHAT') and
     DirExists(UserDataDir) then
  begin
    DelTree(UserDataDir, True, True, True);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir: string;
  StartupLnk: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDir := NormalizeDirPath(ExpandConstant('{app}'));

    { 1. Remove PATH entry only if it was added by the BitChat installer }
    RemoveDirFromPathIfAddedByInstaller(AppDir);

    { 2. Remove per-user Windows Startup shortcut if present }
    StartupLnk := AddBackslash(GetStartupFolder('')) + '{#MyAppName}.lnk';
    if FileExists(StartupLnk) then
      DeleteFile(StartupLnk);

    { 3. Clean up BitChat installer metadata registry key }
    RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, '{#MyAppRegKey}');

    { 4. Preserve user data by default, or remove if explicitly requested }
    if ShouldRemoveUserDataOnUninstall() then
      SafeRemoveUserDataDir();
  end;
end;
