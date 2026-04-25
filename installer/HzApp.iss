#define MyAppName "Hz Power Switcher"
#define MyAppExeName "HzApp.exe"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RafpcAppDesignSolutions"
#define MyAppURL "https://github.com/RafpcAppDesignSolutions/HzApp"
#define MyAppSourceDir "..\\dist"

[Setup]
AppId={{B5C1B78B-5DB2-4D60-8E47-6A38E0E4A2A1}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Hz Power Switcher
DisableProgramGroupPage=yes
OutputBaseFilename=HzApp-Setup
SetupIconFile=..\hz_power_switcher.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\\Hz Power Switcher"; Filename: "{app}\\{#MyAppExeName}"
Name: "{autodesktop}\\Hz Power Switcher"; Filename: "{app}\\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\\{#MyAppExeName}"; Description: "Launch Hz Power Switcher"; Flags: nowait postinstall skipifsilent
