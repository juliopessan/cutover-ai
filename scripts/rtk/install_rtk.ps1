Param()
Write-Output "Installing RTK for Windows (downloads zip from releases)..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/rtk-ai/rtk/releases/latest"
$asset = $release.assets | Where-Object { $_.name -match "rtk-x86_64-pc-windows-msvc.zip" } | Select-Object -First 1
if (-not $asset) {
  Write-Error "Windows release asset not found. Download manually from https://github.com/rtk-ai/rtk/releases"
  exit 1
}
$out = Join-Path -Path ".tools\rtk" -ChildPath $asset.name
New-Item -ItemType Directory -Path ".tools\rtk" -Force | Out-Null
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $out -UseBasicParsing
Expand-Archive -LiteralPath $out -DestinationPath ".tools\rtk" -Force
Write-Output "RTK extracted to .tools\rtk. Add this to PATH or run .\.tools\rtk\rtk.exe"
