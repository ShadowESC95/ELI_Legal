# Install ELI Legal from this source tree, for the current user, on Windows.
# It needs Python 3.10 or newer. Use this when you do not have the packaged setup program.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1              install or upgrade
#   powershell -ExecutionPolicy Bypass -File install.ps1 -NoModels    leave out llama.cpp, which runs GGUF model files in process
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall   remove the program; data is kept
param([string]$Prefix = "$env:LOCALAPPDATA\Programs\ELI Legal (source)", [switch]$NoGui, [switch]$NoModels, [switch]$Uninstall)
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
& $VenvPy -m pip install --quiet "$Root[$Extras,packs]"
if ($LASTEXITCODE -ne 0) { throw "installation failed" }

# llama.cpp runs GGUF model files in process. At the version the graphics packs are built at:
# two versions' libraries cannot share a process. It is compiled on this machine when there is
# no ready-made build for it, and the program is complete without it (a model server works).
if (-not $NoModels) {
    $Llama = "llama-cpp-python==" + (& $VenvPy (Join-Path $Root "scripts\fetch_gpu_pack.py") --version)
    $BuildLog = Join-Path $Prefix "llama-build.log"
    Write-Host "Adding llama.cpp to run GGUF model files (compiled here when there is no ready-made build; that takes some minutes) ..."
    & $VenvPy -m pip install --quiet --log $BuildLog $Llama
    if ($LASTEXITCODE -eq 0) {
        if (Test-Path $BuildLog) { Remove-Item -Force $BuildLog }
    } else {
        Write-Host ""
        Write-Host "llama.cpp could not be built here, so GGUF model files will not run in process yet."
        Write-Host "  It needs the C++ build tools:  https://visualstudio.microsoft.com/visual-cpp-build-tools/  (Desktop development with C++)"
        Write-Host "  Then:                          `"$VenvPy`" -m pip install `"$Llama`""
        Write-Host "  What the build said:           $BuildLog"
        Write-Host "  Without it: a graphics pack (eli-legal gpu install FILE) is a complete llama.cpp and"
        Write-Host "  needs no compiler, and a model server on this machine works as it is."
        Write-Host ""
    }
}

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
