# Prova segura de notificação no Discord

Este procedimento envia somente uma mensagem técnica fixa. Não use processo, cliente, peça, credencial ou outro dado real nesta fase.

## Preparar o canal

1. Crie um servidor ou canal privado no Discord, acessível apenas às pessoas autorizadas para a prova.
2. Nas integrações do canal, crie um webhook chamado `LCF Legal Monitor - Demo`.
3. Copie a URL do webhook, mas não a envie por chat, e-mail, issue ou commit.
4. Confirme a política de retenção e remova pessoas que não precisem participar do teste.

Não é necessário criar um bot Discord: um incoming webhook é suficiente para o envio unidirecional.

## Guardar o segredo localmente

Crie o `.env` a partir do exemplo se ele ainda não existir e restrinja sua leitura:

```bash
cp .env.example .env
chmod 600 .env
```

Edite somente o `.env` local:

```dotenv
DISCORD_DEMO_ENABLED=true
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/ID/TOKEN
```

O `.env` está ignorado pelo Git. Se a URL aparecer em uma captura, log ou conversa, apague/regere o webhook no Discord imediatamente.

## Executar a prova

Primeiro valide a configuração e a fatia inteiramente local:

```bash
.venv/bin/legal-monitor doctor
.venv/bin/legal-monitor demo
```

Depois envie a fixture fixa:

```bash
.venv/bin/legal-monitor notification-demo-discord
```

A saída deve indicar `demo_only=true`, `real_process_data_used=false` e o identificador retornado pelo Discord. O conteúdo da mensagem declara explicitamente que não contém dado processual real.

## Encerrar ou evoluir

Para encerrar a prova, desative `DISCORD_DEMO_ENABLED`, remova o segredo local e exclua/regere o webhook. Não reutilize este adaptador para mensagens jurídicas reais. A escolha do canal operacional, consentimentos, dados permitidos, retenção, outbox e contingência continua sendo uma decisão do M0/M8.
