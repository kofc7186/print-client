FROM mcr.microsoft.com/windows/servercore:ltsc2019

# WORKDIR $env:TEMP

# install ghostscript
RUN powershell -Command \
    Write-Host 'Downloading Ghostscript...' ; \
    $GsInstaller = $env:Temp + '\gs950w64.exe' ; \
    (New-Object Net.WebClient).DownloadFile('https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs950/gs950w64.exe', $GsInstaller) ; \
    Write-Host 'Installing Ghostscript...' ; \
    Start-Process $GsInstaller -ArgumentList '/S' -NoNewWindow -Wait ; \
    Remove-Item $GsInstaller -Force

# install python 3.7
RUN powershell.exe -Command \
    Write-Host 'Downloading Python...' ; \
    $PyInstaller = $env:Temp + '\python-3.7.6-amd64.exe' ; \
    (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.7.6/python-3.7.6-amd64.exe', $PyInstaller) ; \
    Write-Host 'Installing Python...' ; \
    Start-Process $PyInstaller -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0', 'InstallLauncherAllUsers=0' -NoNewWindow -Wait ; \
    Remove-Item $PyInstaller -Force

# install google-cloud-sdk (for debugging only)
# RUN Write-Host 'Downloading Google Cloud SDK...' ; \
#     $GCPInstaller = $env:Temp + '\gs950w64.exe' ; \
#     (New-Object Net.WebClient).DownloadFile('https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs950/gs950w64.exe', $GCPInstaller) ; \
#     Write-Host 'Installing Google Cloud SDK...' ; \
#     Start-Process $GCPInstaller -ArgumentList '/S' -NoNewWindow -Wait

# git clone latest

# pip install -r requirements

# start main.py on launch
