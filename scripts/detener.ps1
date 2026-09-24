# Baja el agente y el tunel.
#
#   .\scripts\detener.ps1

$puerto = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($puerto) {
    $puerto | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force
        Write-Output "Servidor detenido (PID $($_.OwningProcess))"
    }
} else {
    Write-Output "No habia servidor en el puerto 8000."
}

$tunel = Get-Process ngrok -ErrorAction SilentlyContinue
if ($tunel) {
    $tunel | ForEach-Object {
        Stop-Process -Id $_.Id -Force
        Write-Output "Tunel detenido (PID $($_.Id))"
    }
} else {
    Write-Output "No habia tunel corriendo."
}
