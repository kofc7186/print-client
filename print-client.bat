@ECHO OFF
TITLE Knights of Columbus 7186 Print Client
:: Check for GCP_PROJECT environment variable
IF "%GCP_PROJECT%"=="" ECHO GCP_PROJECT environment variable not set! && exit /b 1
:: Fail if creds.json does not exist in CWD
IF NOT EXIST "creds.json" ECHO creds.json must exist in %CWD% and have the service account credentials to connect to the GCP account! && exit /b 1
:: test for docker in path
:: docker pull latest image
docker pull kofc7186/print-client:latest
:: stop image if running
docker stop print-client
docker rm print-client
:: run image, passing in cmd line args from this script
docker run --name=print-client -v .:C:/data/ --restart on-failure -e GCP_PROJECT=%GCP_PROJECT% -d kofc7186/print-client %*