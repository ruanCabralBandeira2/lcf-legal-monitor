# ADR-011 - Chrome do robô sempre aberto (login sem intervenção diária)

- Status: aceito; em validação no Mac mini desde 30/09/2026
- Data: 2026-10-01

## Contexto

Com um Chrome novo a cada rodada, o operador gastava cerca de 20 minutos por dia em logins: escolher o certificado, digitar o PIN do token, marcar o perfil "Advogado" no Portal e aprovar o 2FA. Os testes em 30/09/2026 mostraram:

- a escolha do certificado é resolvida pela política oficial do Chrome `AutoSelectCertificateForUrls`, restrita aos domínios `tjrj.jus.br`, `jfrj.jus.br` e `trf2.jus.br` e ao emissor `AC OAB G3` (`ops/macos/certificado-automatico.sh`);
- o macOS guarda o PIN do token **por processo** do Chrome. O "Timeout do PIN" do SafeSign não muda isso, então cada Chrome novo pedia o PIN;
- o PJeOffice guarda o PIN no próprio processo, com a opção oficial "Apenas no primeiro acesso (com confirmação)";
- o eproc tem a opção oficial "Não usar o 2FA neste dispositivo e navegador" (cookie; vale enquanto houver acesso em até 30 dias).

Guardar ou digitar o PIN por software foi descartado: não é oficial e o macOS bloqueia digitação automática no diálogo do PIN. O certificado A1 (arquivo, sem PIN) fica como alternativa para decisão do titular.

## Decisão

- Um **Chrome do robô** (`com.lcf.legal-monitor.chrome-robo`) abre no login do Mac com perfil próprio, depuração **só em 127.0.0.1:9222** (validado na configuração), pop-ups liberados e a página "NÃO FECHE". O `KeepAlive` reabre o Chrome se ele fechar.
- Os robôs se conectam a ele (`BROWSER_CDP_URL`), criam um contexto próprio por rodada (cookies carregados/salvos por site) e fecham só esse contexto. As janelas abrem minimizadas (`BROWSER_MINIMIZE`); login com gente abre visível.
- `chrome-robo-desbloquear --se-necessario` roda no login do Mac e a cada 5 min: se o Chrome do robô é outro processo desde o último desbloqueio (id do navegador no CDP), entra no Portal para o macOS pedir o PIN, faz o login do PJe para o PJeOffice pedir o PIN e avisa o operador por e-mail.
- O Portal escolhe sozinho o perfil "Advogado" (caixa `#dropdownPerfil`) e clica na caixa verde `.rodape-confirma` ("Entrar"), porque o `<a>` em volta dela não tem tamanho próprio.
- Com `AUTO_CERT_LOGIN`, os robôs de hora em hora do eproc refazem o login sozinhos (até 150 s); se algo pedir gente, avisam como antes.
- Ao fim da rodada, no modo CDP, só os cookies são salvos (`storage_state()` ficou preso para sempre no TRF2/TRF4).
- Cada rodada tem tempo máximo de 90 min; na sequência de login cada site roda em processo separado, para um site travado não bloquear os outros.
- **Fila: um robô por vez no Chrome do robô** (`chrome-robo-uso.lock`, espera até 50 min). Com dois clientes conectados ao mesmo Chrome, cada janela nova espera que todos a liberem; um robô ocupado fora do navegador congelava as janelas do outro (TRF2/TRF4 e PJe em 01/10/2026).
- Sites pausados pelo operador (`PAUSED_SITES`): JFRJ (sem o 2FA configurado) e TRF4 (sem cadastro do titular).
- **eproc usa o perfil normal (não anônimo) do Chrome do robô** (`persistent_profile`): o manual oficial do 2FA avisa que "Não usar o 2FA neste dispositivo e navegador" não vale em janela anônima, e o contexto isolado do robô era tratado assim (o TRF2 pediu o 2FA de novo em 01/10/2026). O robô só abre e fecha as próprias abas; a página "NÃO FECHE" nunca é navegada.
- PJe: cada contexto recebe a permissão `local-network-access` só para os endereços oficiais do PJe (SSO, TJRJ, TRT1), para a página falar com o PJeOffice no Mac sem o Chrome perguntar "acessar apps deste dispositivo" em toda rodada.

## Consequências

- Intervenção humana só depois de reiniciar o Mac ou fechar o Chrome do robô: digitar o PIN uma vez (Parsec), avisado por e-mail.
- Quem usa o Mac com o token plugado pode usar o certificado sem PIN enquanto o Chrome do robô estiver aberto; o Mac deve ficar em local controlado. O PJeOffice continua pedindo confirmação para assinar.
- A porta de depuração local dá controle do Chrome do robô a programas do próprio Mac: o Mac é dedicado e de usuário único.
