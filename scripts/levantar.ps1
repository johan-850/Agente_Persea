# Levanta el agente en segundo plano, suelto de esta consola.
#
# Hasta ahora el servidor se arrancaba desde la sesion de trabajo y moria con
# ella: al probar desde WhatsApp no habia nadie escuchando y los mensajes se
# perdian. Start-Process crea procesos independientes que siguen vivos al
# cerrar la terminal.
#
# Esto NO es un despliegue: si se reinicia el computador o se cae la conexion,
# hay que volver a correrlo. Sirve para probar y para operar un dia suelto.
#
#   .\scripts\levantar.ps1
#   .\scripts\detener.ps1

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $raiz "logs"
$ngrok = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
$dominio = "https://food-imperfect-cosmos.ngrok-free.dev"

if (-not (Test-Path $logs)) { New-Item -ItemType Directory -Path $logs | Out-Null }

# Si ya hay algo escuchando en el 8000, se deja como esta: levantar dos
# servidores sobre el mismo puerto deja uno que falla en silencio.
$ocupado = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($ocupado) {
    Write-Output "Ya hay un servidor en el puerto 8000 (PID $($ocupado[0].OwningProcess)). No se toca."
} else {
    Start-Process -FilePath (Join-Path $raiz ".venv\Scripts\python.exe") `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $raiz `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "servidor.log") `
        -RedirectStandardError (Join-Path $logs "servidor.err.log")
    Write-Output "Servidor levantado -> logs\servidor.log"
}

if (Get-Process ngrok -ErrorAction SilentlyContinue) {
    Write-Output "ngrok ya estaba corriendo. No se toca."
} else {
    Start-Process -FilePath $ngrok `
        -ArgumentList "http", "8000", "--url=$dominio", "--log", "stdout", "--log-format", "logfmt" `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "ngrok.log") `
        -RedirectStandardError (Join-Path $logs "ngrok.err.log")
    Write-Output "Tunel levantado  -> logs\ngrok.log"
}

Start-Sleep -Seconds 5

Write-Output ""
try {
    $salud = Invoke-RestMethod -Uri "http://127.0.0.1:8000/" -TimeoutSec 15
    Write-Output "servidor local: $($salud.status)"
} catch {
    Write-Output "servidor local: NO RESPONDE. Mira logs\servidor.err.log"
}

try {
    $r = [System.Net.WebRequest]::Create($dominio)
    $r.Timeout = 20000
    $r.GetResponse().Close()
    Write-Output "tunel publico: ok  ($dominio)"
} catch {
    Write-Output "tunel publico: NO RESPONDE. Mira logs\ngrok.err.log"
}
