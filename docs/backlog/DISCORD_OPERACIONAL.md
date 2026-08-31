# Backlog do canal Discord operacional

O usuário indicou Discord como canal desejado para o piloto. Esta intenção não equivale à aprovação de envio de dados processuais. O adaptador atual continua limitado à fixture fictícia.

Em 31/08/2026, a prova externa foi concluída com sucesso usando o webhook novo no Keychain, mensagem fixa, número mascarado e PDF vazio. Isso comprova somente a entrega técnica. Não comprova acesso a tribunal, monitoramento, download de peça, resumo ou autorização para dados jurídicos reais.

## Portões antes de código operacional

- confirmação humana de que todo webhook exposto foi revogado; o substituto já está no Keychain;
- participantes do canal e acessos administrativos aprovados;
- avaliação de sigilo, LGPD, termos do Discord, retenção e localização/tratamento dos anexos;
- advogado destinatário e substituto definidos;
- tipos de movimentação e política de anexos aprovados;
- processo e fonte de teste autorizados;
- outbox, canal secundário e resposta a incidente definidos.

## Entrega técnica futura

1. Formatar mensagem por schema versionado, com número mascarado quando a política exigir.
2. Gravar movimento, documento e outbox na mesma unidade lógica.
3. Usar idempotência por destinatário, documento e tipo de mensagem.
4. Enviar um PDF validado por tentativa, respeitando o limite de 10 MiB do Discord.
5. Para arquivo maior, não publicar URL aberta: criar ação humana ou acesso local autenticado/expirável aprovado.
6. Registrar `provider_id`, tentativa, resultado e correlação, sem token ou conteúdo integral em logs.
7. Retentar falha temporária com backoff; falha permanente vai para dead letter e canal secundário.
8. Nunca interpretar envio HTTP como ciência jurídica, intimação oficial ou confirmação de leitura do advogado.

## Relação com DataJud

DataJud poderá, se juridicamente permitido, indicar uma movimentação pública. Ele não fornece a peça. A entrega de PDF depende do conector autorizado PJe/eproc/DCP e do pipeline de integridade local.

## Critério de saída

Evento controlado em um processo autorizado gera exatamente um movimento, um documento/hash e uma entrega ao advogado, sem duplicata, com falhas visíveis e rollback documentado.
