<#
.SYNOPSIS
  KabloCast Guvenli Apple USB Surucu Asistani (UpperFilter ASLA eklenmez).
.DESCRIPTION
  Secilen USB\VID_05AC&PID_12xx\<serial> aygiti icin mevcut surucu durumunu JSON olarak yedekler.
  - 'bind'       : Cihaz dugumune WinUSB / libusb-win32 surucusunu baglar (QuickTime USB icin).
  - 'restore'    : Apple resmi composite surucusune (usbccgp) guvenle geri doner.
  - 'removefilter': Eski araclardan kalmis tehlikeli libusb0 UpperFilters kaydini temizler.
#>
param(
    [Parameter(Mandatory)][ValidateSet("bind", "restore", "removefilter")][string]$Action,
    [Parameter(Mandatory)][string]$InstanceId,
    [Parameter(Mandatory)][string]$ResultPath
)
$ErrorActionPreference = "Stop"

$result = [ordered]@{
    action = $Action
    instance = $InstanceId
    ok = $false
    message = ""
    backup = $null
    rolledBack = $false
}

function Save-Result {
    $dir = Split-Path -Parent $ResultPath
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    ($result | ConvertTo-Json -Depth 5) | Set-Content -Path $ResultPath -Encoding UTF8
}

function Clear-UnsafeUpperFilters([string]$InstId) {
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Enum\$InstId"
    if (Test-Path $regPath) {
        $prop = Get-ItemProperty -Path $regPath -Name "UpperFilters" -ErrorAction SilentlyContinue
        if ($prop -and ($prop.UpperFilters -contains "libusb0")) {
            $filtered = @($prop.UpperFilters | Where-Object { $_ -ne "libusb0" })
            if ($filtered.Count -eq 0) {
                Remove-ItemProperty -Path $regPath -Name "UpperFilters" -ErrorAction SilentlyContinue
            } else {
                Set-ItemProperty -Path $regPath -Name "UpperFilters" -Value $filtered
            }
        }
    }
}

function Find-DriverInfByService([string[]]$TargetServices) {
    $infs = Get-ChildItem -Path "$env:WINDIR\INF\oem*.inf" -ErrorAction SilentlyContinue
    foreach ($inf in $infs) {
        $txt = Get-Content -Path $inf.FullName -Raw -ErrorAction SilentlyContinue
        if (-not $txt) { continue }
        foreach ($svc in $TargetServices) {
            if ($txt -match "(?i)AddService\s*=\s*$svc\b" -or $txt -match "(?i)VID_05AC") {
                if ($svc -eq "usbccgp" -and $txt -match "(?i)VID_05AC" -and $txt -match "(?i)usbccgp") {
                    return $inf.FullName
                }
                if ($svc -ne "usbccgp" -and $txt -match "(?i)$svc") {
                    return $inf.FullName
                }
            }
        }
    }
    return $null
}

try {
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Bu islem icin Yonetici (UAC) yetkisi gereklidir."
    }
    if ($InstanceId -notmatch '^USB\\VID_05AC&PID_[0-9A-Fa-f]{4}\\[^\\&]+$') {
        throw "Gecersiz Apple USB aygit kimligi: $InstanceId"
    }

    $regKey = "HKLM:\SYSTEM\CurrentControlSet\Enum\$InstanceId"
    if (-not (Test-Path $regKey)) {
        throw "Cihaz Windows kayit defterinde bulunamadi. Kabloyu takip tekrar deneyin."
    }

    $backupDir = Split-Path -Parent $ResultPath
    if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Force -Path $backupDir | Out-Null }
    $currentSvc = (Get-ItemProperty -Path $regKey -Name "Service" -ErrorAction SilentlyContinue).Service
    $backupFile = Join-Path $backupDir ("backup_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
    ([ordered]@{ instanceId = $InstanceId; service = $currentSvc; timestamp = (Get-Date).ToString("o") } |
        ConvertTo-Json) | Set-Content -Path $backupFile -Encoding UTF8
    $result.backup = $backupFile

    Clear-UnsafeUpperFilters -InstId $InstanceId

    if ($Action -eq "removefilter") {
        pnputil /restart-device "$InstanceId" | Out-Null
        $result.ok = $true
        $result.message = "Guvenli temizlik tamamlandi; tehlikeli libusb0 filtresi kaldirildi."
    }
    elseif ($Action -eq "restore") {
        $appleInf = Find-DriverInfByService -TargetServices @("usbccgp")
        if ($appleInf) {
            pnputil /add-driver "$appleInf" /install | Out-Null
        }
        pnputil /restart-device "$InstanceId" | Out-Null
        $result.ok = $true
        $result.message = "Apple resmi surucusu geri yuklendi. Kabloyu cikarip tekrar takin."
    }
    elseif ($Action -eq "bind") {
        $libInf = Find-DriverInfByService -TargetServices @("libusb0", "WinUSB")
        if (-not $libInf) {
            throw "Sistem surucu deposunda WinUSB/libusb0 paketi bulunamadi. Zadig ile sadece 'WinUSB' secerek baglayabilir veya kablosuz AirPlay 2 modunu kullanabilirsiniz."
        }
        pnputil /add-driver "$libInf" /install | Out-Null
        pnputil /restart-device "$InstanceId" | Out-Null
        $result.ok = $true
        $result.message = "QuickTime USB surucusu baglandi. Kabloyu cikarip takarak baslatin."
    }
} catch {
    $result.message = $_.Exception.Message
} finally {
    Save-Result
}
