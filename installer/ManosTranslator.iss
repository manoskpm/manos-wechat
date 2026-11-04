; 바로통 설치 파일 (Inno Setup)
; 관리자 권한 없이 사용자 폴더에 설치 → 자동 업데이트가 스스로 파일을 바꿀 수 있음
#define AppVer GetEnv("APP_VERSION")

[Setup]
AppId={{8F3A2C1E-5B7D-4E9A-9C21-6D4F0B7A1E33}
AppName=바로통
AppVersion={#AppVer}
AppPublisher=Manos
DefaultDirName={localappdata}\Programs\ManosTranslator
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=ManosTranslator-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayName=바로통
UninstallDisplayIcon={app}\ManosTranslator.exe
SetupIconFile=..\assets\icon.ico

[Files]
Source: "..\dist\ManosTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 예전 이름(발주 번역기)의 시작 메뉴 폴더 정리
Type: filesandordirs; Name: "{userprograms}\발주 번역기"

[Icons]
Name: "{userdesktop}\위챗+번역기"; Filename: "{app}\ManosTranslator.exe"; Parameters: "--with-wechat"; IconFilename: "{app}\ManosTranslator.exe"
Name: "{userprograms}\바로통\위챗+번역기"; Filename: "{app}\ManosTranslator.exe"; Parameters: "--with-wechat"; IconFilename: "{app}\ManosTranslator.exe"
Name: "{userprograms}\바로통\번역기만 켜기"; Filename: "{app}\ManosTranslator.exe"
Name: "{userprograms}\바로통\바로통 삭제"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ManosTranslator.exe"; Parameters: "--with-wechat"; Description: "지금 위챗과 번역기 켜기"; Flags: nowait postinstall skipifsilent
