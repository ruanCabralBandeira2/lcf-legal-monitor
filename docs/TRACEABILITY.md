# Rastreabilidade da especificação v4

| Requisito | Implementação atual | Estado |
|---|---|---|
| M0 - descoberta e riscos | `docs/M0_CHECKLIST.md` | pendente de decisões humanas |
| M1 - repositório/configuração | `pyproject.toml`, `.env.example`, `legal_monitor.config` | implementado |
| M1 - PostgreSQL/migrations | `migrations/001_foundation.sql`, `scripts/migrate.py` | implementado e validado no PostgreSQL 17.11 |
| M1 - logs estruturados | `legal_monitor.logging` | implementado |
| Domínio CNJ e estados | `legal_monitor.domain` | implementado antecipadamente |
| Connector SDK/fake | `legal_monitor.connectors` | implementado antecipadamente |
| Documento/integração | `legal_monitor.documents` | fatia segura implementada |
| TJRJ real/router/Playwright | bloqueado por M0 e M4-M5 | não iniciado |
| DJEN produção | host guard implementado; cliente real no M6 | parcial |
| Push/WhatsApp/IA | bloqueados por M0 e marcos M6-M8 | não iniciado |
| M2 - scheduler/leases/backoff | `legal_monitor.scheduler`, `migrations/002_scheduler_health.sql` | implementado; testes unitários e PostgreSQL |
| M2 - launchd/heartbeat interno | `ops/launchd`, `docs/runbooks/SCHEDULER.md`, comandos CLI | implementado; instalação automática ainda não ativada |
| M2 - heartbeat externo | provedor ainda não escolhido no M0 | bloqueado sem esconder a ausência |
| M3 - responsáveis e cadastro | `legal_monitor.admin`, `migrations/003_admin_registration.sql` | implementado com CLI local e testes PostgreSQL |
| M3 - estado e primeira agenda | transação de cadastro cria `PENDING_INITIAL_CHECK` e job | implementado; nunca inicia como saudável |
| M3 - auditoria e ciclo de vida | eventos de cadastro/desativação e exclusão lógica | implementado; histórico preservado |
| M3 - API/painel em rede | CLI administrativa é a interface mínima atual | adiado até definir autenticação e exposição local |
