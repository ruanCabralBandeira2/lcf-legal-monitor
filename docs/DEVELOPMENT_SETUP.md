# Preparação do Mac para desenvolvimento

## Situação atual

- GitHub conectado ao Codex e identidade Git configurada somente neste repositório.
- Repositório Git local na branch `main`, ainda sem remoto.
- Ambiente Python isolado `.venv` pronto e ignorado pelo Git.
- Docker, PostgreSQL, GitHub CLI, Homebrew e Command Line Tools do Xcode ainda não estão disponíveis no host.

## Instalação mínima recomendada

1. **Command Line Tools do Xcode** - fornece o Git e a cadeia de compilação nativos do macOS. Instalar com `xcode-select --install` e concluir a janela do sistema.
2. **Docker Desktop para Apple Silicon** - fornece Docker Engine, CLI, Compose e a VM Linux interna. Não instalar uma VM separada.
3. **Python 3.12 estável no host** - necessário para o serviço rodar fora da sessão do Codex. Pode ser instalado pelo pacote oficial do Python ou por Homebrew.
4. **GitHub CLI (`gh`)** - opcional, mas recomendado para autenticar o Git do terminal, criar o repositório remoto e fazer `push` sem armazenar token manualmente.

O PostgreSQL não precisa ser instalado separadamente se o `compose.yaml` for usado. O contêiner já está fixado em PostgreSQL 17.11 e só publica a porta em `127.0.0.1`.

## Não instalar agora

- Selenium;
- Redis ou Celery;
- máquina virtual separada;
- Playwright, navegadores e perfis persistentes antes do marco M4;
- ferramentas de quebra de CAPTCHA ou automação de 2FA;
- automação de WhatsApp Web.

## Ordem de ativação após as instalações

```bash
docker compose up -d postgres
PYTHONPATH=src .venv/bin/python scripts/migrate.py
.venv/bin/legal-monitor doctor
.venv/bin/python -m pytest
```

Para o GitHub no terminal, instalar `gh`, executar `gh auth login` e selecionar HTTPS. Depois criar ou vincular um repositório **privado** por padrão e adicionar o remoto `origin`.

## Portão para integrações reais

Manter `M0_APPROVED=false`, `REAL_CONNECTORS_ENABLED=false` e `WHATSAPP_ENABLED=false` até o checklist M0 ser aprovado. Nenhum processo, credencial, e-mail ou telefone real deve entrar no GitHub.
