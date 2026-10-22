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
// Inno only deletes files it copied at install time. An in-app update adds new
// files and old_version_v* / pre_restore_v* trees, and those would survive
// uninstall. User data that lives in {app} must stay.

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

procedure DeleteUpdateLeftovers();
var
  Dir, Path, Name: string;
  FindRec: TFindRec;
begin
  Dir := ExpandConstant('{app}');
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
  // Fails while cache / logs / rendered_videos / Screenshots are still there.
  RemoveDir(RemoveBackslash(Dir));
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
