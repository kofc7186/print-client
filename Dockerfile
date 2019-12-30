FROM mcr.microsoft.com/windows/servercore:ltsc2019

WORKDIR C:/temp/

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
RUN powershell.exec -Command \
    Write-Host 'Downloading Google Cloud SDK...' ; \
    $Url = 'https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-274.0.0-windows-x86_64.zip' ; \
    $Dest = $env:TEMP ; \
    $ZipFile = $Dest + '\' + $(Split-Path -Path $Url -Leaf) ; \
    (New-Object net.webclient).Downloadfile($Url, $ZipFile) ; \
    Write-Host 'Extracting Google Cloud SDK...' ; \
    $ExtractShell = New-Object -ComObject Shell.Application ; \
    $Files = $ExtractShell.Namespace($ZipFile).Items() ; \
    $ExtractShell.NameSpace($Dest).CopyHere($Files) ; \
    Write-Host 'Installing Google Cloud SDK...' ; \
    Start-Process $Dest + '\google-cloud-sdk\install.bat' -ArgumentList '--quiet' -NoNewWindow -Wait ; \
    Start-Process $Dest + '\google-cloud-sdk\bin\gcloud' -ArgumentList 'components', 'update' -NoNewWindow -Wait ;

# copy program into container
COPY main.py requirements.txt c:/temp/

# pip install -r requirements
RUN pip install -r requirements.txt

# start main.py on launch
ENTRYPOINT [ "python", "main.py" ]
