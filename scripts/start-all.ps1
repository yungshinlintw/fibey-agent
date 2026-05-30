#!/usr/bin/env pwsh
# Starts all Fibey services in a single window with prefixed, color-coded output.
# Press Ctrl+C to stop all services in parallel.
#
# Usage:
#   powershell -NoExit -File scripts\start-all.ps1
#   .\scripts\start-all.ps1

$ErrorActionPreference = "Continue"
$r = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Force UTF-8 so emoji and non-ASCII chars in prompts don't crash on Windows.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8       = "1"

$services = @(
  @{ Name = "INVENTORY";  Cwd = "$r\services\inventory-mcp";           Cmd = "uv sync; uv run python server.py";                                            Port = 8001 },
  @{ Name = "WORKORDERS"; Cwd = "$r\services\work-orders-api";         Cmd = "uv sync; uv run python server.py";                                            Port = 8002 },
  @{ Name = "DASHBOARD";  Cwd = "$r\services\status-dashboard\public"; Cmd = "python -m http.server 8003";                                                  Port = 8003 },
  @{ Name = "GATEWAY";    Cwd = $r;                                    Cmd = "uv run uvicorn fibey.gateway.api_server:app --host 0.0.0.0 --port 8090";     Port = 8090 },
  @{ Name = "UI";         Cwd = "$r\ui";                               Cmd = "if (-not (Test-Path node_modules)) { npm install }; npm run dev";            Port = 5173 }
)

$colors = @{
  INVENTORY  = "Cyan"
  WORKORDERS = "Yellow"
  DASHBOARD  = "Magenta"
  GATEWAY    = "Green"
  UI         = "Blue"
}

# Pre-flight: kill anything already listening on our ports so we don't race
# against stale uvicorn / vite processes. Done in parallel for speed.
$preflightPids = Get-NetTCPConnection -State Listen -LocalPort ($services.Port) -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique
if ($preflightPids) {
  Write-Host "Killing stale processes on ports: $(($services.Port) -join ', ')" -ForegroundColor DarkYellow
  $preflightPids | ForEach-Object -Parallel { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } -ThrottleLimit 8
  Start-Sleep -Milliseconds 500
}

$jobs = foreach ($s in $services) {
  Start-Job -Name $s.Name -ScriptBlock {
    param($cwd, $cmd)
    $ErrorActionPreference = "Continue"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8       = "1"
    Set-Location $cwd
    # Merge stderr → stdout and stringify so native-command stderr lines don't
    # surface as ErrorRecord objects that would trip the parent loop.
    Invoke-Expression "$cmd 2>&1" | ForEach-Object { "$_" }
  } -ArgumentList $s.Cwd, $s.Cmd
}

Write-Host ""
Write-Host "Started $($jobs.Count) services:" -ForegroundColor White
foreach ($s in $services) {
  Write-Host ("  [{0,-10}] http://localhost:{1}" -f $s.Name, $s.Port) -ForegroundColor $colors[$s.Name]
}
Write-Host ""
Write-Host "Press Ctrl+C to stop all services." -ForegroundColor White
Write-Host ""

# Stop everything in parallel — sequential Stop-Job can take many seconds.
function Stop-AllServices {
  param($jobs, $services)
  Write-Host ""
  Write-Host "Stopping all services in parallel..." -ForegroundColor Red

  # 1. Stop background jobs in parallel.
  $jobs | ForEach-Object -Parallel {
    Stop-Job -Job $_ -ErrorAction SilentlyContinue
    Remove-Job -Job $_ -Force -ErrorAction SilentlyContinue
  } -ThrottleLimit 8

  # 2. Kill any leftover processes still holding our ports in parallel.
  $ports = $services.Port
  $leftoverPids = Get-NetTCPConnection -State Listen -LocalPort $ports -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
  if ($leftoverPids) {
    $leftoverPids | ForEach-Object -Parallel {
      Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    } -ThrottleLimit 8
  }

  Write-Host "All services stopped." -ForegroundColor Red
}

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
  Stop-AllServices -jobs $jobs -services $services
}
