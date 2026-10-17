$ErrorActionPreference = "Stop"

# Run this from the cloned repository at C:\KakaoBot\KKanggallbot.
# The Python environment is the existing C:\KakaoBot\.venv.
$RepoPath = $PSScriptRoot
$ParentPath = Split-Path -Parent $RepoPath
$PythonPath = Join-Path $ParentPath ".venv\Scripts\python.exe"
$BotScriptPath = Join-Path $RepoPath "bot.py"
$Branch = "main"
$CheckIntervalSeconds = 30
$LogPath = Join-Path $ParentPath "logs"
$BotProcess = $null
$FailedCommit = $null

function Stop-Bot {
    if ($null -ne $script:BotProcess) {
        $runningProcess = Get-Process -Id $script:BotProcess.Id -ErrorAction SilentlyContinue
        if ($null -ne $runningProcess) {
            Write-Host "Stopping bot process $($script:BotProcess.Id)..."
            Stop-Process -Id $script:BotProcess.Id -Force -ErrorAction SilentlyContinue
        }
        $script:BotProcess.WaitForExit()
    }
    $script:BotProcess = $null
}

function Start-Bot {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdout = Join-Path $LogPath "bot-$stamp.out.log"
    $stderr = Join-Path $LogPath "bot-$stamp.err.log"
    Write-Host "Starting bot.py..."
    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList "bot.py" `
        -WorkingDirectory $RepoPath `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru
    return $process
}

if (-not (Test-Path $PythonPath)) {
    throw "Python 가상환경을 찾을 수 없습니다: $PythonPath"
}
if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
    throw "Git 저장소가 아닙니다. 먼저 이 저장소를 C:\KakaoBot\KKanggallbot 에 clone 하세요."
}
New-Item -ItemType Directory -Force -Path $LogPath | Out-Null

# Clear duplicate bot.py processes left by an earlier watcher run.
$staleBotProcesses = @(
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.IndexOf($BotScriptPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
        }
)
if ($staleBotProcesses.Count -gt 0) {
    Write-Host "Stopping $($staleBotProcesses.Count) previous bot.py process(es)..."
    foreach ($staleProcess in $staleBotProcesses) {
        Stop-Process -Id $staleProcess.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Checking GitHub main branch..."
& git -C $RepoPath fetch --quiet origin $Branch
if ($LASTEXITCODE -ne 0) {
    throw "GitHub에서 최신 버전을 확인하지 못했습니다."
}
$localCommit = (& git -C $RepoPath rev-parse HEAD).Trim()
$remoteCommit = (& git -C $RepoPath rev-parse "origin/$Branch").Trim()
if ($localCommit -ne $remoteCommit) {
    & git -C $RepoPath pull --ff-only origin $Branch
    if ($LASTEXITCODE -ne 0) {
        throw "저장소 업데이트에 실패했습니다."
    }
}

try {
    $BotProcess = Start-Bot
    while ($true) {
        Start-Sleep -Seconds $CheckIntervalSeconds

        & git -C $RepoPath fetch --quiet origin $Branch
        if ($LASTEXITCODE -eq 0) {
            $localCommit = (& git -C $RepoPath rev-parse HEAD).Trim()
            $remoteCommit = (& git -C $RepoPath rev-parse "origin/$Branch").Trim()

            if ($localCommit -ne $remoteCommit) {
                Write-Host "New GitHub commit detected. Updating and restarting..."
                Stop-Bot
                & git -C $RepoPath pull --ff-only origin $Branch
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Updated to $((& git -C $RepoPath rev-parse --short HEAD).Trim())"
                    $FailedCommit = $null
                }
                else {
                    Write-Host "Update failed; restarting the current local version and retrying later."
                }
                $BotProcess = Start-Bot
            }
        }
        else {
            Write-Host "GitHub check failed; bot keeps running and will retry."
        }

        if ($null -ne $BotProcess) {
            $runningProcess = Get-Process -Id $BotProcess.Id -ErrorAction SilentlyContinue
            if ($null -eq $runningProcess) {
                $localCommit = (& git -C $RepoPath rev-parse HEAD).Trim()
                if ($FailedCommit -ne $localCommit) {
                    Write-Host "Bot exited. Check the latest log in $LogPath; waiting for a new GitHub commit before retrying."
                    $FailedCommit = $localCommit
                }
                $BotProcess = $null
            }
        }
    }
}
finally {
    Stop-Bot
}
