; Steempeg per-user installer (Inno Setup 6).
;
; Packs the PyInstaller folder built by newver_compilator.py (dist\Steempeg)
; into Steempeg_v<version>_setup.exe. No admin rights: installs to
; %LocalAppData%\Programs\Steempeg, so the in-app updater can still write there.
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
// Settings → «Start Steempeg with Windows» can add the Run entry after install,
// which uninsdeletevalue above does not know about.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Steempeg');
end;
