# Checklist de descoberta e autorização - M0

Nenhum conector real deve ser ativado antes de este checklist ser aprovado por responsáveis técnicos e jurídicos.

## Registro de 28/09/2026

- Autorização da LCF confirmada pelo responsável técnico, com evidência guardada fora do Git. Acesso por conta de advogado e certificado em token USB; o responsável técnico mantém o autenticador de 2FA no próprio celular, com anuência do advogado.
- Sistemas iniciais: eproc TJRJ, eproc TRF2 e PDPJ-Br (ADR-007).
- Entrega inicial: e-mail (teste com endereço pessoal do operador) e pasta no Mac mini. Telefone adiado.
- `M0_APPROVED=true` somente no `.env` local; `REAL_CONNECTORS_ENABLED` continua `false` até o primeiro conector eproc passar nos testes com fixture sanitizada.

## Decisões bloqueantes

- [ ] Processo-piloto e sistema atual (DCP, PJe ou eproc), com ambiente de teste autorizado.
- [x] Autorização da LCF para monitorar, baixar, armazenar e enviar peças (28/09/2026).
- [ ] Até cinco processos-piloto preferencialmente não sigilosos, compartilhados por canal seguro e nunca registrados no Git.
- [x] Operador/autenticador primário: responsável técnico (token USB + 2FA no celular). Substituto pendente.
- [x] Sistemas iniciais e URLs oficiais: eproc TJRJ, eproc TRF2, PDPJ-Br (ADR-007).
- [ ] Base legal, sigilo, perfis de acesso e termos de uso de cada fonte revisados.
- [ ] Termo do DataJud revisado, inclusive restrição não comercial; compatibilidade do uso pretendido aprovada e aceite registrado antes de qualquer consulta.
- [ ] SLA interno de detecção e de ação humana por processo.
- [ ] Movimentos relevantes e aqueles que exigem tentativa de peça.
- [ ] Provedor oficial de WhatsApp, consentimento, canal secundário e política de anexos.
- [ ] Retenção de documentos, logs e auditoria.
- [ ] Destino de backup criptografado, RPO, RTO e responsáveis pelo teste de restauração.
- [ ] Política para resumo: desativado, modelo local ou provedor remoto aprovado.
- [ ] Template do resumo e do campo "o que foi decidido", com citação da peça/páginas, limiar de confiança e revisão humana definidos.
- [ ] Tratamento de dados, contratos de operadores e resposta a incidentes aprovados.

## Prova técnica sem dados jurídicos

- [ ] Webhook divulgado anteriormente revogado no Discord.
- [ ] Canal Discord privado criado e participantes revisados.
- [x] Webhook novo guardado apenas no Keychain; responsável e periodicidade de rotação ainda precisam ser definidos.
- [ ] Retenção do canal e exclusão de anexos/mensagens de teste definida.
- [x] Prova executada em 31/08/2026 somente com mensagem fixa e PDF vazio; o adaptador informou `real_process_data_used=false` e entrega aceita pelo Discord.

Esses itens permitem apenas a prova descrita em `docs/runbooks/DEMO_NOTIFICATION.md`; não aprovam Discord como canal operacional nem liberam conectores reais.

## Inventário do Mac observado em 30/08/2026

- macOS 15.6 em Apple Silicon arm64.
- Python 3.12.13 próprio do projeto, independente do ambiente do Codex.
- Docker Desktop e PostgreSQL 17.11 em contêiner instalados e saudáveis.
- Cliente `psql` disponível dentro do contêiner; instalação duplicada no host dispensada.
- Command Line Tools do Xcode e Git nativo instalados.
- Repositório Git local inicializado na branch `main`.

## Critério de saída

Registrar responsáveis e evidências das aprovações, sem inserir credenciais, número processual real ou contato pessoal no Git. Somente então alterar `REAL_CONNECTORS_ENABLED` em um ambiente local protegido.
