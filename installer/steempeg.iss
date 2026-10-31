; Steempeg per-user installer (Inno Setup 6).
;
; Packs the frozen build folder newver_compilator.py writes to dist\Steempeg
; (Nuitka for the Windows release) into Steempeg_v<version>_setup.exe.
; No admin rights: installs to %LocalAppData%\Programs\Steempeg, so the in-app
; updater can still write there.
;
; newver_compilator.py --installer passes the defines below; building by hand:
;   ISCC.exe /DAppVersion=55 installer\steempeg.iss

#ifndef AppVersion
  #define AppVersion "dev"
#endif
#ifndef AppVersionFile
  #define AppVersionFile AppVersion
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Steempeg"
#endif
#ifndef OutputDir
  #define OutputDir ".."
#endif

[Setup]
; AppId must never change: Windows uses it to find the install for updates and uninstall.
AppId={{8FDC961D-EEA5-4016-BB3C-7235F7E56619}
AppName=Steempeg
AppVersion={#AppVersion}
AppVerName=Steempeg {#AppVersion}
AppPublisher=applejuicy23
AppPublisherURL=https://github.com/applejuicy23/steempeg
AppSupportURL=https://github.com/applejuicy23/steempeg/issues
DefaultDirName={userpf}\Steempeg
DefaultGroupName=Steempeg
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=Steempeg_v{#AppVersionFile}_setup
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\Steempeg.exe
UninstallDisplayName=Steempeg
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start Steempeg with Windows (hidden in the tray, catches new Steam clips)"; GroupDescription: "Background:"

[Files]
; User data made by a test run of the build folder must not ship in the installer.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\cache,\logs,\rendered_videos,\Screenshots,*.lock"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Steempeg"; Filename: "{app}\Steempeg.exe"
Name: "{autodesktop}\Steempeg"; Filename: "{app}\Steempeg.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Steempeg"; ValueData: """{app}\Steempeg.exe"" --background"; Tasks: autostart; Flags: uninsdeletevalue
; Re-running the installer with the box unticked turns autostart off again.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Steempeg"; Tasks: not autostart; Flags: deletevalue

[Run]
Filename: "{app}\Steempeg.exe"; Description: "Launch Steempeg"; Flags: nowait postinstall skipifsilent

[Code]
var
  RepairPage: TWizardPage;
  UpdateRadio: TNewRadioButton;
  RepairRadio: TNewRadioButton;
  RepairNote: TNewStaticText;
  RepairChoiceDir: string;
  RepairModeChanging: Boolean;

// Inno only deletes files it copied at install time. An in-app update adds new
// files and old_version_v* / pre_restore_v* trees, and those would survive
// uninstall. User data that lives in {app} must stay.
//
// A second run over an existing folder is still an update: it copies files
// and leaves anything this setup does not replace. Repair is the other
// choice on that page. It deletes the program files first, then the copy
// puts this setup back. cache, logs, rendered_videos, and Screenshots stay.

function SamePath(const A, B: string): Boolean;
begin
  Result := CompareText(RemoveBackslash(A), RemoveBackslash(B)) = 0;
end;

function InstallDirIsSafeToClean(const Dir: string): Boolean;
var
  Trimmed, Name: string;
begin
  Result := False;
  Trimmed := RemoveBackslash(Dir);
  // A drive root ("D:\") is never the install folder.
  if Length(Trimmed) <= 3 then
    Exit;
  Name := ExtractFileName(Trimmed);
  // A custom directory that is not named Steempeg may be a folder the user
  // shares with other files (Downloads, a drive root they typed by hand).
  if CompareText(Name, 'Steempeg') <> 0 then
    Exit;
  if SamePath(Trimmed, ExpandConstant('{userprofile}')) then
    Exit;
  if SamePath(Trimmed, ExpandConstant('{userdesktop}')) then
    Exit;
  if SamePath(Trimmed, ExpandConstant('{userdocs}')) then
    Exit;
  if SamePath(Trimmed, ExpandConstant('{localappdata}')) then
    Exit;
  Result := DirExists(Trimmed);
end;

function IsProtectedDataDir(const Name: string): Boolean;
begin
  Result :=
    (CompareText(Name, 'cache') = 0) or
    (CompareText(Name, 'logs') = 0) or
    (CompareText(Name, 'rendered_videos') = 0) or
    (CompareText(Name, 'Screenshots') = 0);
end;

function IsUninstallerFile(const Name: string): Boolean;
begin
  // unins000.* is this running uninstaller; Inno deletes it itself.
  Result := (Length(Name) >= 8) and (CompareText(Copy(Name, 1, 8), 'unins000') = 0);
end;

procedure DeleteProgramFilesKeepData(const Dir: string);
var
  Path, Name: string;
  FindRec: TFindRec;
begin
  if not InstallDirIsSafeToClean(Dir) then
    Exit;
  if not FindFirst(AddBackslash(Dir) + '*', FindRec) then
    Exit;
  try
    repeat
      Name := FindRec.Name;
      if (Name <> '.') and (Name <> '..') and (not IsProtectedDataDir(Name)) and (not IsUninstallerFile(Name)) then
      begin
        Path := AddBackslash(Dir) + Name;
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          DelTree(Path, True, True, True)
        else
          DeleteFile(Path);
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

procedure DeleteUpdateLeftovers();
var
  Dir: string;
begin
  Dir := ExpandConstant('{app}');
  DeleteProgramFilesKeepData(Dir);
  // Fails while cache / logs / rendered_videos / Screenshots are still there.
  if InstallDirIsSafeToClean(Dir) then
    RemoveDir(RemoveBackslash(Dir));
end;

function UninstallKey: string;
begin
  // {{ escapes the brace. AppId itself must stay the same as [Setup].
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{8FDC961D-EEA5-4016-BB3C-7235F7E56619}}_is1';
end;

function RegisteredInstallDir: string;
begin
  Result := '';
  RegQueryStringValue(HKCU, UninstallKey, 'InstallLocation', Result);
  Result := RemoveBackslash(Result);
end;

function ExistingInstallAt(const Dir: string): Boolean;
begin
  Result := False;
  if not DirExists(Dir) then
    Exit;
  if FileExists(AddBackslash(Dir) + 'Steempeg.exe') then
  begin
    Result := True;
    Exit;
  end;
  // Broken install: the exe is gone, but Windows still points this folder at Steempeg.
  Result := (RegisteredInstallDir <> '') and SamePath(RegisteredInstallDir, Dir);
end;

function NextVersionPart(var Text: string): Integer;
var
  DotAt, Value: Integer;
begin
  Result := 0;
  if Text = '' then
    Exit;
  DotAt := Pos('.', Text);
  if DotAt = 0 then
  begin
    Value := StrToIntDef(Text, -1);
    Text := '';
  end
  else
  begin
    Value := StrToIntDef(Copy(Text, 1, DotAt - 1), -1);
    Delete(Text, 1, DotAt);
  end;
  Result := Value;
end;

function SetupIsNewerThan(const Installed: string): Boolean;
var
  SetupText, InstalledText: string;
  SetupPart, InstalledPart: Integer;
begin
  // False when either side is not a dotted number, so a repair is not assumed.
  Result := False;
  SetupText := Trim(ExpandConstant('{#SetupSetting("AppVersion")}'));
  InstalledText := Trim(Installed);
  if (SetupText = '') or (InstalledText = '') then
    Exit;
  repeat
    SetupPart := NextVersionPart(SetupText);
    InstalledPart := NextVersionPart(InstalledText);
    if (SetupPart < 0) or (InstalledPart < 0) then
      Exit;
    if SetupPart > InstalledPart then
    begin
      Result := True;
      Exit;
    end;
    if SetupPart < InstalledPart then
      Exit;
  until (SetupText = '') and (InstalledText = '');
end;

function InstalledVersionForDir(const Dir: string): string;
var
  Registered, Version: string;
begin
  Result := '';
  Registered := RegisteredInstallDir;
  if (Registered = '') or (not SamePath(Registered, Dir)) then
    Exit;
  if RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', Version) then
    Result := Trim(Version);
end;

procedure SelectRepairMode(DoRepair: Boolean);
begin
  if RepairModeChanging then
    Exit;
  RepairModeChanging := True;
  UpdateRadio.Checked := not DoRepair;
  RepairRadio.Checked := DoRepair;
  RepairModeChanging := False;
end;

procedure RepairModeClicked(Sender: TObject);
begin
  if RepairModeChanging then
    Exit;
  SelectRepairMode(Sender = RepairRadio);
end;

procedure ApplyRepairPageDefault;
var
  Dir, Installed: string;
  Newer: Boolean;
begin
  Dir := RemoveBackslash(WizardDirValue);
  if SamePath(Dir, RepairChoiceDir) then
    Exit;
  RepairChoiceDir := Dir;
  Installed := InstalledVersionForDir(Dir);
  Newer := (Installed <> '') and SetupIsNewerThan(Installed);
  if Newer or (Installed = '') then
    SelectRepairMode(False)
  else
    SelectRepairMode(True);
  if Installed <> '' then
    RepairNote.Caption :=
      'Steempeg ' + Installed + ' is already installed in this folder. This setup is ' +
      ExpandConstant('{#SetupSetting("AppVersion")}') + '.'
  else
    RepairNote.Caption :=
      'Steempeg is already installed in this folder.';
end;

procedure InitializeWizard;
var
  TopPos: Integer;
  Hint: TNewStaticText;
begin
  RepairChoiceDir := '';
  RepairPage := CreateCustomPage(wpSelectDir,
    'Existing installation',
    'Choose how to handle the Steempeg folder that is already here.');

  RepairNote := TNewStaticText.Create(RepairPage);
  RepairNote.Parent := RepairPage.Surface;
  RepairNote.Caption := 'Steempeg is already installed in this folder.';
  RepairNote.Left := 0;
  RepairNote.Top := 0;
  RepairNote.Width := RepairPage.SurfaceWidth;
  RepairNote.Height := ScaleY(40);
  RepairNote.AutoSize := False;
  RepairNote.WordWrap := True;

  TopPos := RepairNote.Top + RepairNote.Height + ScaleY(8);

  UpdateRadio := TNewRadioButton.Create(RepairPage);
  UpdateRadio.Parent := RepairPage.Surface;
  UpdateRadio.Caption := 'Update';
  UpdateRadio.Left := 0;
  UpdateRadio.Top := TopPos;
  UpdateRadio.Width := RepairPage.SurfaceWidth;
  UpdateRadio.Checked := True;
  UpdateRadio.OnClick := @RepairModeClicked;

  Hint := TNewStaticText.Create(RepairPage);
  Hint.Parent := RepairPage.Surface;
  Hint.Caption :=
    'Copy this setup''s files over the existing ones. Files this setup does not replace stay, including anything an in-app update added.';
  Hint.Left := ScaleX(16);
  Hint.Top := UpdateRadio.Top + UpdateRadio.Height + ScaleY(2);
  Hint.Width := RepairPage.SurfaceWidth - ScaleX(16);
  Hint.Height := ScaleY(44);
  Hint.AutoSize := False;
  Hint.WordWrap := True;

  TopPos := Hint.Top + Hint.Height + ScaleY(10);

  RepairRadio := TNewRadioButton.Create(RepairPage);
  RepairRadio.Parent := RepairPage.Surface;
  RepairRadio.Caption := 'Repair';
  RepairRadio.Left := 0;
  RepairRadio.Top := TopPos;
  RepairRadio.Width := RepairPage.SurfaceWidth;
  RepairRadio.OnClick := @RepairModeClicked;

  Hint := TNewStaticText.Create(RepairPage);
  Hint.Parent := RepairPage.Surface;
  Hint.Caption :=
    'Remove the program files, then copy this setup''s files back. cache, logs, rendered videos, and screenshots stay.';
  Hint.Left := ScaleX(16);
  Hint.Top := RepairRadio.Top + RepairRadio.Height + ScaleY(2);
  Hint.Width := RepairPage.SurfaceWidth - ScaleX(16);
  Hint.Height := ScaleY(44);
  Hint.AutoSize := False;
  Hint.WordWrap := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (RepairPage <> nil) and (PageID = RepairPage.ID) then
    Result := not ExistingInstallAt(RemoveBackslash(WizardDirValue));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (RepairPage <> nil) and (CurPageID = RepairPage.ID) then
    ApplyRepairPageDefault;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: string;
begin
  if CurStep <> ssInstall then
    Exit;
  if (RepairRadio = nil) or (not RepairRadio.Checked) then
    Exit;
  Dir := RemoveBackslash(ExpandConstant('{app}'));
  if not ExistingInstallAt(Dir) then
    Exit;
  Log('Repair: removing program files in ' + Dir);
  DeleteProgramFilesKeepData(Dir);
end;

// Settings → «Start Steempeg with Windows» can add the Run entry after install,
// which uninsdeletevalue above does not know about.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Steempeg');
    DeleteUpdateLeftovers();
  end;
end;
