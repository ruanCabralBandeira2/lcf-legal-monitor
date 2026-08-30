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
- testes unitários que não precisam de rede nem de dados reais.

Não há Selenium. Também não há automação de WhatsApp Web, quebra de CAPTCHA, captura de 2FA, cálculo de prazo ou envio ao cliente.

## Preparação local

Requisitos para a operação real: Python 3.12+, PostgreSQL 17 e, em marcos posteriores, Playwright instalado no host. O `compose.yaml` oferece PostgreSQL local quando Docker estiver disponível.

Consulte também o [guia de preparação do Mac](docs/DEVELOPMENT_SETUP.md).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
cp .env.example .env
git config core.hooksPath .githooks
PYTHONPATH=src python -m legal_monitor.cli doctor
PYTHONPATH=src python -m unittest discover -s tests -v
```

Para iniciar o banco com Docker:

```bash
docker compose up -d postgres
PYTHONPATH=src python scripts/migrate.py
```

## Fluxo seguro de desenvolvimento

1. Preencher e aprovar [o checklist M0](docs/M0_CHECKLIST.md).
2. Manter `REAL_CONNECTORS_ENABLED=false` até a aprovação do processo-piloto e dos termos de acesso.
3. Executar `legal-monitor doctor` antes de qualquer serviço.
4. Usar somente fixtures sanitizadas nos testes.
5. Registrar decisões divergentes em `docs/adr/`.

## Limites desta entrega

O repositório não acessa TJRJ, PJe, eproc, DCP, DJEN, e-mail, WhatsApp ou serviços de IA. Isso é intencional: processo-piloto, usuários, SLAs, provedor oficial, retenção, backup e base legal ainda são decisões abertas do M0. O banco também não foi iniciado nesta máquina porque Docker/PostgreSQL não estão instalados no ambiente atual.
