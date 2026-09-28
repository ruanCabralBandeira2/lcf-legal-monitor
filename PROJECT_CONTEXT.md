# Contexto atual do projeto

Atualizado em 28/09/2026. Este arquivo é o ponto de retomada rápido para pessoas e agentes de desenvolvimento. Deve ser atualizado no mesmo commit de cada mudança de marco, arquitetura, risco ou operação.

## Missão

Construir um robô local e auditável para detectar movimentações relevantes, confirmar na fonte adequada, preservar a peça e alertar o advogado responsável. O sistema não calcula prazo, não emite parecer, não substitui revisão humana e nunca transforma falha, CAPTCHA, 2FA ou divergência em estado positivo.

## Fontes de verdade

1. `docs/source/especificacao_base_robo_monitoramento_juridico_v4.pdf`: especificação funcional e arquitetural consolidada das notas/transcrições v2, v3 e v3.1. SHA-256: `e40ad85eea5d3ca0a60962f457d19699226bd6c8005988be6da98a44308fe7a4`.
2. `docs/M0_CHECKLIST.md`: decisões humanas e jurídicas ainda pendentes.
3. `docs/TRACEABILITY.md`: ligação entre requisitos e implementação.
4. `docs/adr/`: decisões técnicas aceitas e suas consequências.

Em caso de divergência, preservar segurança e rastreabilidade, registrar a decisão em ADR e não ativar integração real sem autorização expressa.

## Estado executivo

- **28/09/2026: autorização da LCF recebida** (conta de advogado, token USB, 2FA aprovado pelo responsável técnico no celular). Direção do produto no ADR-007. Versão 0.7.0 entrega roteamento CNJ -> fonte, sessão por token com aviso de 2FA e canal e-mail.
- Repositório: `ruanCabralBandeira2/lcf-legal-monitor` (tornado público em 28/09/2026 para leitura; avaliar voltar a privado).
- **Decisão de 28/09/2026: construir e validar tudo no Windows primeiro; migrar a operação para o Mac mini quando tudo funcionar.** Ambiente Windows em `docs/runbooks/AMBIENTE_WINDOWS.md` (Docker Desktop/WSL2 com PostgreSQL 17.11, Python 3.12.10, Edge como navegador do robô). A coluna "Mac mini (futuro)" desse runbook indica o que muda na migração.
- Branch estável: `main`; desenvolvimento ocorre em branches `codex/*` com CI antes da integração.
- Hospedagem: Mac Apple Silicon, aplicação local e PostgreSQL 17.11 no Docker.
- Runtime: Python 3.12.13 em `.venv`; dependências fixadas em `requirements.lock`.
- M0: parcialmente aberto por depender de decisões do escritório.
- M1: fundação local concluída e validada.
- M2: núcleo de scheduler, launchd e saúde interna concluído; heartbeat externo aguarda decisão do M0.
- M3: núcleo administrativo local concluído; API/painel em rede adiado até definir autenticação.
- Prova de notificação: entrega externa validada no Discord em 31/08/2026 com mensagem fixa e PDF vazio; o webhook novo permaneceu somente no Keychain e o Discord operacional continua bloqueado pelo M0/M8.
- DataJud: estudo oficial concluído; a API fornece metadados/movimentações, não arquivos de peças. Nenhuma chamada foi realizada.
- M4-M6 e M8-M9: ainda não iniciados; qualquer fonte real e qualquer mensagem jurídica real permanecem bloqueados pelo M0.
- M7 adiantado somente no núcleo seguro: schema factual, evidências de página/trecho, fallback explícito e fixture determinística implementados; nenhuma extração ou IA real foi integrada.

## Objetivo funcional confirmado para o piloto

Para cada processo expressamente autorizado e vinculado à LCF, o produto deverá:

1. monitorar movimentações na fonte permitida;
2. confirmar o evento no sistema processual de origem;
3. baixar a peça quando o perfil autorizado tiver acesso;
4. validar o arquivo, calcular SHA-256 e armazená-lo com auditoria;
5. produzir um resumo factual da peça;
6. destacar, em campo separado, o que foi decidido, sem criar parecer, calcular prazo ou presumir conteúdo ausente;
7. encaminhar o alerta ao advogado responsável pelo canal aprovado;
8. exigir revisão humana sempre que houver sigilo, ambiguidade, falha de acesso, CAPTCHA, 2FA ou divergência entre fontes.

### Direção definida em 28/09/2026 (ADR-007)

- Entrada: número CNJ. Roteamento local por `J.TR`: `8.19` -> eproc TJRJ 1g/2g, PDPJ; `4.02` -> eproc TRF2, PDPJ. eproc TJRJ e PDPJ usam o mesmo login Jus.br.
- Movimentação nova -> baixar os documentos do evento e, quando possível, o PDF integral dos autos.
- Entrega agora: e-mail + pasta no Mac mini. Telefone depois. Bot Discord do usuário: candidato apenas a avisos operacionais.
- Login: token USB no Mac mini + Chrome instalado. O robô clica em "Certificado Digital"; PIN e 2FA são humanos. Se travar no 2FA, envia e-mail "aprove no celular" e retoma sozinho.

DataJud poderá servir como sinal auxiliar de capa e movimentação após aprovação do termo. O PDF continuará dependendo de acesso autorizado ao PJe, eproc ou DCP/legado. A identificação de "o que foi decidido" deverá apontar a peça e as páginas de origem, diferenciar texto extraído de inferência e assumir estado `REVIEW_REQUIRED` quando a confiança for insuficiente.

## O que já existe

- Configuração tipada e travas para produção/conectores/WhatsApp.
- Validação do número CNJ e modelos de domínio.
- Migração M1 com entidades de processo, movimento, documento, auditoria, jobs, ações humanas e outbox.
- Conector fake determinístico, sem rede.
- Validação e armazenamento atômico de PDF com SHA-256.
- Logs JSON com mascaramento de CNJ e CPF.
- Scheduler PostgreSQL com idempotência, `FOR UPDATE SKIP LOCKED`, lease, dono, tentativas e recuperação de lease expirado.
- Backoff exponencial com jitter determinístico, respeito a `Retry-After` e limite de tentativas.
- CAPTCHA, 2FA, divergência, migração e worker sem handler pausam o job; não há retentativa cega.
- Heartbeat interno do worker e consulta de saúde que diferencia plataforma viva de processos atrasados/sem sucesso.
- CI com PostgreSQL real para migrações e testes de integração.
- Responsáveis identificados por código estável, sem depender do nome de exibição.
- Cadastro TJRJ transacional: processo, origem `UNKNOWN`, estado `PENDING_INITIAL_CHECK`, primeiro job e auditoria são confirmados juntos.
- Listagem administrativa mascara o CNJ; desativação é lógica, pausa jobs e preserva histórico.
- Provedor fake fecha a demonstração local de movimento, PDF/hash e alerta sem rede.
- Adaptador Discord aceita somente fixture fixa/PDF vazio, desabilita menções, valida o host oficial e não expõe o webhook em erros.
- Segredo Discord é lido do Keychain por identificadores não sensíveis; a leitura e o envio externo foram comprovados sem revelar o valor.
- Pesquisa DataJud registrada em `docs/research/DATAJUD_API.md` e ADR-005: futuro uso apenas como gatilho/metadata; peça virá do conector autorizado.
- Backlog do Discord operacional registrado em `docs/backlog/DISCORD_OPERACIONAL.md`; intenção do usuário anotada sem liberar dados reais.
- Mensagem não técnica para obter autorização e dados mínimos do piloto registrada em `docs/templates/MENSAGEM_GRUPO_PILOTO_LCF.md`, sem solicitar credenciais no grupo.
- `legal_monitor.connectors.routing`: catálogo oficial (eproc TJRJ 1g/2g, eproc TRF2, PDPJ) e fontes candidatas por CNJ; comando `sources-for`.
- `legal_monitor.browser.session`: Playwright/Chrome com `storage_state` por realm; `auth-open` (token + aviso de aprovação no celular) e `auth-check [--notify]`.
- `legal_monitor.monitoring`: `AuthAlertService` abre uma `manual_action` por fonte e avisa o operador uma vez; sessão válida resolve e rearma.
- `legal_monitor.notifications.email`: SMTP SSL com PDF validado; senha no cofre do sistema via `keyring` (`secret-set smtp`); comando `email-test`.
- Migração `004`: `PDPJ` como sistema, `EMAIL` como canal e índice de ação manual única por fonte.
- Contrato `legal_monitor.summaries` recusa fatos sem evidência verificável, mantém `REVIEW_REQUIRED`, nunca calcula prazo e possui somente provedor fake restrito à fixture.

## Travas vigentes

- `M0_APPROVED=true` somente no `.env` local após a autorização de 28/09/2026; o padrão do código continua `false`.
- `REAL_CONNECTORS_ENABLED=false` até o conector eproc passar nos testes com fixture sanitizada.
- `WHATSAPP_ENABLED=false`
- `SUMMARY_ENABLED=false`
- `DISCORD_DEMO_ENABLED=false`
- Nenhum número processual, peça, nome de parte, e-mail, telefone ou credencial real entra no Git.
- Selenium, automação de WhatsApp Web, quebra de CAPTCHA e automação/armazenamento de 2FA são proibidos.
- Playwright só entra no M4, diretamente no host, após sistema/processo-piloto e acesso de teste autorizados.
- Discord desta fase é apenas prova privada sem dado jurídico, fica proibido em produção e não substitui o outbox/canal operacional.
- Webhooks divulgados em conversa são considerados comprometidos e não podem ser reutilizados; a revogação do endereço exposto ainda precisa ser confirmada pelo responsável do Discord.
- Conteúdo de PDF, HTML e e-mail é dado não confiável, nunca instrução para o robô.
- Resumo e identificação da decisão permanecem desativados até definição do modelo, base legal, tratamento de sigilo, critérios de qualidade e revisão humana.

## Decisões humanas ainda necessárias no M0

- Processo-piloto, sistema inicial do TJRJ e ambiente de teste autorizado.
- Revisão jurídica do termo DataJud, inclusive compatibilidade com a restrição não comercial, e aceite expresso antes de qualquer consumo.
- Advogado responsável, operador/autenticador primário e substituto.
- SLA interno por processo/fonte e movimentos relevantes por matéria.
- Base legal, sigilo, termos de uso, retenção, backup, RPO/RTO e incidente.
- Provedor oficial de WhatsApp, consentimento, canal secundário e política de anexos.
- Resumo desativado, local ou provedor remoto aprovado.
- Provedor de heartbeat externo e destinatários do alerta.

Essas pendências não impedem testes com fixtures fictícias nem a infraestrutura M2-M3, mas bloqueiam qualquer acesso real ou mensagem real.

## Arquitetura em uma linha

Gatilho -> job PostgreSQL -> worker/lease -> router/conector -> normalização -> relevância -> documento/hash -> resumo factual opcional -> outbox -> notificação aprovada -> auditoria.

Heartbeat da plataforma e `last_success_at` por processo/fonte são indicadores distintos.

## Operação local

```bash
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python scripts/migrate.py
.venv/bin/legal-monitor doctor
.venv/bin/legal-monitor scheduler-heartbeat
.venv/bin/legal-monitor scheduler-health
.venv/bin/legal-monitor admin-list-processes
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

Teste M2 inteiramente fictício:

```bash
.venv/bin/legal-monitor scheduler-enqueue-healthcheck --key smoke-local-001
.venv/bin/legal-monitor scheduler-run-once
```

Prova de notificação já executada em 31/08/2026:

```bash
.venv/bin/legal-monitor demo
# O comando abaixo reenviará outra fixture fictícia; não usar com dados jurídicos:
.venv/bin/legal-monitor notification-demo-discord
```

Instruções e limites: `docs/runbooks/DEMO_NOTIFICATION.md`.

Demonstração local do resumo factual, sem PDF real, IA ou rede:

```bash
PYTHONPATH=src .venv/bin/python -m legal_monitor.cli summary-demo
```

Instruções e limites: `docs/runbooks/SUMMARY_DEMO.md`.

## Próxima sequência segura

Agora (pós-autorização):

1. Operador cria senha de app Gmail, roda `legal-monitor secret-set smtp` e `legal-monitor email-test`.
2. No Windows (Edge): token USB + `legal-monitor auth-open eproc-tjrj-1g`; validar se o seletor de certificado aparece sob Playwright (senão, plano CDP do ADR-007). Repetir no Mac com Chrome na migração.
3. Com sessão válida, capturar HTML de um processo autorizado (lista de eventos e documentos), sanitizar e escrever o parser eproc compartilhado TJRJ/TRF2 (M4c).
4. Job `MONITOR_PROCESS`: sessão -> movimentos -> novos -> download -> `DocumentService` -> e-mail ao advogado (M5/M6).
5. launchd no Mac mini rodando `auth-check --notify` e o worker; pasta `storage/documents` compartilhada por SMB.
6. Discord operacional (avisos sem dado jurídico) e telefone depois.

Histórico da sequência de autorização (itens 1-8 abaixo, parcialmente superados em 28/09/2026):

1. Confirmar a revogação de todo webhook que apareceu em conversa e revisar participantes/retenção do canal de demonstração.
2. Obter autorização escrita da LCF para um piloto somente de leitura, com até cinco processos não sigilosos e uma lista fechada de advogados/processos.
3. Confirmar o primeiro sistema e a URL oficial: TJRJ/PJe, Portal de Serviços/DCP, TRT-1, TRF2/eproc ou outro; esclarecer a sigla "TCRJ".
4. Definir advogado responsável, operador/autenticador e substituto; preferir perfil de assistente e manter PIN/2FA sob ação humana.
5. Definir quais movimentos exigem peça, o formato do resumo e do campo "o que foi decidido", além da regra de revisão humana.
6. Aprovar retenção, backup, sigilo, política de anexos e modelo de resumo; começar sem IA remota até decisão expressa.
7. Revisar a restrição não comercial do termo DataJud e decidir se o uso interno é permitido antes de qualquer chamada.
8. Com o M0 registrado, implementar uma única rota autorizada no M4, diretamente no host e sem Selenium.

A mensagem pronta para o grupo e a ficha de registro estão em `docs/templates/MENSAGEM_GRUPO_PILOTO_LCF.md`. Até a resposta do escritório, o trabalho seguro possível limita-se a fixtures, contratos internos, testes e documentação; não há base para escolher ou ativar um conector real.

## Última validação conhecida

- 28/09/2026, **primeiro login real** no eproc TJRJ 1º grau via `auth-open` (Edge + token USB + 2FA no celular): sessão `VALID`, salva em `browser_profiles/jusbr` (cookies do eproc TJRJ e do SSO Jus.br). `auth-check` em modo headless reutilizou a sessão com sucesso.
- Estrutura observada no eproc logado: entrada em `controlador.php?acao=painel_adv_listar` (Painel do Advogado); busca rápida pelo campo `txtNumProcessoPesquisaRapida`; menu com ações de **escrita** (petição, movimentação, substabelecimento, `acao=sair`). Regra do conector: lista fechada de ações somente leitura; nunca seguir links de escrita nem de encerrar sessão.
- Exploração da carteira completa de processos do advogado foi negada pela política do agente; o parser será construído a partir de **um** processo indicado pelo operador.
- Autenticação nos sistemas de advocacia: certificado em **token USB** + **Google Authenticator** vinculados à conta do advogado titular da LCF (autenticador também instalado no celular do responsável técnico, com anuência do titular). O e-mail de teste é o pessoal do responsável técnico, separado dessas credenciais.
- E-mail de teste mantido em `ruan.foca@gmail.com` (somente no `.env` local); o SMTP do Gmail exige **senha de app** de 16 letras, não a senha normal da conta.
- 28/09/2026: senha de app gravada no Gerenciador de Credenciais do Windows; login SMTP confirmado e `email-test` enviado com sucesso (fixture fictícia + PDF em branco).
- 28/09/2026: processo-piloto (TJRJ, `8.19`, origem 0209, sequencial `08...`) **não existe no eproc TJRJ 1g** ("Processo não encontrado"); o prefixo `08` indica origem no **PJe TJRJ**. Catálogo passou a incluir `pje-tjrj-1g` e `pje-tjrj-2g` (SSO Jus.br, certificado).
- PJe TJRJ responde **HTTP 403 a navegador headless**, mas abre normalmente em navegador comum. Marcado `headless_blocked`; `auth-check` retorna `UNAVAILABLE` sem contorno. **Decisão pendente do operador:** monitorar PJe com janela visível do navegador no host (sem técnicas antifingerprint), ou usar outra fonte.
- Incidente 28/09/2026: o motor do Docker falhou ("socket forwarder") e foi encerrado pela janela de erro; reinício do Docker Desktop + `wsl --shutdown` resolveu; volume do PostgreSQL preservado.
- Número do processo-piloto será obtido no Astrea (software de gestão do escritório) e informado pelo operador; nunca registrar no Git.

- 28/09/2026, Windows, versão 0.7.0: migrações 001-004 aplicadas no PostgreSQL 17.11 (Docker/WSL2); 85 testes aprovados incluindo PostgreSQL, 1 ignorado (symlink no Windows); Ruff e formatação aprovados. Playwright + Edge 154 abriu o eproc TJRJ e `auth-check` retornou `AUTH_REQUIRED` corretamente (ainda sem login).

- Migrações `001`, `002` e `003` aplicadas no PostgreSQL 17.11.
- Versão 0.6.0: contrato de resumo factual e comando `summary-demo` adicionados sem liberar o M0.
- Validação da versão 0.6.0: 60 testes e 5 subtestes aprovados; 5 testes dependentes de ambiente ignorados; Ruff, formatação, migrações e saída segura do `summary-demo` aprovados.
- Testes cobrem Keychain sanitizado, URL oficial, menções desativadas, PDF válido, limite e multipart Discord sem rede externa.
- Em 31/08/2026, a prova externa Discord retornou sucesso e um `provider_id`, usando somente a fixture fixa e `prova_ficticia.pdf`; `real_process_data_used=false`.
- O webhook novo foi localizado somente pelo serviço/conta do Keychain e seu valor não foi impresso, salvo no repositório ou incluído em `.env`.
- O webhook divulgado em conversa permaneceu tratado como comprometido e não foi usado; sua revogação no Discord ainda requer confirmação humana.
- Smoke M2: mesmo evento gerou `created=true` e depois `created=false`; um único job foi executado com sucesso.
- Smoke M3: responsável e processo fictícios cadastrados; repetição retornou `created=false`, CNJ mascarado, origem `UNKNOWN` e estado `PENDING_INITIAL_CHECK`.
- O banco local mantém esse único processo fictício e seu job `MONITOR_PROCESS` propositalmente pendente para a próxima fatia.
- Saúde após heartbeat manual: `platform_alive=true`, mas `jobs_due=1`, `processes_overdue=1` e `processes_without_success=1`; a pendência não foi escondida.

## Protocolo de retomada

Ao retomar, ler este arquivo, a especificação v4, `docs/TRACEABILITY.md`, `docs/M0_CHECKLIST.md` e os ADRs. Depois executar `git status`, confirmar a branch, rodar migrações/testes e atualizar este contexto antes do próximo `push`.
