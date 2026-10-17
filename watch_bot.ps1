$ErrorActionPreference = "Stop"

# Run this from the cloned repository at C:\KakaoBot\KKanggallbot.
# The Python environment is the existing C:\KakaoBot\.venv.
$RepoPath = $PSScriptRoot
$ParentPath = Split-Path -Parent $RepoPath
$PythonPath = Join-Path $ParentPath ".venv\Scripts\python.exe"
$Branch = "main"
$CheckIntervalSeconds = 30
$LogPath = Join-Path $ParentPath "logs"
$BotProcess = $null

function Stop-Bot {
    if ($null -ne $script:BotProcess -and -not $script:BotProcess.HasExited) {
        Write-Host "Stopping bot process $($script:BotProcess.Id)..."
        Stop-Process -Id $script:BotProcess.Id -Force
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

Write-Host "Checking GitHub main branch..."
& git -C $RepoPath fetch origin $Branch
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

        & git -C $RepoPath fetch origin $Branch
        if ($LASTEXITCODE -eq 0) {
            $localCommit = (& git -C $RepoPath rev-parse HEAD).Trim()
            $remoteCommit = (& git -C $RepoPath rev-parse "origin/$Branch").Trim()

            if ($localCommit -ne $remoteCommit) {
                Write-Host "New GitHub commit detected. Updating and restarting..."
                Stop-Bot
                & git -C $RepoPath pull --ff-only origin $Branch
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Updated to $((& git -C $RepoPath rev-parse --short HEAD).Trim())"
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

        if ($null -eq $BotProcess -or $BotProcess.HasExited) {
            Write-Host "Bot stopped unexpectedly; restarting it."
            $BotProcess = Start-Bot
        }
    }
}
finally {
    Stop-Bot
}
