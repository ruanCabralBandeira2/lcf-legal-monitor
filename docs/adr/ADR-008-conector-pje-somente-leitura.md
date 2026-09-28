# ADR-008 - Conector PJe somente leitura e execução pelo operador

- Status: aceito; primeira versão em 0.7.0 (`legal_monitor.connectors.pje`, comando `fetch-latest`)
- Data: 2026-09-28

## Contexto

O processo-piloto tramita no PJe TJRJ 1º grau. O PJe recusa navegador headless (HTTP 403), então o robô usa janela visível (ADR-007). O agente de desenvolvimento (Claude) é impedido pela política da sessão de abrir autos reais; o robô, executado pelo operador no host, não tem essa restrição.

## Decisão

- **Execução:** o robô roda no computador do escritório, iniciado pelo operador ou pelo agendador. O agente escreve e testa o código com fixtures e diagnósticos **sem conteúdo** (somente tags/ids/classes, números longos mascarados) gerados pelo próprio robô em `storage/tmp/diagnostico/`.
- **Navegação permitida:** consulta processual (`/Processo/ConsultaProcesso/listView.seam`), link do resultado da consulta e links de documento da linha do tempo dos autos.
- **Proibido:** aba "Expedientes" e qualquer controle cujo texto indique escrita ou ciência (`peticion|assinar|ciência|excluir|remover|juntar|protocol|encerrar|sair|expediente`). No PJe, abrir intimação pelos expedientes pode registrar ciência e iniciar prazo.
- **Documento:** download direto quando o clique gera arquivo; senão, o binário do visualizador é obtido pela mesma sessão e aceito apenas se começar com `%PDF-`. Todo arquivo passa pelo `DocumentService` (SHA-256, escrita atômica).
- **Falha de leitura:** gera diagnóstico estrutural e nunca vira sucesso.

## Consequências

- A heurística da linha do tempo (`#divTimeLine`, `.media`) é validada no primeiro uso real; ajustes virão do diagnóstico estrutural.
- A confirmação de que visualizar documentos pela linha do tempo **não** registra ciência deve ser feita com o advogado no primeiro teste.
