# Checklist de descoberta e autorização - M0

Nenhum conector real deve ser ativado antes de este checklist ser aprovado por responsáveis técnicos e jurídicos.

## Decisões bloqueantes

- [ ] Processo-piloto e sistema atual (DCP, PJe ou eproc), com ambiente de teste autorizado.
- [ ] Usuário técnico, operador/autenticador primário e substituto.
- [ ] Base legal, sigilo, perfis de acesso e termos de uso de cada fonte revisados.
- [ ] SLA interno de detecção e de ação humana por processo.
- [ ] Movimentos relevantes e aqueles que exigem tentativa de peça.
- [ ] Provedor oficial de WhatsApp, consentimento, canal secundário e política de anexos.
- [ ] Retenção de documentos, logs e auditoria.
- [ ] Destino de backup criptografado, RPO, RTO e responsáveis pelo teste de restauração.
- [ ] Política para resumo: desativado, modelo local ou provedor remoto aprovado.
- [ ] Tratamento de dados, contratos de operadores e resposta a incidentes aprovados.

## Inventário do Mac observado em 30/08/2026

- macOS 15.6 em Apple Silicon arm64.
- Runtime Python 3.12 disponível pelo ambiente do Codex.
- Docker, `psql` e PostgreSQL não encontrados.
- Ferramentas de linha de comando do Xcode não instaladas; o Git do runtime do Codex está disponível.
- Nenhum repositório ou código anterior encontrado na pasta do projeto.

## Critério de saída

Registrar responsáveis e evidências das aprovações, sem inserir credenciais, número processual real ou contato pessoal no Git. Somente então alterar `REAL_CONNECTORS_ENABLED` em um ambiente local protegido.
