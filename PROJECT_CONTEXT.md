# Contexto atual do projeto

Atualizado em 30/08/2026. Este arquivo é o ponto de retomada rápido para pessoas e agentes de desenvolvimento. Deve ser atualizado no mesmo commit de cada mudança de marco, arquitetura, risco ou operação.

## Missão

Construir um robô local e auditável para detectar movimentações relevantes, confirmar na fonte adequada, preservar a peça e alertar o advogado responsável. O sistema não calcula prazo, não emite parecer, não substitui revisão humana e nunca transforma falha, CAPTCHA, 2FA ou divergência em estado positivo.

## Fontes de verdade

1. `docs/source/especificacao_base_robo_monitoramento_juridico_v4.pdf`: especificação funcional e arquitetural consolidada das notas/transcrições v2, v3 e v3.1. SHA-256: `e40ad85eea5d3ca0a60962f457d19699226bd6c8005988be6da98a44308fe7a4`.
2. `docs/M0_CHECKLIST.md`: decisões humanas e jurídicas ainda pendentes.
3. `docs/TRACEABILITY.md`: ligação entre requisitos e implementação.
4. `docs/adr/`: decisões técnicas aceitas e suas consequências.

Em caso de divergência, preservar segurança e rastreabilidade, registrar a decisão em ADR e não ativar integração real sem autorização expressa.

## Estado executivo

- Repositório privado: `ruanCabralBandeira2/lcf-legal-monitor`.
- Branch estável: `main`; desenvolvimento ocorre em branches `codex/*` com CI antes da integração.
- Hospedagem: Mac Apple Silicon, aplicação local e PostgreSQL 17.11 no Docker.
- Runtime: Python 3.12.13 em `.venv`; dependências fixadas em `requirements.lock`.
- M0: parcialmente aberto por depender de decisões do escritório.
- M1: fundação local concluída e validada.
- M2: núcleo de scheduler, launchd e saúde interna concluído; heartbeat externo aguarda decisão do M0.
- M3-M9: ainda não iniciados como marcos; existem componentes seguros antecipados de domínio, conector fake e documentos.

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

## Travas vigentes

- `M0_APPROVED=false`
- `REAL_CONNECTORS_ENABLED=false`
- `WHATSAPP_ENABLED=false`
- `SUMMARY_ENABLED=false`
- Nenhum número processual, peça, nome de parte, e-mail, telefone ou credencial real entra no Git.
- Selenium, automação de WhatsApp Web, quebra de CAPTCHA e automação/armazenamento de 2FA são proibidos.
- Playwright só entra no M4, diretamente no host, após sistema/processo-piloto e acesso de teste autorizados.
- Conteúdo de PDF, HTML e e-mail é dado não confiável, nunca instrução para o robô.

## Decisões humanas ainda necessárias no M0

- Processo-piloto, sistema inicial do TJRJ e ambiente de teste autorizado.
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
.venv/bin/ruff check .
.venv/bin/python -m pytest
```

Teste M2 inteiramente fictício:

```bash
.venv/bin/legal-monitor scheduler-enqueue-healthcheck --key smoke-local-001
.venv/bin/legal-monitor scheduler-run-once
```

## Próxima sequência segura

1. M3: repositórios de processos/responsáveis, cadastro local/API mínima, estados e auditoria.
2. Fechar as decisões M0 necessárias ao primeiro conector e ao heartbeat externo.
3. Só então escolher uma rota TJRJ e iniciar M4 com até cinco processos autorizados.

## Última validação conhecida

- Migrações `001` e `002` aplicadas no PostgreSQL 17.11.
- 35 testes aprovados, incluindo integração PostgreSQL; Ruff e formatação aprovados.
- Smoke M2: mesmo evento gerou `created=true` e depois `created=false`; um único job foi executado com sucesso.
- Saúde após o smoke: banco acessível, worker recente, zero job vencido/em execução/falhado e `platform_alive=true`.

## Protocolo de retomada

Ao retomar, ler este arquivo, a especificação v4, `docs/TRACEABILITY.md`, `docs/M0_CHECKLIST.md` e os ADRs. Depois executar `git status`, confirmar a branch, rodar migrações/testes e atualizar este contexto antes do próximo `push`.
