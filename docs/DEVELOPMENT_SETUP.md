# Preparação do Mac para desenvolvimento

## Situação verificada em 30/08/2026

- Command Line Tools do Xcode 16.4 e Git 2.39.5 disponíveis.
- Docker Desktop 4.88.1, Engine 29.7.2 e Compose 5.4.0 funcionando em Apple Silicon.
- PostgreSQL 17.11 saudável no Docker, exposto somente em `127.0.0.1:5432`.
- Migrações `001_foundation.sql`, `002_scheduler_health.sql` e `003_admin_registration.sql` aplicadas; o esquema contém 17 tabelas.
- Python 3.12.13 e `uv` 0.12.7 instalados somente dentro do projeto.
- Ambiente `.venv` recriado com esse Python e todas as versões de `requirements.lock`.
- GitHub CLI 2.98.0 instalado somente no projeto e autenticado via chaveiro do macOS.
- Repositório Git local na branch `main`, com identidade configurada somente neste repositório.

As pastas `.tools/` e `.venv/` são locais e ignoradas pelo Git. Homebrew, cliente `psql` no host e uma máquina virtual separada não são necessários: o Docker já fornece o PostgreSQL e sua própria VM Linux interna.

## Operação diária

```bash
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python scripts/migrate.py
.venv/bin/legal-monitor doctor
.venv/bin/legal-monitor scheduler-heartbeat
.venv/bin/legal-monitor scheduler-health
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

Para encerrar os contêineres sem apagar os dados do banco:

```bash
docker compose stop
```

## Não instalar agora

- Selenium;
- Redis ou Celery;
- máquina virtual separada;
- Playwright, navegadores e perfis persistentes antes do marco M4;
- ferramentas de quebra de CAPTCHA ou automação de 2FA;
- automação de WhatsApp Web.

## Portão para integrações reais

Manter `M0_APPROVED=false`, `REAL_CONNECTORS_ENABLED=false` e `WHATSAPP_ENABLED=false` até o checklist M0 ser aprovado. Nenhum processo, credencial, e-mail ou telefone real deve entrar no GitHub.
