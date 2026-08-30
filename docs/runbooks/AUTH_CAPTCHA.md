# Runbook - autenticação, 2FA e CAPTCHA

1. Marcar o job como `AUTH_REQUIRED` ou `CAPTCHA_REQUIRED`; nunca como sucesso.
2. Abrir `manual_action` com conector, processo referenciado internamente e `correlation_id`, sem registrar código 2FA.
3. Alertar apenas o operador autorizado para abrir a sessão local legítima.
4. O operador autentica ou resolve o desafio diretamente na interface oficial.
5. O conector executa `check_session`; somente uma confirmação real permite retomar.
6. Registrar resolução e evidência sanitizada na auditoria.

É proibido usar serviço de quebra, OCR para contorno, técnica antifingerprint, extensão evasiva, solicitação de 2FA por WhatsApp ou armazenamento do código.
