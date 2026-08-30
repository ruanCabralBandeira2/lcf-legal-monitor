# ADR-001 - Fundação local, modular e sem integrações reais

- Status: aceito para M0-M1
- Data: 2026-08-30

## Contexto

A especificação prevê uma carteira pequena, execução no Mac mini M4, PostgreSQL como agenda e persistência, Playwright apenas no último quilômetro e estados explícitos para qualquer incerteza. O ambiente inicial está vazio e ainda não há processo-piloto, credenciais, provedor oficial de WhatsApp ou políticas aprovadas.

## Decisão

Adotar Python 3.12, módulos de domínio independentes, migrações SQL explícitas e Psycopg 3. Os conectores seguem um contrato comum e começam por um fake determinístico. Documentos são validados e armazenados localmente com escrita atômica e SHA-256. Integrações reais são bloqueadas por configuração, com padrão seguro `false`.

PostgreSQL continua sendo o banco de produção e da integração. Testes unitários do domínio usam apenas memória e filesystem temporário; SQLite não será usado como substituto silencioso porque sua semântica de locks e constraints diverge do PostgreSQL.

## Consequências

- O núcleo pode ser testado agora sem dados reais, rede ou tribunal.
- O primeiro conector real só será escolhido após o portão M0.
- A API/admin, scheduler/launchd, heartbeat, router real e outbox entram nos marcos seguintes.
- Docker é uma conveniência, não requisito arquitetural; PostgreSQL nativo também é aceito.

## Segurança

Perfis de navegador, `.env`, documentos, backups e logs operacionais ficam fora do Git. Nenhum código recebe autorização para resolver CAPTCHA, armazenar 2FA ou automatizar WhatsApp Web.
