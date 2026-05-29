#!/usr/bin/env pwsh
# Starts all Fibey services in a single window with prefixed, color-coded output.
# Usage: powershell -NoExit -File scripts\start-all.ps1

$ErrorActionPreference = "Continue"
$r = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$services = @(
  @{ Name = "INVENTORY";  Cwd = "$r\services\inventory-mcp";           Cmd = "uv sync; uv run python server.py" },
  @{ Name = "WORKORDERS"; Cwd = "$r\services\work-orders-api";         Cmd = "uv sync; uv run python server.py" },
  @{ Name = "DASHBOARD";  Cwd = "$r\services\status-dashboard\public"; Cmd = "python -m http.server 8003" },
  @{ Name = "GATEWAY";    Cwd = $r;                                    Cmd = "uv run uvicorn fibey.gateway.api_server:app --reload --port 8080" },
  @{ Name = "UI";         Cwd = "$r\ui";                               Cmd = "if (-not (Test-Path node_modules)) { npm install }; npm run dev" }
)

$colors = @{
  INVENTORY  = "Cyan"
  WORKORDERS = "Yellow"
  DASHBOARD  = "Magenta"
  GATEWAY    = "Green"
  UI         = "Blue"
}

$jobs = foreach ($s in $services) {
  Start-Job -Name $s.Name -ScriptBlock {
    param($cwd, $cmd)
    $ErrorActionPreference = "Continue"
    Set-Location $cwd
    # Run via Invoke-Expression; merge stderr into stdout and stringify so
    # native-command stderr lines don't surface as ErrorRecord objects
    # that would trip the parent loop.
    Invoke-Expression "$cmd 2>&1" | ForEach-Object { "$_" }
  } -ArgumentList $s.Cwd, $s.Cmd
}

Write-Host ""
Write-Host "Started $($jobs.Count) services. Press Ctrl+C to stop all." -ForegroundColor White
Write-Host ""

try {
  while ($true) {
    foreach ($j in $jobs) {
      $out = Receive-Job -Job $j -ErrorAction Continue 2>&1
      if ($out) {
        foreach ($line in $out) {
          Write-Host "[$($j.Name)] " -ForegroundColor $colors[$j.Name] -NoNewline
          Write-Host $line
        }
      }
    }
    Start-Sleep -Milliseconds 250
  }
}
finally {
  Write-Host ""
  Write-Host "Stopping all services..." -ForegroundColor Red
  $jobs | Stop-Job -ErrorAction SilentlyContinue
  $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
}
