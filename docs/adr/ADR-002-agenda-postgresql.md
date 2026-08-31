# ADR-002 - PostgreSQL como agenda e lease transacional

- Status: aceito para M2
- Data: 2026-08-30

## Contexto

A carteira inicial é pequena e a especificação determina PostgreSQL como fila, sem Redis/Celery no MVP. O worker precisa evitar processamento duplicado, sobreviver a encerramento abrupto e distinguir falha recuperável de bloqueio humano.

## Decisão

Usar a tabela `job` como agenda. A aquisição ocorre por tipos que o worker possui capacidade de executar, em transação com `FOR UPDATE SKIP LOCKED`, incrementa a tentativa, grava `lease_owner`/`lease_until` e cria `job_attempt`. A conclusão exige o mesmo job, dono e número de tentativa, com lease ainda válido.

Jobs expirados podem ser recuperados por outro worker; a tentativa anterior recebe `LEASE_EXPIRED`. A chave SHA-256 de idempotência evita agenda duplicada. Falhas transitórias usam backoff exponencial com jitter determinístico e limite. CAPTCHA, 2FA, divergência, migração e ausência de handler pausam o job para ação humana/configuração.

Heartbeat do worker fica em tabela própria. A saúde da plataforma não substitui `last_success_at` nem o atraso individual de processos.

## Consequências

- Não há infraestrutura Redis/Celery adicional.
- Concorrência e recuperação dependem da semântica real do PostgreSQL e possuem testes de integração.
- Um worker lento não pode concluir depois que outro adquiriu o job.
- O provedor de heartbeat externo continua bloqueado até decisão do M0; a ausência permanece visível.
