# ADR-003 - Administração local e cadastro transacional

- Status: aceito para M3
- Data: 2026-08-31

## Contexto

O M3 exige responsáveis, processos, estados, auditoria e uma interface administrativa mínima. Ainda não há decisão sobre autenticação de painel, exposição de porta ou acesso remoto. Um processo novo também não pode parecer saudável antes da primeira consulta real.

## Decisão

Começar por CLI local, sem servidor HTTP. Responsáveis usam `reference_code` estável; o nome de exibição pode ser alterado futuramente sem quebrar referências. O cadastro aceita apenas CNJ válido do TJRJ nesta fase.

Processo, histórico de sistema `UNKNOWN`, monitor `PENDING_INITIAL_CHECK`, job `MONITOR_PROCESS` e auditoria são gravados na mesma transação. Repetir o cadastro é idempotente. Mudança de responsável e reativação exigem operações explícitas; não há alteração silenciosa.

A listagem padrão mascara o CNJ. Desativar é exclusão lógica, encerra a origem atual, muda o monitor para `DISABLED`, pausa jobs e mantém histórico/auditoria.

## Consequências

- O M3 pode ser demonstrado sem rede, tribunal ou dados pessoais no Git.
- Falha intermediária reverte todo o cadastro, evitando processo sem agenda ou auditoria.
- Painel/API em rede só será criado após decisão sobre autenticação local e superfície de exposição.
- O primeiro job de monitoramento permanece pendente até existir handler autorizado no M4; não vira sucesso fictício.
