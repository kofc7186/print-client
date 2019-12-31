FROM mcr.microsoft.com/windows/servercore:ltsc2019

WORKDIR C:/temp/

# install ghostscript
RUN powershell -Command \
    Write-Host 'Downloading Ghostscript...' ; \
    $GsInstaller = $env:Temp + '\\gs950w64.exe' ; \
    (New-Object Net.WebClient).DownloadFile('https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs950/gs950w64.exe', $GsInstaller) ; \
    Write-Host 'Installing Ghostscript...' ; \
    Start-Process $GsInstaller -ArgumentList '/S' -NoNewWindow -Wait ; \
    Remove-Item $GsInstaller -Force

# install python 3.7
RUN powershell.exe -Command \
    Write-Host 'Downloading Python...' ; \
    $PyInstaller = $env:Temp + '\\python-3.7.6-amd64.exe' ; \
    (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.7.6/python-3.7.6-amd64.exe', $PyInstaller) ; \
    Write-Host 'Installing Python...' ; \
    Start-Process $PyInstaller -ArgumentList '/quiet TargetDir=C:\Python InstallAllUsers=1 PrependPath=1 Include_test=0 InstallLauncherAllUsers=0' -NoNewWindow -Wait ; \
    Remove-Item $PyInstaller -Force

# install google-cloud-sdk (for debugging only)
RUN powershell.exe -Command \
    Write-Host 'Downloading Google Cloud SDK...' ; \
    $Url = 'https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-274.0.1-windows-x86_64.zip' ; \
    $Dest = $env:TEMP + '\\'; \
    $ZipFile = $Dest + $(Split-Path -Path $Url -Leaf) ; \
    (New-Object net.webclient).DownloadFile($Url, $ZipFile) ; \
    Write-Host 'Extracting Google Cloud SDK...' ; \
    $ProgressPreference = 'SilentlyContinue' ; \
    Expand-Archive -Path $ZipFile -DestinationPath $Dest -Force ; \
    Write-Host 'Installing Google Cloud SDK...' ; \
    $GCPInstall = $Dest + 'google-cloud-sdk\\install.bat' ; \
    Start-Process $GCPInstall -ArgumentList '--quiet' -NoNewWindow -Wait ; \
    Remove-Item $ZipFile -Force

# copy program into container
COPY main.py requirements.txt c:/temp/

# Install python requirements
RUN pip install --no-cache-dir -r requirements.txt

# pip install -r requirements
ENV GCP_PROJECT=print-client-123456
RUN python main.py -p something

# start main.py on launch, allowing cmd line args to be directly passed in on 'docker run' command
ENTRYPOINT [ "python", "main.py" ]
