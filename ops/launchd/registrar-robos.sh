#!/bin/zsh
# Registra um robô por site no launchd do Mac (ADR-009), equivalente a
# ops/windows/registrar-robos.ps1. LaunchAgent (sessão do usuário logado): o PJe
# precisa de janela visível e o token USB está nessa sessão.
#
#   ops/launchd/registrar-robos.sh            # registra robôs + agente anti-suspensão
#   ops/launchd/registrar-robos.sh --so-acordado   # só o agente anti-suspensão
#   ops/launchd/registrar-robos.sh --so-chrome     # só o Chrome do robô + desbloqueio do PIN
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

# eproc: sessão longa (~10 h). De hora em hora, no minuto 0, sem janela (não aparece na tela).
# Cada site tem a sua trava (monitor-run), então rodar junto não duplica rodadas.
typeset -A DE_HORA_EM_HORA=(
  eproc-tjrj-1g 0
  eproc-tjrj-2g 0
  eproc-jfrj-1g 0
  eproc-trf2 0
  eproc-trf4-2g 0
)
# Sites com login (PJe, Portal do TJRJ): UM robô roda todos em sequência, uma janela por
# vez, para o login poder ser feito pelo Parsec do celular (pedido do operador, 30/09/2026:
# com todos juntos as janelas brigavam pela tela). Horários pedidos: 13:00 e 00:00.
JANELA_HORARIOS="13:00 00:00"

descarregar() {
  [[ -n "${LCF_TESTE:-}" ]] || launchctl bootout "$DOMINIO/$1" 2>/dev/null || true
  rm -f "$AGENTES/$1.plist"
}

carregar() {
  plutil -lint -s "$AGENTES/$1.plist"
  if [[ -z "${LCF_TESTE:-}" ]]; then
    # O agente anterior (ex.: Chrome fechando) pode levar alguns segundos para sair.
    local tentativa
    for tentativa in 1 2 3 4 5 6; do
      launchctl bootstrap "$DOMINIO" "$AGENTES/$1.plist" 2>/dev/null && break
      [[ $tentativa == 6 ]] && launchctl bootstrap "$DOMINIO" "$AGENTES/$1.plist"
      sleep 2
    done
  fi
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

# Chrome do robô sempre aberto (ideia A, 30/09/2026): o macOS guarda o PIN do token por
# processo do Chrome. Um único Chrome do robô (perfil próprio, depuração só em 127.0.0.1)
# fica aberto; os robôs se conectam a ele. A pessoa digita o PIN uma vez após ligar o Mac.
# Pop-ups liberados como no Chrome do Playwright: o Portal do TJRJ abre em aba nova e o
# bloqueador parava o login em www.tjrj.jus.br (1º teste, 30/09/2026).
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PORTA=9222
PERFIL_CHROME="$PROJETO/browser_profiles/chrome-robo"

# Recarregar um agente que já roda com o mesmo .plist reiniciaria o Chrome do robô e o PIN
# do token se perderia: nesse caso, mantém como está.
igual_e_rodando() {
  local rotulo="$1" novo="$2"
  [[ -z "${LCF_TESTE:-}" ]] || return 1
  [[ -f "$AGENTES/$rotulo.plist" ]] && cmp -s "$novo" "$AGENTES/$rotulo.plist" \
    && launchctl print "$DOMINIO/$rotulo" >/dev/null 2>&1
}

registrar_chrome_robo() {
  local rotulo="$PREFIXO.chrome-robo"
  local novo
  novo="$(mktemp)"
  mkdir -p "$PERFIL_CHROME" && chmod 700 "$PERFIL_CHROME"
  cat > "$novo" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$rotulo</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CHROME</string>
    <string>--user-data-dir=$PERFIL_CHROME</string>
    <string>--remote-debugging-port=$CHROME_PORTA</string>
    <string>--no-first-run</string>
    <string>--no-default-browser-check</string>
    <string>--hide-crash-restore-bubble</string>
    <string>--disable-background-timer-throttling</string>
    <string>--disable-backgrounding-occluded-windows</string>
    <string>--disable-renderer-backgrounding</string>
    <string>--disable-popup-blocking</string>
    <string>file://$PROJETO/ops/launchd/chrome-robo.html</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>$LOGS/chrome-robo.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS/chrome-robo.log</string>
</dict>
</plist>
PLIST
  if igual_e_rodando "$rotulo" "$novo"; then
    echo "Mantido (já rodando): $rotulo"
    rm -f "$novo"
  else
    descarregar "$rotulo"
    mv "$novo" "$AGENTES/$rotulo.plist"
    carregar "$rotulo"
  fi

  # Logo após o login do Mac e a cada 5 min: se o Chrome do robô foi (re)aberto desde o
  # último desbloqueio, pede o PIN nesse Chrome e avisa o operador por e-mail.
  rotulo="$PREFIXO.chrome-robo-pin"
  novo="$(mktemp)"
  cat > "$novo" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$rotulo</string>
  <key>ProgramArguments</key>
  <array>
    <string>$EXE</string>
    <string>chrome-robo-desbloquear</string>
    <string>--se-necessario</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJETO</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>300</integer>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardOutPath</key>
  <string>$LOGS/chrome-robo-pin.log</string>
  <key>StandardErrorPath</key>
  <string>$LOGS/chrome-robo-pin.log</string>
</dict>
</plist>
PLIST
  if igual_e_rodando "$rotulo" "$novo"; then
    echo "Mantido (já rodando): $rotulo"
    rm -f "$novo"
  else
    descarregar "$rotulo"
    mv "$novo" "$AGENTES/$rotulo.plist"
    carregar "$rotulo"
  fi
}

mkdir -p "$AGENTES" "$LOGS"

if [[ "${1:-}" == "--remover" ]]; then
  for f in "$AGENTES/$PREFIXO".*.plist(N); do descarregar "${f:t:r}"; done
  echo "Robôs removidos."
  exit 0
fi

registrar_acordado
[[ "${1:-}" == "--so-acordado" ]] && exit 0
if [[ "${1:-}" == "--so-chrome" ]]; then
  registrar_chrome_robo
  exit 0
fi

[[ -x "$EXE" ]] || { echo "legal-monitor não encontrado em $EXE" >&2; exit 1; }

registrar_chrome_robo

# Remove robôs de agendas antigas (ex.: um por site do PJe/Portal) antes de registrar.
for f in "$AGENTES/$PREFIXO".robo.*.plist(N); do descarregar "${f:t:r}"; done

for site minuto in ${(kv)DE_HORA_EM_HORA}; do
  rotulo="$PREFIXO.robo.$site"
  descarregar "$rotulo"
  escrever_robo "$rotulo" "monitor-run --site $site --no-interactive-login" \
    "  <dict><key>Minute</key><integer>$minuto</integer></dict>" "$LOGS/robo-$site.log"
  carregar "$rotulo"
done

rotulo="$PREFIXO.robo.janela-login"
bloco="  <array>"$'\n'
for h in ${(z)JANELA_HORARIOS}; do
  bloco+="    <dict><key>Hour</key><integer>$((10#${h%%:*}))</integer><key>Minute</key><integer>$((10#${h##*:}))</integer></dict>"$'\n'
done
bloco+="  </array>"
descarregar "$rotulo"
escrever_robo "$rotulo" "monitor-sequencia" "$bloco" "$LOGS/robo-janela-login.log"
carregar "$rotulo"

echo "Pronto. Conferir: launchctl list | grep $PREFIXO"
