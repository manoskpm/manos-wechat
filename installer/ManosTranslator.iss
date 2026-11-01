; 발주 번역기 설치 파일 (Inno Setup)
; 관리자 권한 없이 사용자 폴더에 설치 → 자동 업데이트가 스스로 파일을 바꿀 수 있음
#define AppVer GetEnv("APP_VERSION")

[Setup]
AppId={{8F3A2C1E-5B7D-4E9A-9C21-6D4F0B7A1E33}
AppName=발주 번역기 (위챗)
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
UninstallDisplayName=발주 번역기 (위챗)
UninstallDisplayIcon={app}\ManosTranslator.exe

[Files]
Source: "..\dist\ManosTranslator.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\위챗+번역기"; Filename: "{app}\ManosTranslator.exe"; Parameters: "--with-wechat"; IconFilename: "{code:WeChatIcon}"
Name: "{userprograms}\발주 번역기\위챗+번역기"; Filename: "{app}\ManosTranslator.exe"; Parameters: "--with-wechat"; IconFilename: "{code:WeChatIcon}"
Name: "{userprograms}\발주 번역기\번역기만 켜기"; Filename: "{app}\ManosTranslator.exe"
Name: "{userprograms}\발주 번역기\발주 번역기 삭제"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ManosTranslator.exe"; Parameters: "--with-wechat"; Description: "지금 위챗과 번역기 켜기"; Flags: nowait postinstall skipifsilent

[Code]
{ 바로가기 아이콘을 위챗 아이콘으로 (위챗을 못 찾으면 번역기 아이콘) }
function WeChatIcon(Param: String): String;
var
  P: String;
begin
  Result := ExpandConstant('{app}\ManosTranslator.exe');
  if RegQueryStringValue(HKCU, 'Software\Tencent\Weixin', 'InstallPath', P) and FileExists(P + '\Weixin.exe') then
  begin
    Result := P + '\Weixin.exe';
    Exit;
  end;
  if RegQueryStringValue(HKCU, 'Software\Tencent\WeChat', 'InstallPath', P) and FileExists(P + '\WeChat.exe') then
  begin
    Result := P + '\WeChat.exe';
    Exit;
  end;
  P := ExpandConstant('{commonpf64}\Tencent\Weixin\Weixin.exe');
  if FileExists(P) then begin Result := P; Exit; end;
  P := ExpandConstant('{commonpf32}\Tencent\Weixin\Weixin.exe');
  if FileExists(P) then begin Result := P; Exit; end;
  P := ExpandConstant('{commonpf32}\Tencent\WeChat\WeChat.exe');
  if FileExists(P) then begin Result := P; Exit; end;
  P := ExpandConstant('{commonpf64}\Tencent\WeChat\WeChat.exe');
  if FileExists(P) then begin Result := P; Exit; end;
end;
