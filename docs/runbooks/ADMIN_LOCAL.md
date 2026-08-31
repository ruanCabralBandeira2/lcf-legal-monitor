# Runbook - administração local

## Preparação

```bash
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python scripts/migrate.py
```

Não cadastrar processo, responsável ou contato real antes da aprovação do M0. Para desenvolvimento, usar somente os exemplos fictícios abaixo.

## Cadastro seguro

```bash
.venv/bin/legal-monitor admin-add-lawyer \
  --code adv-demo \
  --name "Advogado Demonstrativo"

.venv/bin/legal-monitor admin-add-process \
  0000001-69.2026.8.19.0001 \
  --lawyer adv-demo
```

Repetir os comandos não cria duplicatas. Um processo novo deve aparecer como `PENDING_INITIAL_CHECK`, origem `UNKNOWN` e nunca `ACTIVE_HEALTHY`.

## Consulta

```bash
.venv/bin/legal-monitor admin-list-processes
.venv/bin/legal-monitor scheduler-health
```

A CLI mascara o número CNJ. `platform_alive=true` não elimina `jobs_due`, `processes_overdue` ou `processes_without_success`.

## Desativação

```bash
.venv/bin/legal-monitor admin-deactivate-process \
  0000001-69.2026.8.19.0001
```

A operação é lógica e auditada: o processo fica `DISABLED`, jobs ficam pausados e o histórico não é apagado. Reatribuição ou reativação ainda não devem ser feitas diretamente por SQL.
