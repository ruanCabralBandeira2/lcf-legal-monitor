# Runbook - scheduler e heartbeat

## Verificação manual

```bash
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python scripts/migrate.py
.venv/bin/legal-monitor scheduler-heartbeat
.venv/bin/legal-monitor scheduler-health
```

`platform_alive=true` confirma banco acessível e heartbeat recente. Não confirma que cada processo foi consultado; verificar também `processes_overdue`, `processes_without_success` e, futuramente, `last_success_at` por fonte.

## Smoke test fictício

```bash
.venv/bin/legal-monitor scheduler-enqueue-healthcheck --key smoke-local-001
.venv/bin/legal-monitor scheduler-run-once
.venv/bin/legal-monitor scheduler-health
```

Repetir o primeiro comando com a mesma chave deve retornar o mesmo job com `created=false`.

## launchd

O template `ops/launchd/com.lcf.legal-monitor.worker.plist.example` executa um lote curto a cada minuto. Antes de instalar:

1. Substituir `__PROJECT_DIR__` pelo caminho absoluto do repositório.
2. Confirmar `.env` local com permissão `600` e sem credencial fictícia em produção.
3. Copiar o arquivo resultante para `~/Library/LaunchAgents` somente após revisão do administrador.
4. Carregar com `launchctl bootstrap gui/$(id -u) arquivo.plist`.
5. Confirmar logs, heartbeat e reinício após boot.

Não instalar o template enquanto o serviço ainda estiver em desenvolvimento ativo.

## Incidentes

- Worker stale: verificar PostgreSQL, logs, espaço em disco e status do launchd.
- Lease expirando com frequência: investigar duração do handler; não aumentar o lease sem medir.
- Job `PAUSED`: revisar `error_code`; CAPTCHA/2FA exigem ação humana, nunca repetição cega.
- Job `FAILED`: consultar `job_attempt`, correlation ID e runbook da fonte antes de reenfileirar.
