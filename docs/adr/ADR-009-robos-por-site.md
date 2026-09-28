# ADR-009 - Um robô por site, monitor com histórico e agendas próprias

- Status: aceito; implementado na versão 0.7.0 (validação real por site pendente)
- Data: 2026-09-28

## Contexto

A carteira real da LCF (118 processos CNJ + 1 administrativo) está espalhada por sete sites: eproc JFRJ (61), eproc TJRJ 1º grau (44), PJe TJRJ (5), PJe TRT1 (5), eproc TJRJ 2º grau, eproc TRF2 e eproc TRF4 (1 cada). As sessões têm durações muito diferentes (eproc TJRJ ~10 h; PJe TJRJ ~15 min) e logins diferentes (token + PIN via SSO Jus.br; OAB + senha + 2FA na JFRJ/TRF2). O operador pediu um robô por site "vendo o tempo todo", mantendo login remoto por enquanto.

## Decisão

- **Robô = site do catálogo.** `monitor-run --site <chave>` roda só aquele site; o agendador tem uma tarefa por site (`ops/windows/registrar-robos.ps1`; launchd no Mac).
- **Conectores por família:** `EprocConnector` (um leitor para TJRJ 1g/2g, JFRJ, TRF2, TRF4) e `PjeConnector` (TJRJ; TRT1 a validar).
- **Roteamento:** `J.TR` + origem `0000` (2º grau primeiro) + sequencial TJRJ ≥ 0800000 (PJe primeiro). A descoberta grava `source_key`; `;SITE=` na carteira força o site (processo em recurso com número da vara).
- **Histórico e dedupe:** movimentos gravados com fingerprint e número do evento (eproc). 1ª rodada registra o histórico em silêncio e envia **um resumo** (partes de 40); depois, só novidades com download e e-mail. `--notify-initial` envia um e-mail por processo.
- **Agendas:** eproc de hora em hora com `--no-interactive-login` (sessão caída → um aviso deduplicado → `auth-open`); PJe em janelas fixas (06:00/18:00) com login interativo e PIN remoto.
- **Segurança:** somente leitura; lista de ações do eproc permitida (`acessar_documento*`); documentos de intimação/citação nunca abertos; processos `RESTRICTED` (família, criminal, segredo) recebem só aviso, sem texto nem anexo.
- **Carteira fora do Git:** `storage/carteira/` com apenas números e marcas; importação idempotente (`import-processes`), visão por site (`sites-report`).

## Consequências

- O leitor do eproc foi validado contra página sintética no navegador real; o primeiro uso real de cada site pode exigir ajuste via diagnóstico estrutural.
- Processos em recurso podem ter movimentação em duas instâncias; hoje o robô acompanha uma por processo (a descoberta ou o `SITE=`). Acompanhamento simultâneo das duas fica para depois.
- A sessão da JFRJ/TRF2 ainda não foi medida; se for curta, esses robôs passam para janelas fixas como o PJe.
- O processo administrativo municipal fica fora do robô (acompanhamento manual).
