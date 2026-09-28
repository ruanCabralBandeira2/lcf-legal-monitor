# Runbook - autenticação, 2FA e CAPTCHA

1. Marcar o job como `AUTH_REQUIRED` ou `CAPTCHA_REQUIRED`; nunca como sucesso.
2. Abrir `manual_action` com conector, processo referenciado internamente e `correlation_id`, sem registrar código 2FA.
3. Alertar apenas o operador autorizado para abrir a sessão local legítima.
4. O operador autentica ou resolve o desafio diretamente na interface oficial.
5. O conector executa `check_session`; somente uma confirmação real permite retomar.
6. Registrar resolução e evidência sanitizada na auditoria.

## Login por token USB com aprovação no celular (ADR-007)

1. Conectar o token USB no Mac mini.
2. Rodar `legal-monitor auth-open eproc-tjrj-1g` (ou `eproc-trf2`, `pdpj`).
3. Na janela do Chrome, escolher o certificado e digitar o PIN, se o sistema pedir.
4. Se a tela parar pedindo 2FA, o operador recebe o e-mail "Aprove o login no celular" e aprova no aplicativo autenticador.
5. O comando termina sozinho quando a sessão fica válida e resolve a ação manual aberta.
6. Para testar sem janela: `legal-monitor auth-check --notify`.

eproc TJRJ e PDPJ compartilham o login Jus.br; TRF2 tem login separado.

É proibido usar serviço de quebra, OCR para contorno, técnica antifingerprint, extensão evasiva, solicitação de 2FA por WhatsApp ou armazenamento do código.
