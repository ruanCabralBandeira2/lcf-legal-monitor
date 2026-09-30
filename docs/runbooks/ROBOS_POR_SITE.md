# Runbook - robôs por site

Um robô por site do catálogo, cada um com sua agenda (ADR-009). Hoje roda no Windows (Agendador de Tarefas); **no futuro rodará no Mac mini** (launchd), com os mesmos comandos.

## Carteira (28/09/2026)

Carteira exportada do Astrea em `storage/carteira/` (fora do Git): 119 linhas, 118 números CNJ válidos e 1 processo administrativo (Secretaria Municipal de Fazenda), que fica fora do robô.

| Site | Processos | Login | Sessão | Agenda sugerida | Conector |
|---|---:|---|---|---|---|
| `eproc-jfrj-1g` (Justiça Federal RJ) | 61 | OAB + senha + 2FA | a medir | de hora em hora | eproc (validar 1º uso) |
| `eproc-tjrj-1g` | 44 → 0 (não estão no eproc) | token (SSO Jus.br) | ~10 h | de hora em hora | eproc (validado) |
| `tjrj-portal` (processo eletrônico legado do TJRJ) | 44 (numeração antiga) | token (imagem do certificado no IdServerJus) ou usuário/senha | não persiste (login a cada rodada) | janelas com PIN (como o PJe) | em construção: consulta em iframe (`#/consproc/consultaportal`) |
| `pje-tjrj-1g` | 5 | token + PIN | ~15 min | 06:00 e 18:00 | PJe (validado) |
| `pje-trt1-1g` (Trabalho) | 5 | login próprio | a medir | 06:20 e 18:20 | PJe (validar) |
| `eproc-tjrj-2g` | 1 | token (SSO Jus.br) | ~10 h | de hora em hora | eproc |
| `eproc-trf2` | 1 | OAB + senha + 2FA | a medir | de hora em hora | eproc |
| `eproc-trf4-2g` | 1 | token (SSO Jus.br); cadastro no TRF4 | a medir | de hora em hora | eproc |

Os números acima são o **site provável**; a primeira rodada confirma e grava onde cada processo está (`sites-report`). Processos antigos do TJRJ que não estiverem no eproc serão procurados no PJe; se não aparecerem em nenhum, ficam listados como pendentes.

## Primeira vez (validar cada site antes de agendar)

```bash
.venv\Scripts\legal-monitor import-processes storage\carteira\astrea-2026-09-28.txt --lawyer titular-lcf
.venv\Scripts\legal-monitor sites-report
.venv\Scripts\legal-monitor auth-open eproc-tjrj-1g
.venv\Scripts\legal-monitor monitor-run --site eproc-tjrj-1g
.venv\Scripts\legal-monitor sites-report
```

A 1ª rodada de cada processo registra o histórico em silêncio e manda **um resumo** por e-mail (em partes de 40 processos). Se a página não for reconhecida, o robô grava em `storage/tmp/diagnostico/` só a estrutura (sem conteúdo); envie esse arquivo para ajuste.

## Agendar

```bash
powershell -ExecutionPolicy Bypass -File ops\windows\registrar-robos.ps1
```

- eproc: de hora em hora com `--no-interactive-login`. Sessão caída gera um e-mail "login necessário"; rode `auth-open <site>`.
- PJe: 06:00 e 18:00 com login interativo; o e-mail "aprove/digite o PIN" chega e o operador digita o PIN remotamente.
- Logs em `logs\robo-<site>.log` (saída do agendador) e `logs\monitor-<site>-<data>.json` (resultado de cada rodada, números mascarados). Remover: `registrar-robos.ps1 -Remover`.
- As tarefas rodam ocultas (`executar-oculto.vbs`): fechar uma janela de console mataria o robô. Depois de atualizar o projeto, rode o script de registro de novo.
- Os robôs agendados executam esta mesma cópia do projeto: durante o desenvolvimento, mudanças de código e banco valem já na rodada seguinte.

## Regras que os robôs seguem

- Somente leitura; nunca abrem a aba Expedientes nem documentos de intimação/citação (risco de ciência).
- Processos `RESTRICTED` (família, criminal, segredo): e-mail só avisa, sem texto nem anexo.
- Processo em recurso com número da vara: marque `;SITE=<tribunal>` na carteira (ex.: `eproc-trf2`).
