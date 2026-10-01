# Runbook - migração Windows → Mac mini e retomada

Preparado em 30/09/2026. Até aqui o robô foi construído e validado no Windows (ver `AMBIENTE_WINDOWS.md`). A partir deste ponto a operação e o desenvolvimento continuam no **Mac mini**, onde ficará o token USB.

**Para retomar numa nova sessão do Claude no Mac:** abra o Claude Code na pasta do projeto e peça: *"Leia AGENTS.md, PROJECT_CONTEXT.md e docs/runbooks/MIGRACAO_MAC.md e continue de onde paramos."* Não é preciso levar a conversa anterior: todo o contexto necessário está no repositório. (Se exportar a conversa, guarde-a em local privado: ela contém nomes e números reais da carteira.)

## 1. No Windows, antes de desligar

1. Enviar o código ao GitHub (pede login do GitHub no navegador):

   ```bash
   git push -u origin claude/m4-rota-email-sessao
   ```

2. Copiar para o Mac **por canal privado** (pen drive, AirDrop ou cabo — nunca Git, e-mail ou chat):
   - `.env` (configuração local; no Mac, trocar `BROWSER_CHANNEL=msedge` por `BROWSER_CHANNEL=chrome`);
   - `storage/carteira/astrea-2026-09-28.txt` (carteira: só números e marcas);
   - `storage/backups/legal_monitor-2026-09-30.dump` (banco: processos cadastrados, históricos já lidos, procuras por site);
   - opcional: `storage/documents/` (PDFs já baixados).
   - **Não copiar** `browser_profiles/` (sessões do advogado): no Mac, fazer login de novo com o token.
3. Depois que o Mac estiver rodando, **remover os robôs do Windows** para não haver rodadas e e-mails em dobro:

   ```bash
   powershell -ExecutionPolicy Bypass -File ops\windows\registrar-robos.ps1 -Remover
   ```

## 2. Preparar o Mac mini

Pré-requisitos: Command Line Tools/Git, Python 3.12, **Docker Desktop** (com "Start Docker Desktop when you sign in" **ligado** — no Windows o Docker não voltou após reiniciar e as rodadas falharam por 2 dias), **Google Chrome**, driver/middleware do token USB para macOS (o certificado deve aparecer no Acesso às Chaves), Compartilhamento de Tela ligado (para digitar o PIN remotamente).

```bash
git clone https://github.com/ruanCabralBandeira2/lcf-legal-monitor.git
cd lcf-legal-monitor
git checkout claude/m4-rota-email-sessao
git config core.hooksPath .githooks
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e ".[dev,browser]"
```

Colocar nos mesmos caminhos os arquivos copiados (`.env`, `storage/carteira/…`, `storage/backups/…`). Banco — restaurar **antes** de migrar:

```bash
docker compose up -d postgres
docker exec -i lcf-legal-monitor-postgres-1 pg_restore -U legal_monitor -d legal_monitor --clean --if-exists < storage/backups/legal_monitor-2026-09-30.dump
PYTHONPATH=src .venv/bin/python scripts/migrate.py
.venv/bin/legal-monitor doctor
.venv/bin/legal-monitor sites-report
```

E-mail (a senha de app vai para o Keychain; digitada pela pessoa, sem eco):

```bash
.venv/bin/legal-monitor secret-set smtp
.venv/bin/legal-monitor email-test
```

Testes (os de navegador usam Edge e são pulados no Mac até ajustarmos o canal):

```bash
TEST_DATABASE_URL=postgresql://legal_monitor:legal_monitor_dev@127.0.0.1:5432/legal_monitor .venv/bin/python -m pytest
```

### Estado no Mac (30/09/2026)

- Projeto em `~/lcf-legal-monitor`, branch `claude/m4-rota-email-sessao`, hooks ativos. Python 3.12.13 dentro do projeto (`.tools/python/`, fora do Git) e `.venv` criado a partir dele em 01/10/2026; antes o ambiente dependia de `~/Documents/ChatGPT/LCF ADVOGADOS/.tools`. Reserva do ambiente antigo: `.venv-antigo`.
- `.env` (com `BROWSER_CHANNEL=chrome`), carteira e dump copiados; banco restaurado (118 processos, migrações 001-006) e `sites-report` ok.
- Testes PostgreSQL rodam num banco separado `legal_monitor_test` (nunca no banco operacional):
  `TEST_DATABASE_URL=postgresql://legal_monitor:legal_monitor_dev@127.0.0.1:5432/legal_monitor_test .venv/bin/python -m pytest` - todos aprovados; Ruff ok.
- Um container antigo de demonstração (`lcfadvogados-postgres-1`, de `~/Documents/ChatGPT/LCF ADVOGADOS`, só dados fictícios de agosto) foi parado e teve o reinício automático desligado; o volume foi preservado.
- Faltam (ação humana): instalar Google Chrome; instalar o middleware do token G&D StarSign CUT S (`security list-smartcards` ainda não enxerga o cartão); ligar "Start Docker Desktop when you sign in"; `secret-set smtp` + `email-test`; remover os robôs do Windows; logins da seção 3.

## 3. Logins no Mac (token USB no Mac; PIN e 2FA sempre humanos)

```bash
.venv/bin/legal-monitor auth-open eproc-tjrj-1g   # token; vale também para eproc 2g, PDPJ e TRF4 (SSO Jus.br)
.venv/bin/legal-monitor auth-open eproc-trf2      # OAB + senha + 2FA
.venv/bin/legal-monitor auth-open eproc-jfrj-1g   # OAB + senha + 2FA (pendente desde 29/09)
.venv/bin/legal-monitor auth-open pje-trt1-1g     # token (SSO Jus.br), janela visível
```

PJe TJRJ e Portal de Serviços do TJRJ **não guardam sessão**: o login acontece dentro de cada rodada (`monitor-run --site pje-tjrj-1g` abre o login e pede o PIN).

## 4. Onde paramos (pendências em ordem de prioridade)

1. **Portal de Serviços do TJRJ (44)** — **feito em 30/09/2026** (ADR-010): 44/44 lidos. Peça real validada (`fetch-latest ... --com-peca --operador`). Falta decidir a seleção automática do certificado (`AutoSelectCertificateForUrls`) para rodar sem ninguém.
2. **TRF2 (1 processo)** — o robô grava 50 eventos (1 a 50, último em 08/07/2020). Perguntar ao operador qual é o último evento no eproc do TRF2. Se houver mais de 50, o carregamento sob demanda (`#carregarNovosEventos`) não está sendo disparado pela rolagem.
3. **PJe TJRJ (5)** — 3 com histórico. Os outros 2 mostram o aviso da Resolução CNJ "advogado não faz parte": o robô recusa; o operador pediu para ignorá-los por enquanto (habilitar o advogado ou desativar com `admin-deactivate-process`).
4. **JFRJ (61)** — login OAB + senha + 2FA do titular e depois `monitor-run --site eproc-jfrj-1g`.
5. **TRT1 (5)** — PJe-KZ (Angular), SSO Jus.br, exige janela visível; a tela antiga de consulta cai em `error.seam`: construir conector próprio do PJe-KZ.
6. **TRF4 (1)** — titular sem cadastro no eproc do TRF4 ("Invalid user"): credenciamento ou outro advogado.
7. **Agravo do TJRJ 2º grau** — não está no eproc 2g: próximo candidato Portal/PJe 2g.
8. **Agendamento no Mac** — `ops/launchd/registrar-robos.sh` (LaunchAgents por site, mesma agenda do Windows, mais `caffeinate` para o Mac não suspender). `--so-acordado` registra só o anti-suspensão; `--remover` remove tudo; `LCF_TESTE=<pasta>` só gera e valida os `.plist`. Registrar **depois** de remover os robôs do Windows e fazer os logins.
9. Depois: Discord/telefone, abrir PR do branch para `main` após validação.

## 5. Regras que não mudam

- O robô nunca digita PIN, senha ou código 2FA; a pessoa faz (no Mac, por Compartilhamento de Tela quando remoto).
- O agente (Claude) não abre autos reais: o operador executa o robô e o agente lê resultados mascarados e diagnósticos só de estrutura (ADR-008).
- Números processuais reais nunca entram no Git; testes usam números fictícios.
- Somente leitura: nunca petição, expedientes, ciência, lembretes, renúncia, habilitação, "marcar como lido".
- Atualizar `PROJECT_CONTEXT.md` e `docs/TRACEABILITY.md` a cada mudança relevante.
