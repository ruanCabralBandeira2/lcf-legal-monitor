# ADR-006 - Contrato rastreável do resumo factual

- Status: aceito para núcleo e demonstração fictícia
- Data: 2026-08-31

## Contexto

A LCF confirmou como objetivo do produto monitorar movimentações, baixar a peça autorizada, resumir seu conteúdo e informar ao advogado o que foi decidido. A especificação v4 exige que o resumo seja estritamente factual, separe conteúdo expresso de inferência, cite páginas quando possível, não calcule prazo e nunca substitua a revisão humana.

O M0 ainda não autorizou processo, fonte, documento ou provedor de IA real. O primeiro conector também não foi escolhido. Portanto, é possível adiantar o contrato de dados e as validações, mas não é seguro extrair ou resumir peças reais.

## Decisão

Criar um núcleo puro em `legal_monitor.summaries` com as seguintes regras:

- todo fato substantivo contém ao menos uma evidência com página e trecho;
- o serviço verifica se a página existe e se o trecho está presente no texto extraído;
- `decisao_resultado` registra somente resultado expresso, nunca recomendação ou estratégia;
- datas e prazos são extrações literais rotuladas como `não validado como prazo processual`;
- todo rascunho automático nasce como `REVIEW_REQUIRED` e não pode se autoaprovar;
- indisponibilidade, falha do provedor ou saída sem evidência viram resultado explícito `UNAVAILABLE`;
- uma falha no resumo não altera a integridade nem impede a entrega futura da peça;
- o serviço não possui notificador, navegador, acesso a segredo ou ferramenta de envio;
- o único provedor atual é determinístico e recusa qualquer entrada diferente da fixture fixa fictícia;
- `SUMMARY_ENABLED` continua `false` por padrão e nenhum modelo local ou remoto foi integrado.

O comando `legal-monitor summary-demo` demonstra o schema sem rede, processo ou documento real. Aprovação ou rejeição humana do rascunho será um caso de uso separado, auditado, em etapa posterior.

## Consequências

- O formato de “o que foi decidido” pode ser avaliado pelo escritório antes do acesso aos tribunais.
- Citações inventadas, páginas inexistentes ou trechos ausentes são rejeitados pelo serviço.
- O núcleo não promete compreensão jurídica nem elimina o risco de erro de OCR ou interpretação.
- A escolha do extrator, OCR e modelo de resumo permanece bloqueada pelo M0 e pelo marco M7.
- O teste fictício não autoriza anexos reais no Discord nem consumo de serviços externos.
