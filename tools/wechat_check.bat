@echo off
rem WeChat accessibility check - read only, does not control or change WeChat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $i=$s.LastIndexOf('#PS'+'START'); Invoke-Expression $s.Substring($i)"
echo.
echo Done. Please send wechat_check.txt on your Desktop.
pause
exit /b
#PSSTART
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$desk = [Environment]::GetFolderPath('Desktop')
$out = Join-Path $desk 'wechat_check.txt'
$wx = ([string][char]0x5FAE) + ([string][char]0x4FE1)
$names = @($wx, 'WeChat', 'Weixin')
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine('time: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
[void]$sb.AppendLine('windows: ' + [Environment]::OSVersion.VersionString)
$narr = Get-Process -Name Narrator -ErrorAction SilentlyContinue
[void]$sb.AppendLine('narrator running: ' + [bool]$narr)
$AE = [System.Windows.Automation.AutomationElement]
$root = $AE::RootElement
$tops = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$script:count = 0
function Dump($el, $depth) {
  if ($script:count -ge 8000 -or $depth -gt 45) { return }
  $script:count++
  try {
    $c = $el.Current
    $r = $c.BoundingRectangle
    $line = ('  ' * $depth) + $c.ControlType.ProgrammaticName.Replace('ControlType.', '') + ' | ' + $c.ClassName + ' | ' + $c.Name + ' | ' + [int]$r.X + ',' + [int]$r.Y + ',' + [int]$r.Width + ',' + [int]$r.Height
    [void]$script:sb.AppendLine($line)
  } catch { [void]$script:sb.AppendLine(('  ' * $depth) + '(error) ' + $_) }
  try { $ch = $walker.GetFirstChild($el) } catch { $ch = $null }
  while ($ch -ne $null) {
    Dump $ch ($depth + 1)
    try { $ch = $walker.GetNextSibling($ch) } catch { $ch = $null }
  }
}
$found = 0
foreach ($w in $tops) {
  $n = ''
  try { $n = $w.Current.Name } catch {}
  if ($names -contains $n) {
    $found++
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('===== window: ' + $n + ' =====')
    $t0 = Get-Date
    $script:count = 0
    Dump $w 0
    [void]$sb.AppendLine('nodes: ' + $script:count + '  seconds: ' + [math]::Round(((Get-Date) - $t0).TotalSeconds, 2))
  }
}
[void]$sb.AppendLine('wechat windows found: ' + $found)
[IO.File]::WriteAllText($out, $sb.ToString(), [Text.Encoding]::UTF8)
Write-Host ('saved: ' + $out + '  (wechat windows: ' + $found + ')')
