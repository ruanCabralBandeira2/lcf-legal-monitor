# Runbook - canal e-mail

## Configurar (Windows ou Mac)

1. Na conta Google remetente, ative a verificação em duas etapas e crie uma **senha de app** em https://myaccount.google.com/apppasswords (nome sugerido: `lcf-legal-monitor`).
2. No `.env` local: `EMAIL_ENABLED=true`, `SMTP_USERNAME`, `EMAIL_FROM`, `EMAIL_OPERATOR_TO` e `EMAIL_LAWYER_TO`.
3. Grave a senha de app no cofre do sistema, digitando sem eco:

   ```bash
   legal-monitor secret-set smtp
   ```

4. Teste com PDF em branco, sem dado processual:

   ```bash
   legal-monitor email-test --to operator
   ```

## Regras

- A senha nunca vai para `.env`, Git, chat ou log.
- Operador recebe avisos de login/2FA; advogado recebe movimentações e peças.
- Anexos só PDF validado, até 20 MiB no total; acima disso o e-mail aponta a pasta no Mac mini.
- Envio aceito pelo SMTP não é ciência jurídica nem confirmação de leitura.
