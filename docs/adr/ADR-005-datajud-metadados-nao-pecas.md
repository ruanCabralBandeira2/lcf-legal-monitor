# ADR-005 - DataJud como fonte de metadados, não de peças

- Status: aceito como desenho; consumo real bloqueado pelo M0
- Data: 2026-08-31

## Contexto

Foi solicitada a avaliação da API Pública do DataJud para acompanhar movimentações e obter peças a serem entregues ao advogado. A documentação oficial consultada em 31/08/2026 descreve a API como Beta e pública para metadados de processos não sigilosos. O endpoint do TJRJ é separado por alias e a consulta usa Elasticsearch Query DSL com chave pública publicada pelo CNJ.

O glossário oficial enumera capa, grau, sigilo, sistema, classe, assuntos, órgão julgador e movimentos. Ele não contém documento, conteúdo, PDF, anexo, identificador de peça ou URL de download. O exemplo oficial de resposta também retorna somente esses metadados.

## Decisão

Não implementar o DataJud como `fetch_document` nem prometer download de peças por essa API. Após revisão jurídica, confirmação documentada de que o uso pretendido é compatível com a restrição não comercial e aceite expresso do termo, ele poderá ser um sinal auxiliar para:

- localizar processo público pelo número CNJ;
- identificar o sistema processual informado pelo tribunal;
- comparar códigos, nomes e datas de movimentações;
- priorizar um job de confirmação na fonte adequada.

A peça continuará vindo do conector autorizado do sistema processual de origem - PJe, eproc ou DCP/legado - e passará pelo serviço local de validação, SHA-256 e armazenamento antes de qualquer notificação.

O cliente DataJud futuro deverá ficar atrás de `M0_APPROVED`, `REAL_CONNECTORS_ENABLED` e de uma confirmação própria de aceite do termo. A chave pública não será fixada no código porque o CNJ informa que ela pode mudar. Consultas terão frequência conservadora, resposta limitada, número exato pós-validado e registro de que a fonte não garante precisão, integridade ou atualidade.

## Consequências

- O DataJud não resolve a ausência do token/certificado necessário para peças protegidas.
- É possível demonstrar metadados e roteamento antes do acesso autenticado, mas somente após a análise de compatibilidade e o aceite do termo.
- O Discord não receberá link público para documento sigiloso; a política de anexos e participantes precisa ser aprovada no M0/M8.
- Nenhuma chamada real à API Pública foi feita durante este estudo.

## Fontes oficiais

- https://datajud-wiki.cnj.jus.br/api-publica/
- https://datajud-wiki.cnj.jus.br/api-publica/glossario/
- https://datajud-wiki.cnj.jus.br/api-publica/endpoints/
- https://datajud-wiki.cnj.jus.br/api-publica/exemplos/exemplo1/
- https://datajud-wiki.cnj.jus.br/api-publica/termo-uso/
