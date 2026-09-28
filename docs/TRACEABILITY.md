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
| Parser/download eproc | ADR-007 | não iniciado; depende de HTML real sanitizado |
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
