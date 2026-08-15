@echo off
setlocal
title CoerIA

set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:7860"
set "COERIA_AUTH_MODE=disabled"

if not exist "%PROJECT_DIR%app.py" (
    echo ERRO: Nao foi encontrado o ficheiro "%PROJECT_DIR%app.py".
    echo Confirme que este ficheiro BAT esta na pasta principal do projeto.
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo ERRO: O ambiente virtual da aplicacao nao foi encontrado.
    echo Caminho esperado: "%PYTHON_EXE%"
    echo.
    echo Crie o ambiente virtual e instale as dependencias antes de continuar.
    pause
    exit /b 1
)

rem Le diretamente as variaveis de utilizador para funcionar mesmo que o
rem Explorador do Windows ainda nao tenha atualizado o seu ambiente.
for /f "usebackq delims=" %%K in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User')"`) do set "OPENAI_API_KEY=%%K"
for /f "usebackq delims=" %%K in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('IAEDU_API_KEY','User')"`) do set "IAEDU_API_KEY=%%K"

if not defined OPENAI_API_KEY (
    if not defined IAEDU_API_KEY (
        echo ERRO: nao esta configurada nenhuma chave de fornecedor de IA.
        echo Configure OPENAI_API_KEY ou IAEDU_API_KEY no PowerShell e volte a executar.
        pause
        exit /b 1
    )
)

pushd "%PROJECT_DIR%"

echo A iniciar a aplicacao CoerIA...
echo O navegador sera aberto em %APP_URL% quando a aplicacao estiver disponivel.
echo.
echo IMPORTANTE: fechar o navegador nao termina a aplicacao.
echo Para terminar, volte a esta consola e prima Ctrl+C,
echo ou feche esta janela.
echo.

if not defined COERIA_SKIP_BROWSER (
    if not defined AGIR_SKIP_BROWSER (
        start "" /b powershell.exe -NoProfile -Command "$url='%APP_URL%'; for ($i=0; $i -lt 60; $i++) { try { $response=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1; if ($response.StatusCode -eq 200) { Start-Process $url; exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }"
    )
)

"%PYTHON_EXE%" app.py
set "EXIT_CODE=%ERRORLEVEL%"

popd

echo.
if "%EXIT_CODE%"=="0" (
    echo A aplicacao foi terminada.
) else (
    echo A aplicacao terminou com o codigo de erro %EXIT_CODE%.
)
echo Prima uma tecla para fechar esta janela.
pause >nul

exit /b %EXIT_CODE%
