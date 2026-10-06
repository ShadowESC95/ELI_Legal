# Install ELI Legal from this source tree, for the current user, on Windows.
# It needs Python 3.10 or newer. Use this when you do not have the packaged setup program.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1              install or upgrade
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall   remove the program; data is kept
param([string]$Prefix = "$env:LOCALAPPDATA\Programs\ELI Legal (source)", [switch]$NoGui, [switch]$Uninstall)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Data = "$env:LOCALAPPDATA\ELI Legal"
$Mark = Join-Path $Prefix ".eli-legal-program-folder"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "ELI Legal.lnk"

if ($Uninstall) {
    if (Test-Path $Prefix) {
        if (-not (Test-Path $Mark)) { throw "$Prefix was not created by this installer; not touching it" }
        Remove-Item -Recurse -Force $Prefix
    }
    if (Test-Path $Shortcut) { Remove-Item -Force $Shortcut }
    Write-Host "ELI Legal has been removed. Your data was NOT removed: $Data"
    exit 0
}

$Py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $Py -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is needed. Install it from python.org, or set PYTHON to its path." }
if ((Test-Path $Prefix) -and -not (Test-Path $Mark)) { throw "$Prefix exists and was not created by this installer; choose another -Prefix" }
New-Item -ItemType Directory -Force -Path $Prefix, $Data | Out-Null
New-Item -ItemType File -Force -Path $Mark | Out-Null
Write-Host "Creating a private Python environment in $Prefix ..."
& $Py -m venv (Join-Path $Prefix "venv")
$VenvPy = Join-Path $Prefix "venv\Scripts\python.exe"
& $VenvPy -m pip install --quiet --upgrade pip
$Extras = if ($NoGui) { "server" } else { "all" }
Write-Host "Installing ELI Legal and what it needs ..."
& $VenvPy -m pip install --quiet "$Root[$Extras]"
if ($LASTEXITCODE -ne 0) { throw "installation failed" }

$Cli = Join-Path $Prefix "eli-legal.cmd"
"@echo off`r`nrem ELI Legal launcher (created by install.ps1)`r`nif not defined ELI_LEGAL_HOME set `"ELI_LEGAL_HOME=$Data`"`r`n`"$VenvPy`" -m eli_legal.cli %*" | Out-File -Encoding ascii $Cli
if (-not $NoGui) {
    $Pyw = Join-Path $Prefix "venv\Scripts\pythonw.exe"
    $Gui = Join-Path $Prefix "eli-legal-gui.cmd"
    "@echo off`r`nrem ELI Legal launcher (created by install.ps1)`r`nif not defined ELI_LEGAL_HOME set `"ELI_LEGAL_HOME=$Data`"`r`nstart `"`" `"$Pyw`" -m eli_legal.gui.app %*" | Out-File -Encoding ascii $Gui
    $Link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
    $Link.TargetPath = $Gui
    $Link.WorkingDirectory = $Prefix
    $Link.WindowStyle = 7
    $Link.Save()
}
& $Cli --version
Write-Host ""
Write-Host "Installed in $Prefix. Your data will be kept in: $Data"
Write-Host "  Command line : `"$Cli`" --help"
if (-not $NoGui) { Write-Host "  Desktop      : Start menu, 'ELI Legal'" }
