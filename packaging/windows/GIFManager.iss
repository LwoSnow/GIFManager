; GIFManager Next — Inno Setup script.
;
; Built by CI as:
;     iscc /DMyAppVersion=<version> /DMySource=<dist\GIFManager> packaging\windows\GIFManager.iss
; Output: GIFManager-Setup-<version>.exe
;
; # Why the version and the source come in as defines
;
; The version has ONE authority, `gifmanager/__init__.py`, read by the workflow. Copying it into this
; file would create a second place to forget; passing it in means a stale number is impossible rather than
; unlikely. The source directory is a define for the same reason: it is `dist\GIFManager` in CI and
; anywhere at all locally.
;
; 由 CI 这样构建：
;     iscc /DMyAppVersion=<版本> /DMySource=<dist\GIFManager> packaging\windows\GIFManager.iss
; 输出：GIFManager-Setup-<版本>.exe
;
; # 为什么版本与源目录用 define 传入
;
; 版本只有"一个"权威来源——`gifmanager/__init__.py`，由 workflow 读取。把它抄进本文件会制造第二处
; 需要记得同步的地方；改为传入，则"过期版本号"是不可能，而不是"不太可能"。源目录同理：CI 里是
; `dist\GIFManager`，本地可以在任何地方。

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#ifndef MySource
  #define MySource "..\..\dist\GIFManager"
#endif

#define MyAppName "GIFManager"
#define MyAppPublisher "LwoSnow"
#define MyAppExeName "GIFManager.exe"

[Setup]
; A stable AppId keeps upgrades in place instead of installing a second copy.
; 稳定的 AppId 使升级就地替换，而不是再装一份。
AppId={{8C1F5D42-6B7A-4B93-9E4C-2A5D7E9F1B03}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/LwoSnow/GIFManager
AppSupportURL=https://github.com/LwoSnow/GIFManager/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
; A 64-bit-only payload: the bundled Qt libraries are x86-64, so installing into the 32-bit Program Files
; would produce an application that cannot load them.
; 仅 64 位的负载：随包的 Qt 库是 x86-64，装进 32 位 Program Files 会得到一个无法加载它们的程序。
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install by default: a tray utility should not need an administrator, and the application keeps
; its data under %LOCALAPPDATA% anyway.
; 默认按用户安装：托盘工具不该需要管理员权限，而程序本来就把数据放在 %LOCALAPPDATA%。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=GIFManager-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; The application is a single frameless window that hides instead of exiting, so the installer must not
; close it silently - it asks the running copy to quit through its own single-instance channel.
; 程序是一个隐藏而非退出的无边框窗口，因此安装器不得静默关闭它——它通过自身的单实例通道请求运行中的
; 副本退出。
CloseApplications=yes
RestartApplications=no

; ONLY the bundled language.
;
; Inno Setup ships about twenty translated message files, and Simplified Chinese is NOT one of them -
; listing it makes ISCC fail with "could not read ... ChineseSimplified.isl". Adding a community
; translation would mean downloading it at build time, which turns a packaging step into a network
; dependency; the APPLICATION is still localised as usual, so only the installer's own buttons are English.
; 只用随附语言。
;
; Inno Setup 附带约二十种翻译消息文件，而简体中文"不在"其中——列上它会让 ISCC 以
; "could not read ... ChineseSimplified.isl" 失败。引入社区翻译意味着在构建期下载它，那会把一个打包
; 步骤变成网络依赖；而"程序本身"照常本地化，因此只有安装器自己的按钮是英文。
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start with Windows / 开机启动"; GroupDescription: "Startup / 启动"; Flags: unchecked

[Files]
Source: "{#MySource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; NO `[UninstallDelete]` on the payload.
;
; A previous draft deleted `{app}\_internal\PySide6\qml` to "clear Qt's cache", which would have removed
; Qt's own QML modules - part of the installation, not scratch data. Qt keeps its caches under
; `%LOCALAPPDATA%`, which the uninstaller must leave alone anyway: it belongs to the user, and the
; application's data directory lives beside it.
; 不对负载使用 `[UninstallDelete]`。
;
; 上一版草稿删除 `{app}\_internal\PySide6\qml` 以"清理 Qt 缓存"，那会移除 Qt 自身的 QML 模块——它们是
; 安装内容的一部分，不是临时数据。Qt 的缓存位于 `%LOCALAPPDATA%`，而卸载器本就应当不去碰它：它属于
; 用户，且程序的数据目录就在它旁边。
