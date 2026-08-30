# Runbook - preparação do ambiente local

1. Confirmar FileVault ativo, conta dedicada sem privilégio administrativo diário e bloqueio automático.
2. Instalar Python 3.12 e PostgreSQL 17, nativamente ou por contêiner.
3. Criar `.env` a partir de `.env.example`, com permissões `600` e segredo de banco exclusivo.
4. Manter `M0_APPROVED=false`, `REAL_CONNECTORS_ENABLED=false` e `WHATSAPP_ENABLED=false` durante a fundação.
5. Executar `legal-monitor doctor`, testes e migrações.
6. Confirmar que `browser_profiles`, `storage`, `logs` e `.env` não aparecem no Git.
7. Configurar backup somente após definir destino, criptografia, RPO, RTO e responsável.

Não instalar Selenium. Não expor PostgreSQL ou painel na rede pública. Não usar número processual, documento, e-mail ou telefone real nos testes.
