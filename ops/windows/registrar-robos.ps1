<#
Registra um robô por site no Agendador de Tarefas do Windows (ADR-009).

Execute no PowerShell do usuário que fica logado no PC (não precisa de administrador):
    powershell -ExecutionPolicy Bypass -File ops\windows\registrar-robos.ps1
Para remover todos os robôs:
    powershell -ExecutionPolicy Bypass -File ops\windows\registrar-robos.ps1 -Remover

Antes de registrar, valide cada site manualmente (docs/runbooks/ROBOS_POR_SITE.md).
No Mac mini (futuro) o equivalente será o launchd (ops/launchd).
#>
param(
    [string]$Projeto = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [switch]$Remover
)
$ErrorActionPreference = "Stop"
$Pasta = "\LCF Legal Monitor\"

if ($Remover) {
    Get-ScheduledTask -TaskPath $Pasta -ErrorAction SilentlyContinue |
        Unregister-ScheduledTask -Confirm:$false
    Write-Host "Robos removidos."
    return
}

$Exe = Join-Path $Projeto ".venv\Scripts\legal-monitor.exe"
if (-not (Test-Path $Exe)) { throw "legal-monitor.exe nao encontrado em $Exe" }
$Logs = Join-Path $Projeto "logs"
New-Item -ItemType Directory -Force $Logs | Out-Null

# eproc: sessão longa (~10 h). De hora em hora, sem abrir janela de login:
# sessão caída gera UM e-mail "login necessário" e a pessoa roda auth-open.
$DeHoraEmHora = @(
    "eproc-tjrj-1g",
    "eproc-tjrj-2g",
    "eproc-jfrj-1g",
    "eproc-trf2",
    "eproc-trf4-2g"
)
# PJe: sessão curta (~15 min). Janelas fixas com login interativo (PIN digitado remotamente).
$JanelasDeLogin = @{
    "pje-tjrj-1g" = @("06:00", "18:00")
    "pje-trt1-1g" = @("06:20", "18:20")
}

function Registrar-Robo([string]$Site, [string]$Argumentos, $Gatilhos) {
    $Log = Join-Path $Logs "robo-$Site.log"
    $Acao = New-ScheduledTaskAction -Execute "cmd.exe" `
        -Argument "/c `"`"$Exe`" $Argumentos >> `"$Log`" 2>&1`"" `
        -WorkingDirectory $Projeto
    $Config = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    # Interativo: o PJe precisa de janela visível e o token USB está na sessão do usuário.
    $Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "Robo $Site" -TaskPath $Pasta -Action $Acao `
        -Trigger $Gatilhos -Settings $Config -Principal $Principal -Force | Out-Null
    Write-Host "Registrado: Robo $Site  (log: $Log)"
}

$Inicio = (Get-Date).AddMinutes(5)
foreach ($Site in $DeHoraEmHora) {
    $Gatilho = New-ScheduledTaskTrigger -Once -At $Inicio -RepetitionInterval (New-TimeSpan -Hours 1)
    Registrar-Robo $Site "monitor-run --site $Site --no-interactive-login" $Gatilho
    $Inicio = $Inicio.AddMinutes(7)  # escalona para os robôs não rodarem juntos
}
foreach ($Site in $JanelasDeLogin.Keys) {
    $Gatilhos = $JanelasDeLogin[$Site] | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
    Registrar-Robo $Site "monitor-run --site $Site" $Gatilhos
}
Write-Host "Pronto. Veja em: Agendador de Tarefas > Biblioteca > LCF Legal Monitor"
