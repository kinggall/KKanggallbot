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

# Only one watcher may manage this checkout. A second watcher must not kill
# the first watcher's bot or race it during an update.
$mutexKey = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($RepoPath.ToLowerInvariant())).Replace('/', '_')
$WatcherMutex = New-Object Threading.Mutex($false, "Local\KakaoBot-$mutexKey")
try { $ownsWatcher = $WatcherMutex.WaitOne(0) }
catch [Threading.AbandonedMutexException] { $ownsWatcher = $true }
if (-not $ownsWatcher) {
    $WatcherMutex.Dispose()
    throw "A watcher is already running for $RepoPath. Keep only the existing watcher window."
}

function Stop-BotTree([int]$ProcessId) {
    # Windows venv python.exe may launch a child python.exe which owns Flask.
    # Killing only the launcher leaves that server running with old aliases.
    $ErrorActionPreference = 'Continue'
    & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
}

function Remove-DuplicateBots {
    $processes = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'")
    $ownedIds = @{}
    if ($null -ne $script:BotProcess -and -not $script:BotProcess.HasExited) {
        $ownedIds[[int]$script:BotProcess.Id] = $true
        do {
            $added = $false
            foreach ($process in $processes) {
                if ($ownedIds.ContainsKey([int]$process.ParentProcessId) -and -not $ownedIds.ContainsKey([int]$process.ProcessId)) {
                    $ownedIds[[int]$process.ProcessId] = $true
                    $added = $true
                }
            }
        } while ($added)
    }
    $legacyScript = Join-Path $ParentPath 'bot.py'
    foreach ($process in $processes) {
        if ($ownedIds.ContainsKey([int]$process.ProcessId) -or -not $process.CommandLine) { continue }
        $command = $process.CommandLine
        $isOurBot = $command.IndexOf($BotScriptPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $command.IndexOf($legacyScript, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            ($process.ExecutablePath -and $process.ExecutablePath.Equals($PythonPath, [StringComparison]::OrdinalIgnoreCase) -and
             $command -match '(?i)(?:^|\s|")\.?[\\/]?bot\.py(?:$|\s|")')
        if ($isOurBot -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
            Write-Host "Stopping stale bot tree $($process.ProcessId)..."
            Stop-BotTree $process.ProcessId
        }
    }
}

function Stop-Bot {
    if ($null -ne $script:BotProcess) {
        $runningProcess = Get-Process -Id $script:BotProcess.Id -ErrorAction SilentlyContinue
        if ($null -ne $runningProcess) {
            Write-Host "Stopping bot process $($script:BotProcess.Id)..."
            Stop-BotTree $script:BotProcess.Id
        }
        $null = $script:BotProcess.WaitForExit(10000)
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
        -ArgumentList "-u `"$BotScriptPath`"" `
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

Remove-DuplicateBots

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

        Remove-DuplicateBots

        & git -C $RepoPath fetch --quiet origin $Branch
        if ($LASTEXITCODE -eq 0) {
            $localCommit = (& git -C $RepoPath rev-parse HEAD).Trim()
            $remoteCommit = (& git -C $RepoPath rev-parse "origin/$Branch").Trim()

            if ($localCommit -ne $remoteCommit) {
                Write-Host "New GitHub commit detected. Updating and restarting..."
                Stop-Bot
                Remove-DuplicateBots
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
    $WatcherMutex.ReleaseMutex()
    $WatcherMutex.Dispose()
}
