# Estudo da API Pública do DataJud

Pesquisa concluída em 31/08/2026, exclusivamente sobre documentação oficial. Nenhuma requisição foi enviada à API.

## Resultado executivo

A API Pública do DataJud pode retornar metadados de capa e movimentações de processos públicos. Ela não disponibiliza o arquivo das peças processuais. Para o robô, sua função correta é acelerar descoberta, roteamento e reconciliação; o PDF deve ser coletado depois no PJe, eproc ou DCP autorizado.

## Escopo documentado

O glossário oficial contém:

- número CNJ, tribunal, grau, nível de sigilo e data de ajuizamento;
- formato e sistema processual;
- classe, assuntos e órgão julgador;
- código, nome, data, complementos e órgão de cada movimentação;
- timestamps de atualização do índice.

Não há campo documentado para peça, documento, PDF, conteúdo, anexo ou URL de download. O exemplo de busca por número processual confirma a mesma estrutura.

## Acesso e TJRJ

- Método: `POST` com Query DSL do Elasticsearch.
- Endpoint TJRJ: `https://api-publica.datajud.cnj.jus.br/api_publica_tjrj/_search`.
- Autorização: cabeçalho `Authorization: APIKey ...` com chave pública vigente publicada pelo CNJ.
- A chave pode mudar e, por isso, não deve ser fixada no repositório.
- A versão está documentada como Beta.

## Termo e confiabilidade

O simples consumo implica aceite integral do termo. O termo restringe o uso a finalidade legal, não comercial e autorizada e informa que o CNJ não garante precisão, integridade ou atualidade. Antes da primeira chamada, o escritório deve obter análise jurídica documentada sobre a compatibilidade do uso interno pretendido com a restrição não comercial; aceitar o termo, isoladamente, não resolve essa dúvida.

## Fluxo proposto

1. Agenda, DJEN, Push ou DataJud sinaliza possível movimento.
2. O número CNJ é validado e o resultado DataJud é pós-filtrado por igualdade exata.
3. O sistema informado ajuda o router, mas não substitui confirmação na fonte.
4. O conector PJe/eproc/DCP autorizado confirma a movimentação.
5. Havendo peça, o conector baixa o PDF para temporário.
6. O serviço valida MIME/assinatura/páginas, calcula SHA-256 e armazena atomicamente.
7. Outbox idempotente prepara a entrega pelo canal aprovado.

## Fontes oficiais

- API Pública: https://datajud-wiki.cnj.jus.br/api-publica/
- Acesso: https://datajud-wiki.cnj.jus.br/api-publica/acesso/
- Endpoints: https://datajud-wiki.cnj.jus.br/api-publica/endpoints/
- Glossário: https://datajud-wiki.cnj.jus.br/api-publica/glossario/
- Exemplo por número: https://datajud-wiki.cnj.jus.br/api-publica/exemplos/exemplo1/
- Considerações finais: https://datajud-wiki.cnj.jus.br/api-publica/consideracoes_finais/
- Termo de uso: https://datajud-wiki.cnj.jus.br/api-publica/termo-uso/
