# Prova segura de notificação no Discord

Este procedimento envia somente uma mensagem técnica fixa e um PDF vazio gerado pelo próprio projeto. Não use processo, cliente, peça, credencial ou outro dado real nesta fase.

## 1. Revogar qualquer webhook exposto

Uma URL de webhook contém um token de envio. Se ela apareceu em chat, issue, captura, e-mail ou log, trate-a como comprometida:

1. Abra as integrações do canal no Discord.
2. Exclua o webhook divulgado.
3. Crie um webhook novo chamado `LCF Legal Monitor - Demo`.
4. Não copie o novo link para conversas ou arquivos do projeto.

Use um servidor/canal privado, acessível apenas às pessoas autorizadas para a prova. Não é necessário criar um bot Discord: um incoming webhook é suficiente para o envio unidirecional.

## 2. Guardar o novo segredo no Keychain

No Terminal local, execute o comando abaixo. A opção `-w` no final fará o macOS pedir o valor de forma interativa, sem gravá-lo no histórico do shell:

```bash
security add-generic-password \
  -U \
  -a local-monitor \
  -s com.lcf.legal-monitor.discord.webhook \
  -w
```

Cole o webhook novo somente no prompt do Keychain. Não use `DISCORD_WEBHOOK_URL` no `.env`.

Para confirmar que o item existe sem revelar o segredo:

```bash
security find-generic-password \
  -a local-monitor \
  -s com.lcf.legal-monitor.discord.webhook
```

## 3. Ativar somente a prova

No `.env` local, mantenha os identificadores e ative a demonstração:

```dotenv
DISCORD_DEMO_ENABLED=true
DISCORD_WEBHOOK_KEYCHAIN_SERVICE=com.lcf.legal-monitor.discord.webhook
DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT=local-monitor
```

O `.env` não contém o webhook e permanece ignorado pelo Git.

## 4. Executar

Primeiro valide a configuração e a fatia inteiramente local:

```bash
.venv/bin/legal-monitor doctor
.venv/bin/legal-monitor demo
```

Depois envie a fixture fixa e o PDF vazio:

```bash
.venv/bin/legal-monitor notification-demo-discord
```

A saída deve indicar `demo_only=true`, `real_process_data_used=false`, o nome `prova_ficticia.pdf` e o identificador retornado pelo Discord. O adaptador valida assinatura PDF e limita o anexo a 10 MiB, que é o limite padrão documentado pelo Discord em 31/08/2026.

## 5. Encerrar ou girar o segredo

Desative `DISCORD_DEMO_ENABLED`. Para remover o item do Keychain:

```bash
security delete-generic-password \
  -a local-monitor \
  -s com.lcf.legal-monitor.discord.webhook
```

Não reutilize este adaptador de demonstração para mensagens jurídicas reais. Participantes, retenção, política de anexos, outbox, idempotência, contingência e base jurídica continuam sendo decisões do M0/M8.

Referências oficiais:

- https://docs.discord.com/developers/platform/webhooks
- https://docs.discord.com/developers/resources/webhook
- https://docs.discord.com/developers/reference#uploading-files
