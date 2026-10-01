#!/bin/zsh
# Registra um robô por site no launchd do Mac (ADR-009), equivalente a
# ops/windows/registrar-robos.ps1. LaunchAgent (sessão do usuário logado): o PJe
# precisa de janela visível e o token USB está nessa sessão.
#
#   ops/launchd/registrar-robos.sh            # registra robôs + agente anti-suspensão
#   ops/launchd/registrar-robos.sh --so-acordado   # só o agente anti-suspensão
#   ops/launchd/registrar-robos.sh --remover  # remove todos
#
# Antes de registrar, remova os robôs do Windows (evita rodadas e e-mails em dobro)
# e valide cada site manualmente (docs/runbooks/MIGRACAO_MAC.md).
set -euo pipefail

PROJETO="${0:A:h:h:h}"
# LCF_TESTE=<pasta>: só gera e valida os .plist nessa pasta, sem carregar no launchd.
AGENTES="${LCF_TESTE:-$HOME/Library/LaunchAgents}"
PREFIXO="com.lcf.legal-monitor"
EXE="$PROJETO/.venv/bin/legal-monitor"
LOGS="$PROJETO/logs"
DOMINIO="gui/$(id -u)"

# Pedido do operador (30/09/2026): todos os robôs na mesma hora, sem escalonar.
# Cada site tem a sua trava (monitor-run), então rodar junto não duplica rodadas.
# eproc: sessão longa (~10 h). De hora em hora, no minuto 0, sem abrir janela de login.
typeset -A DE_HORA_EM_HORA=(
  eproc-tjrj-1g 0
  eproc-tjrj-2g 0
  eproc-jfrj-1g 0
  eproc-trf2 0
  eproc-trf4-2g 0
)
# PJe: sessão curta (~15 min). Portal do TJRJ: sessão só na aba (login a cada rodada).
# Janelas fixas com login interativo (certificado/PIN pela pessoa, salvo seleção automática).
typeset -A JANELAS_DE_LOGIN=(
  pje-tjrj-1g "06:00 18:00"
  pje-tjrj-2g "06:00 18:00"
  pje-trt1-1g "06:00 18:00"
  tjrj-portal "06:00 18:00"
)

descarregar() {
  [[ -n "${LCF_TESTE:-}" ]] || launchctl bootout "$DOMINIO/$1" 2>/dev/null || true
  rm -f "$AGENTES/$1.plist"
}

carregar() {
  plutil -lint -s "$AGENTES/$1.plist"
  [[ -n "${LCF_TESTE:-}" ]] || launchctl bootstrap "$DOMINIO" "$AGENTES/$1.plist"
  echo "Registrado: $1"
}

# $1 rótulo, $2 argumentos (uma string), $3 bloco StartCalendarInterval, $4 log
escrever_robo() {
  local argumentos=""
  for a in ${(z)2}; do argumentos+="    <string>$a</string>"$'\n'; done
  cat > "$AGENTES/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$1</string>
  <key>ProgramArguments</key>
  <array>
    <string>$EXE</string>
$argumentos  </array>
  <key>WorkingDirectory</key>
  <string>$PROJETO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key>
    <string>pt_BR.UTF-8</string>
    <key>PYTHONIOENCODING</key>
    <string>utf-8</string>
  </dict>
  <key>StartCalendarInterval</key>
$3
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>$4</string>
  <key>StandardErrorPath</key>
  <string>$4</string>
</dict>
</plist>
PLIST
}

registrar_acordado() {
  # Mantém o Mac sem suspender enquanto o usuário estiver logado (sem sudo).
  local rotulo="$PREFIXO.caffeinate"
  descarregar "$rotulo"
  cat > "$AGENTES/$rotulo.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$rotulo</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>-s</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
PLIST
  carregar "$rotulo"
}

mkdir -p "$AGENTES" "$LOGS"

if [[ "${1:-}" == "--remover" ]]; then
  for f in "$AGENTES/$PREFIXO".*.plist(N); do descarregar "${f:t:r}"; done
  echo "Robôs removidos."
  exit 0
fi

registrar_acordado
[[ "${1:-}" == "--so-acordado" ]] && exit 0

[[ -x "$EXE" ]] || { echo "legal-monitor não encontrado em $EXE" >&2; exit 1; }

for site minuto in ${(kv)DE_HORA_EM_HORA}; do
  rotulo="$PREFIXO.robo.$site"
  descarregar "$rotulo"
  escrever_robo "$rotulo" "monitor-run --site $site --no-interactive-login" \
    "  <dict><key>Minute</key><integer>$minuto</integer></dict>" "$LOGS/robo-$site.log"
  carregar "$rotulo"
done

for site horarios in ${(kv)JANELAS_DE_LOGIN}; do
  rotulo="$PREFIXO.robo.$site"
  bloco="  <array>"$'\n'
  for h in ${(z)horarios}; do
    bloco+="    <dict><key>Hour</key><integer>$((10#${h%%:*}))</integer><key>Minute</key><integer>$((10#${h##*:}))</integer></dict>"$'\n'
  done
  bloco+="  </array>"
  descarregar "$rotulo"
  escrever_robo "$rotulo" "monitor-run --site $site" "$bloco" "$LOGS/robo-$site.log"
  carregar "$rotulo"
done

echo "Pronto. Conferir: launchctl list | grep $PREFIXO"
