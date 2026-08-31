# ADR-004 - Prova de notificação isolada por webhook Discord

- Status: aceito para demonstração técnica
- Data: 2026-08-31

## Contexto

O escritório precisa comprovar que o fluxo de alerta funciona antes de receber acesso autenticado aos sistemas judiciais. O núcleo já produz uma movimentação e um PDF exclusivamente fictícios, mas ainda não havia uma saída de notificação testável. WhatsApp exige uma integração oficial e decisões do M0; um bot Discord completo acrescentaria OAuth, comandos e uma conexão persistente sem necessidade para uma prova unidirecional.

## Decisão

Adicionar um contrato mínimo de notificação, um provedor fake em memória e um adaptador de webhook Discord restrito a uma mensagem fixa de demonstração. O webhook:

- fica desativado por padrão e é proibido em `APP_ENV=production`;
- aceita somente mensagens marcadas como demonstração;
- não recebe texto livre, número processual, nome, documento ou anexo pela CLI;
- exige URL HTTPS no domínio oficial `discord.com`;
- desabilita menções e pede confirmação da mensagem criada;
- nunca inclui a URL/token em saída ou erro;
- lê o segredo somente do Keychain do macOS;
- envia, na prova, apenas um PDF vazio gerado localmente e limitado a 10 MiB;
- considera comprometido e exige rotação de qualquer webhook divulgado em chat, issue, captura ou log.

O adaptador não se conecta ao outbox de produção e não significa aprovação do Discord como canal jurídico. WhatsApp continuará limitado à API oficial/provedor aprovado, sem WhatsApp Web. A API Pública do DataJud é candidata a uma futura prova com metadados públicos, mas qualquer consumo permanece bloqueado até revisão e aceitação expressa do termo de uso do CNJ.

## Consequências

- A fatia fictícia local agora demonstra também a geração de um alerta pelo provedor fake.
- Quando o usuário recriar um canal privado e guardar o webhook no Keychain, uma mensagem técnica fixa com PDF fictício poderá comprovar a entrega externa sem expor dados jurídicos.
- Respostas a comandos, anexos, preferências de destinatário, retries, outbox e recibos entram no marco de notificações posterior.
- Uma entrega no Discord não comprova acesso ao PJe nem atualidade do DataJud; comprova apenas o trecho de notificação.
