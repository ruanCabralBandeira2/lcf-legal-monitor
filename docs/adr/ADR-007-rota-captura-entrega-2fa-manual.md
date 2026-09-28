# ADR-007 - Rota de captura, entrega e login por token com 2FA humano

- Status: aceito; fatia M4a/M4b/M6-e-mail implementada na versão 0.7.0
- Data: 2026-09-28

## Contexto

Em 28/09/2026 o responsável técnico registrou:

1. a autorização da LCF para o piloto, com acesso por conta de advogado;
2. o fluxo desejado: receber o número CNJ, consultar TJRJ (eproc), eproc TRF2 e PDPJ-Br, detectar movimentação nova, baixar o conteúdo integral e entregar ao advogado;
3. a entrega inicial por **e-mail** e o armazenamento em pasta no **Mac mini**. Telefone fica para depois;
4. o login dos sistemas é feito com **certificado em token USB**. Quando houver 2FA, o robô deve **avisar** o operador, que aprova pelo **celular**.

O desenvolvimento ocorre em Windows; a operação (token USB, navegador, Keychain, launchd, armazenamento) ocorre no Mac mini.

## Decisão

### Roteamento pelo número CNJ

O segmento `J.TR` define as fontes candidatas, sem rede (`legal_monitor.connectors.routing`):

| `J.TR` | Tribunal | Fontes candidatas, em ordem |
|---|---|---|
| `8.19` | TJRJ | `eproc-tjrj-1g` -> `eproc-tjrj-2g` -> `pdpj` |
| `4.02` | TRF2 | `eproc-trf2` -> `pdpj` |
| outro | - | `pdpj` |

Endereços conferidos em 28/09/2026: `eproc1g.tjrj.jus.br` (login pelo SSO Jus.br), `eproc.trf2.jus.br` (login próprio) e `portaldeservicos.pdpj.jus.br` (SSO Jus.br). `eproc2g.tjrj.jus.br` será confirmado no primeiro login. eproc TJRJ e PDPJ compartilham o realm `jusbr`: uma única sessão cobre as duas fontes.

### Sessão, token USB e 2FA

- O robô usa o Google Chrome instalado (`BROWSER_CHANNEL=chrome`), que enxerga o certificado do token pelo repositório do sistema.
- `legal-monitor auth-open <fonte>` abre janela visível e clica no botão público "Certificado Digital". A seleção do certificado, o PIN do token (se o middleware pedir) e a aprovação do 2FA ficam com a pessoa.
- Se a sessão não ficar válida em 20 s, o robô envia **um** aviso "aprove no celular" ao operador e aguarda até 10 min, verificando sozinho. Nenhum código, senha ou PIN é digitado, lido ou armazenado.
- A sessão resultante (cookies) é salva em `browser_profiles/<realm>/storage_state.json` (fora do Git, 0600). Usamos `storage_state` e não perfil persistente porque o SSO usa cookies de sessão, que o Chromium descarta ao fechar.
- `legal-monitor auth-check [--notify]` testa as sessões em modo headless. Sessão expirada abre `manual_action` única por fonte (índice parcial na migração 004) e envia **um** e-mail "login necessário" ao operador. Sessão válida resolve a ação e rearma o aviso.

### Captura (próxima fatia)

- Por movimento novo: baixar os documentos do evento e, quando a fonte oferecer, o PDF integral dos autos.
- Todo arquivo passa por `documents.service` (validação, limite, SHA-256, escrita atômica) antes da entrega.

### Armazenamento e entrega

- Primário: `storage/documents/` no Mac mini; depois, compartilhamento SMB autenticado no escritório, sem link público.
- E-mail: `EmailNotifier` via SMTP SSL; senha de app no cofre do sistema (`keyring`: Keychain no macOS, Gerenciador de Credenciais no Windows); PDFs somente de raiz permitida e até `EMAIL_MAX_ATTACHMENT_BYTES` (20 MiB). Acima disso, o e-mail aponta a pasta no Mac mini.
- Telefone (SMS/WhatsApp oficial) e Discord operacional: adiados. O bot Discord criado pelo usuário é candidato a receber somente avisos operacionais sem dado jurídico.

### Fontes que recusam navegador sem janela (28/09/2026)

O PJe TJRJ responde HTTP 403 ao navegador headless e abre normalmente no navegador comum. O operador autorizou que o robô use **janela visível** do navegador comum (Edge no Windows, Chrome no Mac) para essas fontes (`headless_blocked` no catálogo + `BROWSER_VISIBLE_FOR_BLOCKED=true`). Proibido: user-agent falso, plugins furtivos, técnicas antifingerprint ou qualquer evasão. Sem a flag, a fonte é reportada `UNAVAILABLE`.

## Consequências

- Clicar no botão de login por certificado não automatiza o 2FA: a aprovação continua humana. A regra do `AGENTS.md` permanece válida.
- A sessão salva equivale a um login ativo do advogado. O Mac mini precisa de FileVault, usuário dedicado e tela bloqueada.
- Se o Chrome sob Playwright não exibir o seletor de certificado do token no macOS, a alternativa registrada é conectar via CDP a um Chrome aberto pelo operador com perfil dedicado (`--remote-debugging-port` somente em localhost).
- O parser eproc depende de HTML real capturado de um processo autorizado; as fixtures serão sanitizadas antes de entrar no Git.
