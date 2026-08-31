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
| TJRJ real/router/Playwright | bloqueado por M0 e M4-M5 | não iniciado |
| DJEN produção | host guard implementado; cliente real no M6 | parcial |
| Prova de notificação | `legal_monitor.notifications`, `docs/runbooks/DEMO_NOTIFICATION.md` | entrega externa Discord validada em 31/08/2026 com segredo no Keychain e PDF fictício; uso jurídico continua bloqueado |
| Discord/outbox operacional | `docs/backlog/DISCORD_OPERACIONAL.md` | desenho registrado; bloqueado por M0/M8 |
| Push/WhatsApp/IA operacionais | bloqueados por M0 e marcos M6-M8 | não iniciado |
| Resumo factual da peça | `SUMMARY_ENABLED=false`, M7 | objetivo confirmado; modelo, sigilo, proveniência, qualidade e revisão humana pendentes |
| Campo "o que foi decidido" | M7 | não iniciado; deverá citar peça/páginas, separar extração de inferência e falhar para revisão humana |
| M2 - scheduler/leases/backoff | `legal_monitor.scheduler`, `migrations/002_scheduler_health.sql` | implementado; testes unitários e PostgreSQL |
| M2 - launchd/heartbeat interno | `ops/launchd`, `docs/runbooks/SCHEDULER.md`, comandos CLI | implementado; instalação automática ainda não ativada |
| M2 - heartbeat externo | provedor ainda não escolhido no M0 | bloqueado sem esconder a ausência |
| M3 - responsáveis e cadastro | `legal_monitor.admin`, `migrations/003_admin_registration.sql` | implementado com CLI local e testes PostgreSQL |
| M3 - estado e primeira agenda | transação de cadastro cria `PENDING_INITIAL_CHECK` e job | implementado; nunca inicia como saudável |
| M3 - auditoria e ciclo de vida | eventos de cadastro/desativação e exclusão lógica | implementado; histórico preservado |
| M3 - API/painel em rede | CLI administrativa é a interface mínima atual | adiado até definir autenticação e exposição local |
| API Pública DataJud | `docs/research/DATAJUD_API.md`, `ADR-005` | estudo concluído: metadados/movimentos, sem peças; não consumida e aguarda aceite expresso |
