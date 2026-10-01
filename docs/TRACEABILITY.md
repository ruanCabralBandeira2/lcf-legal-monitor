# Rastreabilidade da especificação v4

| Requisito | Implementação atual | Estado |
|---|---|---|
| M0 - descoberta e riscos | `docs/M0_CHECKLIST.md` | pendente de decisões humanas |
| Comunicação não técnica para aprovação do piloto | `docs/templates/MENSAGEM_GRUPO_PILOTO_LCF.md` | pronta para envio; resposta do escritório pendente |
| M1 - repositório/configuração | `pyproject.toml`, `.env.example`, `legal_monitor.config` | implementado |
| M1 - PostgreSQL/migrations | `migrations/001_foundation.sql`, `scripts/migrate.py` | implementado e validado no PostgreSQL 17.11 |
| M1 - logs estruturados | `legal_monitor.logging` | implementado |
| Domínio CNJ e estados | `legal_monitor.domain` | implementado antecipadamente |
| Connector SDK/fake | `legal_monitor.connectors` | implementado antecipadamente |
| Documento/integração | `legal_monitor.documents` | fatia segura implementada |
| Router CNJ -> fontes (eproc TJRJ, PJe TJRJ, eproc TRF2, PDPJ) | `legal_monitor.connectors.routing`, `sources-for`, ADR-007 | implementado e testado |
| Sessão Playwright + token USB + aviso 2FA no celular | `legal_monitor.browser.session`, `auth-open`, `auth-check`, `legal_monitor.monitoring`, migração 004, `tests/test_manual_action_postgres.py` | implementado; migração 004 validada no PostgreSQL; login real com token validado em 28/09/2026 no eproc TJRJ 1g (Windows/Edge); Mac pendente |
| Ambiente Windows-first e plano de migração ao Mac | `docs/runbooks/AMBIENTE_WINDOWS.md` | validado em 28/09/2026 |
| Conector PJe (consulta, linha do tempo, download) | `legal_monitor.connectors.pje`, `fetch-latest`, ADR-008, `tests/test_pje.py` | primeiro ciclo real validado em 28/09/2026 (PJe TJRJ 1g, e-mail com PDF); filtro de controles de escrita reforçado |
| Parser/download eproc | ADR-007 | não iniciado; processo-piloto está no PJe |
| Canal e-mail | `legal_monitor.notifications.email`, `secret-set`, `email-test`, `docs/runbooks/EMAIL.md` | implementado; envio real validado em 28/09/2026 (email-test) |
| DJEN produção | host guard implementado; cliente real no M6 | parcial |
| Prova de notificação | `legal_monitor.notifications`, `docs/runbooks/DEMO_NOTIFICATION.md` | entrega externa Discord validada em 31/08/2026 com segredo no Keychain e PDF fictício; uso jurídico continua bloqueado |
| Discord/outbox operacional | `docs/backlog/DISCORD_OPERACIONAL.md` | desenho registrado; bloqueado por M0/M8 |
| Push/WhatsApp/IA operacionais | bloqueados por M0 e marcos M6-M8 | não iniciado |
| Resumo factual da peça | `legal_monitor.summaries`, `SUMMARY_ENABLED=false`, ADR-006 | contrato, validação de evidência, fallback e fixture implementados; extração/modelo real bloqueados pelo M0/M7 |
| Campo "o que foi decidido" | `FactualSummaryDraft.decision_result`, `summary-demo` | schema e demonstração fictícia implementados; revisão humana obrigatória |
| M2 - scheduler/leases/backoff | `legal_monitor.scheduler`, `migrations/002_scheduler_health.sql` | implementado; testes unitários e PostgreSQL |
| M2 - launchd/heartbeat interno | `ops/launchd`, `docs/runbooks/SCHEDULER.md`, comandos CLI | implementado; instalação automática ainda não ativada |
| M2 - heartbeat externo | provedor ainda não escolhido no M0 | bloqueado sem esconder a ausência |
| M3 - responsáveis e cadastro | `legal_monitor.admin`, `migrations/003_admin_registration.sql` | implementado com CLI local e testes PostgreSQL |
| M3 - estado e primeira agenda | transação de cadastro cria `PENDING_INITIAL_CHECK` e job | implementado; nunca inicia como saudável |
| M3 - auditoria e ciclo de vida | eventos de cadastro/desativação e exclusão lógica | implementado; histórico preservado |
| M3 - API/painel em rede | CLI administrativa é a interface mínima atual | adiado até definir autenticação e exposição local |
| API Pública DataJud | `docs/research/DATAJUD_API.md`, `ADR-005` | estudo concluído: metadados/movimentos, sem peças; não consumida e aguarda aceite expresso |
| Medição de duração da sessão | `session-watch`, CSV em `storage/tmp` | eproc ~10 h; PJe ~11-16 min após login com certificado, atividade não renova (28/09/2026) |
| Carteira real e separação por site | `legal_monitor.admin.portfolio`, `import-processes`, `sites-report`, `storage/carteira/` (fora do Git) | 118 processos importados em 28/09/2026 |
| Robôs por site e agendas | `monitor-run --site`, `--no-interactive-login`, `ops/windows/registrar-robos.ps1`, ADR-009, `docs/runbooks/ROBOS_POR_SITE.md` | implementado; agendamento a registrar pelo operador após validar cada site |
| Conector eproc (TJRJ, JFRJ, TRF2, TRF4) | `legal_monitor.connectors.eproc`, `tests/test_eproc.py` | extração validada em página sintética no Edge; 1º uso real pendente |
| Processos restritos e eventos de intimação | `MonitoredProcess.sensitivity`, `TimelineItem.documents_allowed` | e-mail só aviso para RESTRICTED; documentos de intimação/citação nunca abertos |
| Resultado de procura por site e registro da rodada | migração 006 `source_lookup`, `logs/monitor-<site>-<data>.json`, `sites-report` (procura) | implementado após a 1ª tentativa real sem sucesso (28/09/2026) |
| Prova positiva de login no eproc | `SourceEndpoint.logged_in_selector`, `classify_session` | corrige falso positivo da tela externa da JFRJ |
| Paginação de eventos do eproc e download por endereço | `EprocConnector.read_timeline` (todas as páginas), `TimelineDocument.href`, `tests/test_eproc.py` (duas páginas simuladas no Edge) | corrigido após 1º ciclo real no TRF2 (28/09/2026) |
| Trava contra enxurrada de novidades | `MAX_INDIVIDUAL_ALERTS`, `_send_burst_summary` | implementado |
| Recusa de login explicada | `LOGIN_REFUSED`, `SessionCheck.detail` | implementado (caso TRF4 "Invalid user") |
| Aviso de banco fora do ar | `alert_database_down` em `legal_monitor.cli`, `tests/test_cli_database_alert.py` | implementado após 2 dias de rodadas falhando em silêncio (28-30/09/2026) |
| Diagnóstico guiado do TJRJ legado | `diagnostico-tjrj` (consulta pública opcional; Portal com gravação guiada de rotas, endereços internos e iframe) | pronto; gravação guiada pendente no Mac |
| Migração para o Mac mini | `docs/runbooks/MIGRACAO_MAC.md`, backup `storage/backups/` (fora do Git) | preparado em 30/09/2026 |
| Conector Portal de Serviços TJRJ (legado) | `legal_monitor.connectors.tjrj_portal`, ADR-010, `tests/test_tjrj_portal.py` | 44/44 processos lidos em 30/09/2026 (3.737 movimentações); peça real (ato assinado, `gedcacheweb`) baixada, validada e enviada por e-mail em 30/09/2026 |
| Aviso de prolongar sessão (Portal) | `keep_session`, `_answer_browser_dialog` | "Sim" só para esse aviso; outras caixas recusadas (teste com Chrome real) |
| Motivo de e-mail sem PDF | `MISSING_*` em `legal_monitor.monitoring.monitor`, `missing_reason` | e-mail e log da rodada dizem por que não há peça |
| Caixa alert/confirm no PJe | `_record_dialog` em `legal_monitor.connectors.pje` | registrada (mascarada) e recusada; revelou 2 processos em que o advogado não é parte |
| Trava por site e teste com poucos processos | `_run_lock` e `--max-processos` em `legal_monitor.cli` | duas rodadas do mesmo site não correm juntas |
| Agendamento no Mac | `ops/launchd/registrar-robos.sh` (LaunchAgents + `caffeinate`) | registrado no Mac; agenda simultânea preparada, ativação após teste |
| Teste de peça sob demanda | `fetch-latest --com-peca --operador` (`LatestMovementService`, Portal e PJe) | e-mail de teste só ao operador, com motivo quando não há PDF |
| Resumo de e-mail legível | `shorten` em `legal_monitor.monitoring.monitor` | corta no fim da palavra com "…" (160 caracteres) |
| Teste de rotina em ambiente real | `admin-reset-history --ultimas N --com-peca` (auditado), `monitor-run --processo` | 30/09/2026: movimentação esquecida voltou como novidade, PDF baixado e e-mail enviado; agenda simultânea disparada pelo launchd (Portal 44/44 OK em 18 min) |
| Login por certificado no JFRJ e TRF2 | `certificate_login_selector` (`SubmitCert`) no catálogo | botão conferido na página pública em 30/09/2026; login real pendente |
| Logins um de cada vez | `monitor-sequencia` (`LOGIN_SEQUENCE`), agente `robo.janela-login` às 13:00 e 00:00 | pedido após o teste simultâneo de 30/09/2026; e-mail de espera orienta concluir pelo Parsec |
| Chrome do robô sempre aberto (PIN uma vez por reinício) | ADR-011, `BROWSER_CDP_URL`, `chrome-robo-desbloquear`, agentes `chrome-robo` e `chrome-robo-pin` | validado em 01/10/2026: Portal sem PIN e sem clique |
| Seleção automática do certificado | `ops/macos/certificado-automatico.sh` (política `AutoSelectCertificateForUrls`) | ativa para TJRJ, JFRJ e TRF2 (emissor AC OAB G3) |
| Perfil "Advogado" no Portal | `_choose_lawyer_profile` (caixa `#dropdownPerfil`, "Entrar" visível) | teste com réplica da tela real e janela oculta "pegadinha" |
| Login automático do eproc e 2FA | `AUTO_CERT_LOGIN`, `login(visible=False)`; "Não usar o 2FA neste dispositivo e navegador" (manual oficial) | aguarda o operador marcar a opção no JFRJ e no TRF2 |
| Rodadas nunca travam a agenda | `_save_state(cookies_only=True)`, `_start_watchdog` (90 min), `_run_site_process` | após TRF2/TRF4 presos em `storage_state()` em 01/10/2026 |
| Fila de um robô por vez no Chrome do robô | `_exclusive_lock` em `legal_monitor.browser.session` (`CDP_QUEUE_SECONDS`) | após travas com dois clientes CDP simultâneos (01/10/2026) |
| Pausar sites | `PAUSED_SITES` no `.env` (`monitor-run` sai sem janela nem aviso; `sites-report` marca `pausado`) | JFRJ e TRF4 pausados em 01/10/2026 |
| PJe sem "acessar apps deste dispositivo" | `allow_local_apps` (permissão `local-network-access` só para `PJE_LOCAL_APP_ORIGINS`) | o Chrome perguntava em toda rodada (contexto limpo); relato do operador em 01/10/2026 |
| eproc no perfil normal do Chrome do robô | `SourceEndpoint.persistent_profile`, `_profile_context` | "dispositivo confiável" do 2FA não vale em janela anônima (manual oficial); 01/10/2026 |
