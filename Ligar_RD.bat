@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Ligar RD - Red News Radio

echo ============================================
echo        RED NEWS RADIO - LIGAR RD
echo ============================================
echo.

set "RadioDir=C:\RadioRedNews"
set "MusicasDir=C:\RadioRedNews\musicas"
set "Lista=C:\RadioRedNews\lista.txt"
set "Config=C:\RadioRedNews\icecast-rednews.xml"
set "CloudLog=C:\RadioRedNews\cloudflared.log"
set "LinkFile=C:\RadioRedNews\link-boombox.txt"
set "Senha=rednews123"
set "Mount=rednews.mp3"
set "Porta=8000"

rem === CONFIGURAR AQUI ===
set "SiteURL=https://rednews-1.onrender.com"
set "SenhaAdmin=suasenha123"
rem =======================

echo [1/10] Fechando processos antigos...
taskkill /IM ffmpeg.exe /F >nul 2>&1
taskkill /IM cloudflared.exe /F >nul 2>&1
taskkill /IM icecast.exe /F >nul 2>&1

echo [2/10] Conferindo pastas...
if not exist "%RadioDir%" mkdir "%RadioDir%"
if not exist "%MusicasDir%" mkdir "%MusicasDir%"

echo [3/10] Limpando logs antigos...
if exist "%CloudLog%" del "%CloudLog%" >nul 2>&1
if exist "%LinkFile%" del "%LinkFile%" >nul 2>&1

echo [4/10] Gerando lista de musicas...
dir /b "%MusicasDir%\*.mp3" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERRO: Nenhuma musica .mp3 encontrada em:
    echo %MusicasDir%
    echo.
    echo Coloque pelo menos uma musica nessa pasta.
    explorer "%MusicasDir%"
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem '%MusicasDir%' -Filter *.mp3 | ForEach-Object { 'file ''' + $_.FullName + '''' } | Set-Content '%Lista%' -Encoding ASCII"
echo OK: lista.txt atualizado.

echo [5/10] Procurando Icecast...
set "IceExe=C:\Program Files\Icecast\bin\icecast.exe"
if not exist "%IceExe%" set "IceExe=C:\Program Files (x86)\Icecast\bin\icecast.exe"

if not exist "%IceExe%" (
    echo.
    echo ERRO: Icecast nao encontrado.
    echo Caminho esperado: C:\Program Files\Icecast\bin\icecast.exe
    pause
    exit /b 1
)

if not exist "%Config%" (
    echo.
    echo ERRO: Config do Icecast nao encontrado: %Config%
    echo Rode primeiro o script que criou o icecast-rednews.xml.
    pause
    exit /b 1
)

echo [6/10] Procurando cloudflared...
set "CloudExe="

where cloudflared.exe >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%A in ('where cloudflared.exe') do (
        if not defined CloudExe set "CloudExe=%%A"
    )
)

if not defined CloudExe (
    if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe" set "CloudExe=%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe"
)
if not defined CloudExe (
    if exist "C:\Users\%USERNAME%\AppData\Local\Microsoft\WinGet\Links\cloudflared.exe" set "CloudExe=C:\Users\%USERNAME%\AppData\Local\Microsoft\WinGet\Links\cloudflared.exe"
)
if not defined CloudExe (
    if exist "C:\Program Files\cloudflared\cloudflared.exe" set "CloudExe=C:\Program Files\cloudflared\cloudflared.exe"
)

if not defined CloudExe (
    echo.
    echo ERRO: cloudflared nao foi encontrado.
    echo Instale com: winget install --id Cloudflare.cloudflared
    pause
    exit /b 1
)

echo OK: cloudflared encontrado.

echo [7/10] Iniciando Icecast...
start "ICECAST - RED NEWS" /D "%RadioDir%" "%IceExe%" -c "%Config%"
timeout /t 4 >nul

echo [8/10] Iniciando transmissao FFmpeg...
start "FFMPEG - RED NEWS RADIO" cmd /k "cd /d "%RadioDir%" && ffmpeg -re -stream_loop -1 -f concat -safe 0 -i lista.txt -vn -c:a libmp3lame -b:a 128k -content_type audio/mpeg -f mp3 icecast://source:%Senha%@localhost:%Porta%/%Mount%"
timeout /t 5 >nul

echo Abrindo radio local...
start http://localhost:%Porta%/%Mount%

echo [9/10] Iniciando Cloudflare Tunnel...
start "CLOUDFLARE - LINK PUBLICO" /MIN cmd /c ""%CloudExe%" tunnel --protocol http2 --edge-ip-version 4 --url http://localhost:%Porta% > "%CloudLog%" 2>&1"

echo.
echo Aguardando link publico do Cloudflare...
echo.

set "TunnelURL="

for /l %%i in (1,1,120) do (
    for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%CloudLog%'; if(Test-Path $p){$t=Get-Content $p -Raw; if($t -match 'https://[a-zA-Z0-9-]+\.trycloudflare\.com'){ $Matches[0] }}"`) do (
        set "TunnelURL=%%L"
    )
    if defined TunnelURL goto LINK_ENCONTRADO
    echo Aguardando link... %%i/120
    timeout /t 1 >nul
)

echo.
echo ERRO: Nao consegui capturar o link do Cloudflare.
if exist "%CloudLog%" notepad "%CloudLog%"
pause
exit /b 1

:LINK_ENCONTRADO
set "FinalLink=%TunnelURL%/%Mount%"

echo.
echo Link encontrado: %TunnelURL%
echo Aguardando tunnel registrar...

for /l %%i in (1,1,60) do (
    findstr /c:"Registered tunnel connection" "%CloudLog%" >nul 2>&1
    if not errorlevel 1 goto TUNNEL_OK
    echo Aguardando conexao... %%i/60
    timeout /t 1 >nul
)

:TUNNEL_OK

echo %FinalLink% > "%LinkFile%"
echo %FinalLink% | clip

echo.
echo [10/10] Atualizando Red News automaticamente...
curl -s -X POST "%SiteURL%/api/stream/publish" ^
     -H "Content-Type: application/json" ^
     -d "{\"password\":\"%SenhaAdmin%\",\"url\":\"%FinalLink%\",\"is_live\":true}" >nul 2>&1

if errorlevel 1 (
    echo AVISO: Nao consegui atualizar o site automaticamente.
    echo Cole o link manualmente no painel admin.
) else (
    echo OK: Site atualizado - radio AO VIVO ativado!
)

echo.
echo ============================================
echo          RD LIGADA COM SUCESSO
echo ============================================
echo.
echo LINK LOCAL:
echo http://localhost:%Porta%/%Mount%
echo.
echo LINK PUBLICO (copiado):
echo %FinalLink%
echo.
echo Site: %SiteURL%
echo.
echo ============================================

start %FinalLink%
pause
