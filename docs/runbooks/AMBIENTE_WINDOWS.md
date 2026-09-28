# Runbook - ambiente de desenvolvimento no Windows

Decisão de 28/09/2026: o produto é construído e validado primeiro no Windows. **Quando tudo funcionar, a operação migra para o Mac mini.** Cada item abaixo indica o equivalente no Mac.

## Pré-requisitos (validados em 28/09/2026, Windows 10 Pro, Ryzen 5 5600G)

| Item | Windows (agora) | Mac mini (futuro) |
|---|---|---|
| Virtualização | SVM ligado no BIOS + `wsl --install --no-distribution` + reinício | nativa |
| PostgreSQL | Docker Desktop (WSL2) + `docker compose up -d postgres` | Docker Desktop |
| Python | 3.12.10 em `%LOCALAPPDATA%\Programs\Python\Python312`, `.venv` no projeto | 3.12 em `.venv` |
| Navegador do robô | Edge (`BROWSER_CHANNEL=msedge`) | Chrome (`BROWSER_CHANNEL=chrome`) |
| Token USB | driver do token registra o certificado no repositório do Windows | middleware do token + Keychain |
| Segredos | Gerenciador de Credenciais do Windows (`keyring`) | Keychain (`keyring`) |
| Agendamento | Agendador de Tarefas do Windows | launchd (`ops/launchd`) |
| Documentos | `storage/documents` local | `storage/documents` + compartilhamento SMB |

## Preparação

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install -e ".[dev,browser]"
docker compose up -d postgres
.venv\Scripts\python scripts\migrate.py
.venv\Scripts\legal-monitor doctor
```

No PowerShell, o alias da Microsoft Store pode esconder o `python` recém-instalado; use o caminho completo ou o `.venv`.

## Testes com PostgreSQL

```bash
set TEST_DATABASE_URL=postgresql://legal_monitor:legal_monitor_dev@127.0.0.1:5432/legal_monitor
.venv\Scripts\python -m pytest
```

O teste de link simbólico é pulado no Windows sem modo desenvolvedor; ele roda no CI e no Mac.

## Cuidados

- `.gitattributes` fixa LF: o checksum das migrações precisa ser igual no Windows e no Mac.
- A primeira inicialização do Docker Desktop leva alguns minutos para configurar o WSL2.
- `.env`, `browser_profiles/` e `storage/` nunca entram no Git.
