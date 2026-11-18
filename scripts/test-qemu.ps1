[CmdletBinding()]
param(
    [ValidateSet('4G', '8G', '16G')]
    [string]$Ram = '8G',
    [ValidateSet(0, 1)]
    [int]$Rotational = 0,
    [string]$IsoPath = '',
    [string]$DiskPath = '',
    [string]$Disk = '',
    [string]$OvmfCode = '',
    [string]$OvmfVars = '',
    [ValidateSet('auto', 'kvm', 'whpx', 'tcg')]
    [string]$Accel = 'auto',
    [switch]$Headless,
    [switch]$DryRun,
    [switch]$Json,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    @(
        'Usage: test-qemu.ps1 [OPTIONS]',
        '',
        'Boot or dry-run the HP EliteBook Folio 9480m QEMU Haswell test profile.',
        '',
        'Options:',
        '  -Ram <4G|8G|16G>          RAM tier to emulate (default: 8G)',
        '  -Rotational <0|1>         Storage type: 0 = SSD/mSATA, 1 = HDD (default: 0)',
        '  -Disk <ssd|hdd|path>      Storage preset (ssd or hdd) or qcow2 disk path',
        '  -DiskPath <path>          Path to qcow2 test disk (default: work\qemu\kite-os-test.qcow2)',
        '  -IsoPath <path>           Path to KITE_OS ISO (default: out\kite-os-folio9480-x86_64_v3.iso)',
        '  -OvmfCode <path>          Path to OVMF_CODE firmware fd',
        '  -OvmfVars <path>          Path to OVMF_VARS template fd',
        '  -Accel <auto|kvm|whpx|tcg> QEMU accelerator (default: auto)',
        '  -Headless                 Run with -display none -serial mon:stdio',
        '  -DryRun                   Print QEMU command without launching',
        '  -Json                     Emit JSON payload (with -DryRun)',
        '  -Help                     Show this help message'
    ) | ForEach-Object { Write-Host $_ }
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if (-not [string]::IsNullOrWhiteSpace($Disk)) {
    $diskLower = $Disk.Trim().ToLowerInvariant()
    if ($diskLower -eq 'ssd') {
        $Rotational = 0
    }
    elseif ($diskLower -eq 'hdd') {
        $Rotational = 1
    }
    elseif ([string]::IsNullOrWhiteSpace($DiskPath)) {
        $DiskPath = $Disk
    }
}

if ([string]::IsNullOrWhiteSpace($IsoPath)) {
    $IsoPath = Join-Path $RepoRoot 'out\kite-os-folio9480-x86_64_v3.iso'
}
if ([string]::IsNullOrWhiteSpace($DiskPath)) {
    $DiskPath = Join-Path $RepoRoot 'work\qemu\kite-os-test.qcow2'
}

function Resolve-OvmfPath {
    param(
        [string]$Explicit,
        [string[]]$Candidates,
        [string]$Fallback
    )
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        return $Explicit
    }
    foreach ($cand in $Candidates) {
        if (Test-Path -LiteralPath $cand) {
            return $cand
        }
    }
    return $Fallback
}

$resolvedOvmfCode = Resolve-OvmfPath -Explicit $OvmfCode -Candidates @(
    'C:\Program Files\qemu\share\edk2-x86_64-code.fd',
    'C:\Program Files\qemu\share\OVMF_CODE.fd',
    'C:\msys64\ucrt64\share\qemu\edk2-x86_64-code.fd'
) -Fallback 'C:\Program Files\qemu\share\edk2-x86_64-code.fd'

$resolvedOvmfVars = Resolve-OvmfPath -Explicit $OvmfVars -Candidates @(
    'C:\Program Files\qemu\share\edk2-i386-vars.fd',
    'C:\Program Files\qemu\share\OVMF_VARS.fd',
    'C:\msys64\ucrt64\share\qemu\edk2-i386-vars.fd'
) -Fallback 'C:\Program Files\qemu\share\edk2-i386-vars.fd'

$resolvedAccel = $Accel
if ($resolvedAccel -eq 'auto') {
    $whpxEnabled = $false
    try {
        $cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
        if ($cs.HypervisorPresent) {
            $feat = Get-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -ErrorAction SilentlyContinue
            if ($null -ne $feat -and $feat.State -eq 'Enabled') {
                $whpxEnabled = $true
            }
        }
    }
    catch {
        $whpxEnabled = $false
    }
    if ($whpxEnabled) {
        $resolvedAccel = 'whpx'
    }
    else {
        $resolvedAccel = 'tcg'
    }
}

$qemuWorkDir = Split-Path -Parent $DiskPath
if ([string]::IsNullOrWhiteSpace($qemuWorkDir)) {
    $qemuWorkDir = '.'
}
$writableVars = Join-Path $qemuWorkDir 'OVMF_VARS.fd'

if ($Rotational -eq 0) {
    $rotationRate = 1
}
else {
    $rotationRate = 5400
}

$qemuBin = 'qemu-system-x86_64'
$qemuCmdObj = Get-Command qemu-system-x86_64 -ErrorAction SilentlyContinue
if ($null -ne $qemuCmdObj) {
    $qemuBin = $qemuCmdObj.Source
}
elseif (Test-Path -LiteralPath 'C:\Program Files\qemu\qemu-system-x86_64.exe') {
    $qemuBin = 'C:\Program Files\qemu\qemu-system-x86_64.exe'
}

$argv = @(
    '-name', "KITE_OS-Folio9480m-$Ram",
    '-machine', 'q35',
    '-accel', $resolvedAccel,
    '-cpu', 'Haswell-noTSX',
    '-smp', '4,cores=2,threads=2',
    '-m', $Ram,
    '-drive', "if=pflash,format=raw,readonly=on,file=$resolvedOvmfCode",
    '-drive', "if=pflash,format=raw,file=$writableVars",
    '-device', 'virtio-scsi-pci,id=scsi0',
    '-drive', "id=hd0,if=none,format=qcow2,file=$DiskPath",
    '-device', "scsi-hd,drive=hd0,bus=scsi0.0,rotation_rate=$rotationRate",
    '-drive', "id=cd0,if=none,media=cdrom,readonly=on,file=$IsoPath",
    '-device', 'scsi-cd,drive=cd0,bus=scsi0.0,bootindex=1',
    '-netdev', 'user,id=net0',
    '-device', 'e1000e,netdev=net0',
    '-device', 'intel-hda',
    '-device', 'hda-duplex'
)

if ($Headless) {
    $argv += @('-display', 'none', '-serial', 'mon:stdio')
}
else {
    $argv += @('-vga', 'std')
}

$quotedParts = @()
foreach ($a in $argv) {
    if ($a -match '\s') {
        $quotedParts += "`"$a`""
    }
    else {
        $quotedParts += $a
    }
}
$commandLine = "$qemuBin " + ($quotedParts -join ' ')

if ($DryRun) {
    $payload = [ordered]@{
        dry_run       = $true
        binary        = $qemuBin
        ram           = $Ram
        rotational    = $Rotational
        rotation_rate = $rotationRate
        accel         = $resolvedAccel
        headless      = [bool]$Headless
        iso           = $IsoPath
        disk          = $DiskPath
        ovmf_code     = $resolvedOvmfCode
        ovmf_vars     = $writableVars
        argv          = $argv
        command       = $commandLine
    }
    if ($Json) {
        $payload | ConvertTo-Json -Depth 5
    }
    else {
        Write-Host "[dry-run] Binary        : $qemuBin"
        Write-Host "[dry-run] Folio Profile : -cpu Haswell-noTSX, -smp 4,cores=2,threads=2, -m $Ram, rotational=$Rotational (rotation_rate=$rotationRate), accel=$resolvedAccel"
        Write-Host "[dry-run] Command       : $commandLine"
    }
    exit 0
}

if ($null -eq $qemuCmdObj -and -not (Test-Path -LiteralPath $qemuBin)) {
    [Console]::Error.WriteLine("Error: 'qemu-system-x86_64' is not installed or not in PATH. Install QEMU for Windows (e.g. winget install SoftwareFreedomConservancy.QEMU).")
    exit 1
}

if (-not (Test-Path -LiteralPath $IsoPath)) {
    [Console]::Error.WriteLine("Error: ISO not found at '$IsoPath'. Build it first with .\scripts\build-iso.ps1.")
    exit 1
}

if (-not (Test-Path -LiteralPath $resolvedOvmfCode)) {
    [Console]::Error.WriteLine("Error: OVMF code firmware not found at '$resolvedOvmfCode'.")
    exit 1
}

if (-not (Test-Path -LiteralPath $qemuWorkDir)) {
    New-Item -ItemType Directory -Path $qemuWorkDir -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $writableVars)) {
    if (-not (Test-Path -LiteralPath $resolvedOvmfVars)) {
        [Console]::Error.WriteLine("Error: OVMF vars template not found at '$resolvedOvmfVars'.")
        exit 1
    }
    Copy-Item -LiteralPath $resolvedOvmfVars -Destination $writableVars -Force
}

if (-not (Test-Path -LiteralPath $DiskPath)) {
    $qemuImg = 'qemu-img'
    if (Test-Path -LiteralPath 'C:\Program Files\qemu\qemu-img.exe') {
        $qemuImg = 'C:\Program Files\qemu\qemu-img.exe'
    }
    & $qemuImg create -f qcow2 $DiskPath 32G
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

& $qemuBin @argv
exit $LASTEXITCODE
