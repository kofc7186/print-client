@ECHO OFF
TITLE Knights of Columbus 7186 Print Client
REM Check for GCP_PROJECT environment variable
IF "%GCP_PROJECT%"=="" ECHO GCP_PROJECT environment variable not set! && exit /b 1
REM Check for GOOGLE_APPLICATION_CREDENTIALS environment variable
IF ("%GOOGLE_APPLICATION_CREDENTIALS%" NEQ "") (SET cred="-e GOOGLE_APPLICATION_CREDENTIALS=%GOOGLE_APPLICATION_CREDENTIALS%") ELSE (set cred="")
REM Fail if creds.json does not exist in CWD
IF NOT EXIST "creds.json" ECHO creds.json must exist in %CD% and have the service account credentials to connect to the GCP account! && exit /b 1
REM docker pull latest image
docker pull kofc7186/print-client:latest
REM stop image if running
cmd /C docker stop print-client-container
cmd /C docker rm print-client-container
REM run image, passing in cmd line args from this script
docker run --name=print-client-container -v %CD%\:C:\data\ --restart on-failure -e GCP_PROJECT=%GCP_PROJECT% %cred% kofc7186/print-client:latest %*