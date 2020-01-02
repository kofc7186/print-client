@ECHO OFF
TITLE Knights of Columbus 7186 Print Client
REM Check for GCP_PROJECT environment variable
IF "%GCP_PROJECT%"=="" ECHO GCP_PROJECT environment variable not set! && exit /b 1
REM Fail if creds.json does not exist in CWD
IF NOT EXIST "creds.json" ECHO creds.json must exist in %CWD% and have the service account credentials to connect to the GCP account! && exit /b 1
REM test for docker in path
REM ensure print spooler is not running on host (needs to run within container)
powershell -cmd Stop-Service spooler
powershell -cmd Set-Service spooler -StartupType Disabled
REM docker pull latest image
docker pull kofc7186/print-client:latest
REM stop image if running
docker stop print-client-container || @echo on
docker rm print-client-container || @echo on
REM run image, passing in cmd line args from this script
docker run --name=print-client-container ^                %= name the container so we can refer to it later =%
--isolation=process ^                                     %= use process isolation =%
-v .:C:\data\ ^                                           %= map CWD into container so we can pass GCP creds =%
--restart on-failure ^                                    %= restart the container in the case where python crashes =%
-e GCP_PROJECT='%GCP_PROJECT%' ^                          %= pass in the GCP project =%
-e GOOGLE_APPLICATION_CREDENTIALS='C:/data/creds.json' ^  %= pass in the GCP creds =%
kofc7186/print-client:latest %*                           %= always run the latest container =%