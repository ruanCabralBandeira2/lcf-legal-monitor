# Demonstração segura do resumo factual

## Objetivo

Comprovar o formato do resumo e do campo `decisao_resultado` antes de escolher extrator, OCR ou modelo. A demonstração usa texto fixo, fictício e incorporado ao código; não lê PDF, banco, tribunal, Keychain ou rede.

## Executar

Depois de instalar a versão atual do pacote no ambiente local:

```bash
.tools/bin/uv pip install --python .venv/bin/python . --no-deps
.venv/bin/legal-monitor summary-demo
```

Durante o desenvolvimento, também é possível executar diretamente o código da branch:

```bash
PYTHONPATH=src .venv/bin/python -m legal_monitor.cli summary-demo
```

## Resultado esperado

A saída JSON deve informar:

- `safe_demo=true`;
- `network_used=false`;
- `real_process_data_used=false`;
- `decisao_resultado` com página e trecho verificável;
- de três a oito pontos em `resumo_advogado`;
- `review_required=true`;
- `prazo_calculado=false`.

## Limites

- O comando não demonstra leitura de peça real nem interpretação por IA.
- O resultado não é parecer, controle de prazo ou orientação estratégica.
- Todo rascunho automático exige revisão humana.
- Saída sem página/trecho verificável deve virar `UNAVAILABLE`, nunca resumo aparentemente válido.
- `SUMMARY_ENABLED` permanece desativado para o fluxo operacional.
