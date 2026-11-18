[CmdletBinding()]
param(
    [ValidateSet('Auto', 'Docker', 'WSL')]
    [string]$Mode = 'Auto',
    [string]$WorkDir = 'work',
    [string]$OutDir = 'out',
    [string]$WslDistro = '',
    [string]$DockerImage = 'archlinux:latest',
    [switch]$SkipRepoSetup,
    [switch]$DryRun,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

function ConvertTo-PosixRelOrWslPath {
    param(
        [string]$InputPath,
        [string]$Style = 'Docker'
    )
    if ($InputPath -match '^[A-Za-z]:\\') {
        $drive = $InputPath.Substring(0, 1).ToLowerInvariant()
        $rest = $InputPath.Substring(2) -replace '\\', '/'
        if ($Style -eq 'WSL') {
            return "/mnt/$drive$rest"
        }
        return $InputPath -replace '\\', '/'
    }
    return ($InputPath -replace '\\', '/')
}

function ConvertTo-WslPath {
    param([string]$WinPath)
    if ($WinPath -match '^([A-Za-z]):\\(.*)$') {
        $drive = $Matches[1].ToLowerInvariant()
        $rest = $Matches[2] -replace '\\', '/'
        return "/mnt/$drive/$rest"
    }
    if ($WinPath -match '^([A-Za-z]):/?$') {
        $drive = $Matches[1].ToLowerInvariant()
        return "/mnt/$drive"
    }
    return ($WinPath -replace '\\', '/')
}

function Resolve-DockerHostMount {
    param(
        [string]$InputPath,
        [string]$RepoRootPath,
        [string]$ContainerMount
    )
    $trimmed = $InputPath.Trim()
    if (-not [System.IO.Path]::IsPathRooted($trimmed)) {
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $RepoRootPath $trimmed))
    }
    else {
        $candidate = [System.IO.Path]::GetFullPath($trimmed)
    }
    $repoFull = [System.IO.Path]::GetFullPath($RepoRootPath).TrimEnd('\', '/')
    $candNorm = $candidate.TrimEnd('\', '/')

    if ($candNorm.Equals($repoFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return [ordered]@{
            container_path = '/workspace'
            host_mount     = ''
        }
    }
    if ($candNorm.StartsWith($repoFull + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
        $candNorm.StartsWith($repoFull + '/', [System.StringComparison]::OrdinalIgnoreCase)) {
        $rel = $candNorm.Substring($repoFull.Length + 1) -replace '\\', '/'
        return [ordered]@{
            container_path = $rel
            host_mount     = ''
        }
    }
    return [ordered]@{
        container_path = $ContainerMount
        host_mount     = $candNorm
    }
}

function Get-WslDistros {
    $wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -eq $wslCmd) {
        return @()
    }
    try {
        $raw = & wsl.exe -l -q 2>$null
        if ($LASTEXITCODE -ne 0 -or $null -eq $raw) {
            return @()
        }
        $list = @()
        foreach ($line in $raw) {
            $cleaned = ($line -replace "`0", '').Trim()
            if (-not [string]::IsNullOrWhiteSpace($cleaned)) {
                $list += $cleaned
            }
        }
        return $list
    }
    catch {
        return @()
    }
}

function Test-DockerAvailable {
    param([switch]$CheckDaemon)
    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $dockerCmd) {
        return $false
    }
    if (-not $CheckDaemon) {
        return $true
    }
    try {
        $osType = & docker info --format '{{.OSType}}' 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        if ($null -eq $osType) {
            return $false
        }
        return ($osType.Trim().ToLowerInvariant() -eq 'linux')
    }
    catch {
        return $false
    }
}

$distros = Get-WslDistros
$dockerCli = Test-DockerAvailable
$dockerDaemon = $false
if ($dockerCli -and -not $DryRun) {
    $dockerDaemon = Test-DockerAvailable -CheckDaemon
}

$resolvedBackend = $Mode
$backendAvailable = $false

if ($Mode -eq 'Auto') {
    if ($distros.Count -gt 0) {
        $resolvedBackend = 'WSL'
        $backendAvailable = $true
    }
    elseif ($DryRun -and $dockerCli) {
        $resolvedBackend = 'Docker'
        $backendAvailable = $true
    }
    elseif (-not $DryRun -and $dockerDaemon) {
        $resolvedBackend = 'Docker'
        $backendAvailable = $true
    }
    else {
        $resolvedBackend = 'Docker'
        $backendAvailable = $false
    }
}
elseif ($Mode -eq 'WSL') {
    if (-not [string]::IsNullOrWhiteSpace($WslDistro)) {
        $backendAvailable = ($distros -contains $WslDistro)
    }
    else {
        $backendAvailable = ($distros.Count -gt 0)
    }
}
elseif ($Mode -eq 'Docker') {
    if ($DryRun) {
        $backendAvailable = $dockerCli
    }
    else {
        $backendAvailable = $dockerDaemon
    }
}

$WorkDirPosix = ConvertTo-PosixRelOrWslPath -InputPath $WorkDir -Style $resolvedBackend
$OutDirPosix = ConvertTo-PosixRelOrWslPath -InputPath $OutDir -Style $resolvedBackend

$skipFlag = ''
if ($SkipRepoSetup) {
    $skipFlag = ' --skip-repo-setup'
}

$targetDistro = $WslDistro
if ([string]::IsNullOrWhiteSpace($targetDistro)) {
    $preferred = $null
    foreach ($d in $distros) {
        if ($d -match 'arch|cachy') {
            $preferred = $d
            break
        }
    }
    if ($null -ne $preferred) {
        $targetDistro = $preferred
    }
    elseif ($distros.Count -gt 0) {
        $targetDistro = $distros[0]
    }
    else {
        $targetDistro = '<arch-or-ubuntu-distro>'
    }
}

$commandArgs = @()
if ($resolvedBackend -eq 'Docker') {
    $workMap = Resolve-DockerHostMount -InputPath $WorkDir -RepoRootPath $RepoRoot -ContainerMount '/kite-work'
    $outMap = Resolve-DockerHostMount -InputPath $OutDir -RepoRootPath $RepoRoot -ContainerMount '/kite-out'
    $WorkDirPosix = $workMap.container_path
    $OutDirPosix = $outMap.container_path

    $dockerMounts = @('-v', "${RepoRoot}:/workspace")
    $mountStringParts = @("-v `"${RepoRoot}:/workspace`"")
    if (-not [string]::IsNullOrWhiteSpace($workMap.host_mount)) {
        if (-not $DryRun -and -not (Test-Path -LiteralPath $workMap.host_mount)) {
            New-Item -ItemType Directory -Path $workMap.host_mount -Force | Out-Null
        }
        $dockerMounts += @('-v', "$($workMap.host_mount):/kite-work")
        $mountStringParts += "-v `"$($workMap.host_mount):/kite-work`""
    }
    if (-not [string]::IsNullOrWhiteSpace($outMap.host_mount)) {
        if (-not $DryRun -and -not (Test-Path -LiteralPath $outMap.host_mount)) {
            New-Item -ItemType Directory -Path $outMap.host_mount -Force | Out-Null
        }
        $dockerMounts += @('-v', "$($outMap.host_mount):/kite-out")
        $mountStringParts += "-v `"$($outMap.host_mount):/kite-out`""
    }

    $innerCmd = "pacman-key --init && pacman-key --populate archlinux && pacman -Syu --noconfirm archiso git curl rsync && ./scripts/build-iso.sh --work-dir '$WorkDirPosix' --out-dir '$OutDirPosix'$skipFlag"
    $commandArgs = @('run', '--rm', '--privileged') + $dockerMounts + @(
        '-w', '/workspace',
        $DockerImage,
        'bash', '-lc', $innerCmd
    )
    $commandString = "docker run --rm --privileged " + ($mountStringParts -join ' ') + " -w /workspace $DockerImage bash -lc `"$innerCmd`""
}
else {
    $wslRepoRoot = ConvertTo-WslPath -WinPath $RepoRoot
    $innerCmd = "cd '$wslRepoRoot' && ./scripts/build-iso.sh --work-dir '$WorkDirPosix' --out-dir '$OutDirPosix'$skipFlag"
    $commandArgs = @(
        '-d', $targetDistro,
        '-u', 'root',
        '--', 'bash', '-lc', $innerCmd
    )
    $commandString = "wsl.exe -d $targetDistro -u root -- bash -lc `"$innerCmd`""
}

$targetIso = "$OutDirPosix/kite-os-folio9480-x86_64_v3.iso"
$targetSha = "$targetIso.sha256"

if ($DryRun) {
    $plan = [ordered]@{
        dry_run           = $true
        requested_mode    = $Mode
        backend           = $resolvedBackend
        backend_available = $backendAvailable
        wsl_distro        = $targetDistro
        docker_image      = $DockerImage
        target_iso        = $targetIso
        target_sha256     = $targetSha
        command_args      = $commandArgs
        command           = $commandString
    }
    if ($Json) {
        $plan | ConvertTo-Json -Depth 5
    }
    else {
        Write-Host "[dry-run] Requested Mode   : $Mode"
        Write-Host "[dry-run] Resolved Backend : $resolvedBackend (available=$backendAvailable)"
        Write-Host "[dry-run] Target ISO       : $targetIso"
        Write-Host "[dry-run] Target SHA-256   : $targetSha"
        Write-Host "[dry-run] Command          : $commandString"
    }
    exit 0
}

if (-not $backendAvailable) {
    $msgLines = @(
        "Error: Cannot execute live ISO build (requested Mode='$Mode', resolved Backend='$resolvedBackend').",
        "Diagnostics on this Windows host:",
        "  1. Docker Desktop: 'docker' CLI absent or Linux container daemon not running (requires Linux containers + --privileged for mkarchiso loop mounts).",
        "  2. WSL2: 'wsl.exe -l -q' reported no matching distribution (requested='$targetDistro', found=$($distros.Count)). Install via 'wsl --install -d Ubuntu' or ArchWSL.",
        "  3. Alternative: Push to GitHub to run '.github/workflows/build-iso.yml' in a privileged archlinux:latest container."
    )
    [Console]::Error.WriteLine(($msgLines -join [Environment]::NewLine))
    exit 1
}

if ($resolvedBackend -eq 'Docker') {
    & docker @commandArgs
    exit $LASTEXITCODE
}
else {
    & wsl.exe @commandArgs
    exit $LASTEXITCODE
}
