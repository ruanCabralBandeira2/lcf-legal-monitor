#!/bin/zsh
# Seleção automática do certificado do advogado no Google Chrome (política oficial
# AutoSelectCertificateForUrls), SÓ para os sites dos tribunais monitorados e SÓ para o
# certificado emitido pela AC OAB G3. Tira o clique "OK" da janela "Selecione um
# certificado" (Portal TJRJ e eproc), para os robôs logarem sozinhos.
#
# Decisão do titular do certificado (ADR-010). O PIN continua no token/SafeSign: nada é
# guardado aqui.
#
#   ops/macos/certificado-automatico.sh ativar
#   ops/macos/certificado-automatico.sh desativar
#   ops/macos/certificado-automatico.sh status
set -euo pipefail

DOMINIO="${LCF_DOMINIO:-com.google.Chrome}"  # LCF_DOMINIO: só para teste
CHAVE="AutoSelectCertificateForUrls"
EMISSOR="AC OAB G3"
SITES=(tjrj.jus.br jfrj.jus.br trf2.jus.br)

case "${1:-status}" in
  ativar)
    lista=""
    for site in $SITES; do
      regra="{\\\"pattern\\\":\\\"https://[*.]$site\\\",\\\"filter\\\":{\\\"ISSUER\\\":{\\\"CN\\\":\\\"$EMISSOR\\\"}}}"
      lista+="${lista:+, }\"$regra\""
    done
    defaults write "$DOMINIO" "$CHAVE" "($lista)"
    echo "Ativado para: $SITES (emissor $EMISSOR)."
    echo "Feche o Chrome (Cmd+Q) e confira em chrome://policy."
    ;;
  desativar)
    defaults delete "$DOMINIO" "$CHAVE" 2>/dev/null || true
    echo "Desativado. Feche o Chrome (Cmd+Q) para valer."
    ;;
  status)
    defaults read "$DOMINIO" "$CHAVE" 2>/dev/null || echo "Não configurado."
    ;;
  *)
    echo "uso: $0 ativar|desativar|status" >&2
    exit 2
    ;;
esac
