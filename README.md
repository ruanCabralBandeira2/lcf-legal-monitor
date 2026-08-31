# Robô de Monitoramento Jurídico - LCF Advogados

Base local e auditável para detectar movimentações relevantes, preservar peças processuais e preparar alertas ao advogado responsável. Esta entrega implementa a fundação segura do M0-M1 com dados exclusivamente fictícios.

## O que já funciona

- configuração tipada, com travas para produção e bloqueio do host de homologação do DJEN;
- validação completa do número CNJ (formato e dígitos verificadores);
- contratos de conectores e conector simulado, sem acesso a tribunais;
- pipeline local de PDF com limite de tamanho, validação, SHA-256 e escrita atômica;
- migração PostgreSQL para as entidades essenciais, constraints e idempotência;
- logging JSON com mascaramento de números CNJ;
- CLI de diagnóstico e demonstração segura;
- scheduler PostgreSQL com jobs idempotentes, leases, recuperação e retentativas;
- heartbeat interno e visão separada de saúde da plataforma e atraso dos processos;
- administração local de responsáveis e processos, com número mascarado e auditoria;
- cadastro transacional que cria estado inicial não-verde e primeira verificação;
- testes unitários que não precisam de rede nem de dados reais.

Não há Selenium. Também não há automação de WhatsApp Web, quebra de CAPTCHA, captura de 2FA, cálculo de prazo ou envio ao cliente.

## Preparação local

Este Mac já está preparado com Python 3.12 isolado no projeto, Docker Desktop, Docker Compose e PostgreSQL 17 em contêiner. Em marcos posteriores, a automação de navegador poderá usar Playwright; Selenium não faz parte da arquitetura.

Consulte também o [guia de preparação do Mac](docs/DEVELOPMENT_SETUP.md).

```bash
git config core.hooksPath .githooks
.venv/bin/legal-monitor doctor
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

Para iniciar o banco com Docker:

```bash
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python scripts/migrate.py
.venv/bin/legal-monitor scheduler-heartbeat
.venv/bin/legal-monitor scheduler-health
```

Teste seguro e idempotente do worker, sem acessar fonte externa:

```bash
.venv/bin/legal-monitor scheduler-enqueue-healthcheck --key primeiro-smoke-local
.venv/bin/legal-monitor scheduler-run-once
```

Cadastro administrativo local com dados fictícios:

```bash
.venv/bin/legal-monitor admin-add-lawyer --code adv-demo --name "Advogado Demonstrativo"
.venv/bin/legal-monitor admin-add-process 0000001-69.2026.8.19.0001 --lawyer adv-demo
.venv/bin/legal-monitor admin-list-processes
```

A saída mascara o número CNJ. A desativação é lógica, pausa jobs pendentes e preserva auditoria:

```bash
.venv/bin/legal-monitor admin-deactivate-process 0000001-69.2026.8.19.0001
```

## Fluxo seguro de desenvolvimento

1. Preencher e aprovar [o checklist M0](docs/M0_CHECKLIST.md).
2. Manter `REAL_CONNECTORS_ENABLED=false` até a aprovação do processo-piloto e dos termos de acesso.
3. Executar `legal-monitor doctor` antes de qualquer serviço.
4. Usar somente fixtures sanitizadas nos testes.
5. Registrar decisões divergentes em `docs/adr/`.

## Limites desta entrega

O repositório não acessa TJRJ, PJe, eproc, DCP, DJEN, e-mail, WhatsApp ou serviços de IA. Isso é intencional: processo-piloto, usuários, SLAs, provedor oficial, retenção, backup e base legal ainda são decisões abertas do M0. O PostgreSQL local contém apenas o esquema inicial e dados de desenvolvimento.

O estado completo para retomadas está em [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). A especificação consolidada está versionada em [docs/source](docs/source/especificacao_base_robo_monitoramento_juridico_v4.pdf).
