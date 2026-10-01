# ADR-010 - Conector do Portal de Serviços do TJRJ (processo eletrônico legado)

- Status: aceito; implementado na versão 0.8.0 (movimentações validadas; peças pendentes)
- Data: 2026-09-30

## Contexto

44 processos da carteira têm numeração antiga do TJRJ e não estão no eproc nem no PJe. Eles só aparecem no Portal de Serviços (`www3.tjrj.jus.br/portalservicos`). Duas gravações guiadas (`diagnostico-tjrj`) e dois vídeos do operador, gravados no Mac em 30/09/2026, mostraram:

- o login é feito pelo IdServerJus (botão de certificado em imagem): o Chrome pede a escolha do certificado e o SafeSign, o PIN (que fica em cache depois da primeira vez);
- a sessão fica presa à aba e não sobrevive a uma janela nova do robô (`storage_state` não basta);
- a consulta roda num iframe (`/consultaprocessual/`): aba "Por Número", numeração "Única", número em duas partes (`NNNNNNN-DD.AAAA` + `.8.19.` fixo + `OOOO`), "Pesquisar";
- os detalhes mostram só a "Última Movimentação"; o botão de leitura "Todos Os Movimentos" abre a lista completa em cartões `app-movimento`, paginada de 10 em 10, da mais recente para a mais antiga;
- depois de um processo, o iframe continua nos detalhes e o endereço da página não muda.

## Decisão

- `TjrjPortalConnector` (`legal_monitor.connectors.tjrj_portal`) com a mesma interface dos conectores PJe/eproc.
- **Login dentro da rodada** (`login_per_run`): o monitor não verifica a sessão antes; o conector abre o login no mesmo contexto da leitura, clica no botão público de certificado e espera até 5 min pelo Portal. Rodadas sem login interativo marcam `AUTH_REQUIRED`.
- Janela sempre visível nesse site (escolha do certificado é diálogo do navegador).
- Entre processos, volta à pesquisa pelo botão "Voltar" do próprio Portal; se não der, recarrega a consulta passando pelo painel.
- Leitura de cartões: tipo do movimento + pares rótulo/valor; a data principal é o primeiro campo "Data…"; o texto fica estável entre rodadas para o dedupe.
- Agenda: 06:30 e 18:30 (`ops/launchd/registrar-robos.sh`).
- Somente leitura: nunca Petição Eletrônica, Push, Distribuição, intimações ou qualquer controle de escrita.
- Peças ainda não são baixadas: o e-mail informa o motivo ("abra no Visualizador do Portal"). Os cartões têm "Visualizar Ato Assinado Digitalmente" e "Ver Íntegra da Decisão", candidatos para a próxima etapa.

## Consequências

- Validado em 30/09/2026: teste com 3 processos (51, 50 e 118 movimentações, histórico completo até a distribuição) e rodada com os 44.
- Sem ninguém na frente do Mac, a rodada para na escolha do certificado. Rodar sozinho exige a política do Chrome `AutoSelectCertificateForUrls` restrita aos hosts do TJRJ — decisão do titular do certificado, ainda não tomada.
- `--max-processos` permite validar um conector novo com poucos processos; `monitor-run` passou a ter trava por site (duas rodadas do mesmo site não correm juntas).
