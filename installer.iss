; Research Agent 安装程序配置
; 使用 Inno Setup 编译 (https://jrsoftware.org/isinfo.php)
;
; 编译步骤:
;   1. 先执行 scripts\build_desktop.ps1 生成 dist\ResearchAgent\
;   2. 使用 Inno Setup 打开此文件并点击 Build → Compile

#define MyAppName "Research Agent"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "Research Agent Team"
#define MyAppExeName "ResearchAgent.exe"

[Setup]
AppId={{B8E3F2A1-4D5C-6E7F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=ResearchAgent_Setup_{#MyAppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppName}
DisableProgramGroupPage=yes
RestartIfNeededByRun=no
CreateAppDir=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
Name: "startupicon"; Description: "开机自启动"; GroupDescription: "启动选项:"; Flags: unchecked

[Files]
; 主程序文件
Source: "dist\ResearchAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"
Root: HKCU; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"

[Code]
function InitializeSetup(): Boolean;
var
  ExistingInstallPath: String;
begin
  // 检测旧版本并提示是否覆盖安装
  if RegQueryStringValue(HKCU, 'Software\{#MyAppName}', 'InstallPath', ExistingInstallPath) then
  begin
    if MsgBox('检测到旧版本的 ' + '{#MyAppName}' + '，是否继续安装？' + #13#10 + '(将自动保留用户数据)', mbConfirmation, MB_YESNO) = IDNO then
      Result := False
    else
      Result := True
    end
  end
  else
    Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 创建用户数据目录
    ForceDirectories(ExpandConstant('{userappdata}\ResearchAgent'));

    // 写入版本信息
    RegWriteStringValue(
      HKCU,
      'Software\{#MyAppName}',
      'InstallDate',
      GetDateTimeString('yyyy-mm-dd', '-', ':')
    );
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 询问是否保留用户数据
    if MsgBox('是否保留用户数据（配置、历史记录、数据库等）？', mbConfirmation, MB_YESNO) = IDNO then
    begin
      DelTree(ExpandConstant('{userappdata}\ResearchAgent'), True, True, True);
    end;
  end;
end;
