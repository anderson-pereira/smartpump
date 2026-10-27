# SmartPump design QA

final result: blocked

## Artifacts

- Source visual: dashboard SmartPump fornecida na conversa e o design existente em `docs/design/smartpump-dashboard-selected.png`.
- Implementation: build de produção em `web/dist/client`.
- Target state: receita com loop na página Operar, incluindo loop ativo, modal consultivo aberto e painel de comandos manuais em altura desktop.

## Completed checks

- O cartão de execução distribui cabeçalho, mapa da receita e etapa atual verticalmente conforme a altura disponível.
- A lista redundante "A seguir" e seus estilos responsivos foram removidos.
- A navegação principal passou a usar abas de página com título e contexto.
- A faixa de status contém apenas válvula, bomba e receita.
- Os cartões redundantes de receitas recentes e conexões foram removidos.
- A Biblioteca carrega uma receita em Operar sem iniciar a execução.
- O modal de configuração da bomba é aberto pelo botão Iniciar receita da dashboard.
- Pausar, retomar e parar possuem integração real com a API.
- Marcadores de loop abrem um modal consultivo com repetições, duração, vazão e hierarquia interna.
- O loop ativo usa um único cartão para ciclo, etapa interna atual e sequência compacta.
- Os grupos de comandos manuais usam distribuição vertical flexível na altura disponível.
- Build de produção concluído.
- Renderização inicial do React concluída sem exceções.
- Testes do empacotamento Web aprovados (4/4).
- Testes Python aprovados (60/60).

## Blocker

O navegador interno solicitado pelo fluxo de QA não está disponível neste ambiente (`Browser is not available: iab`). Por isso, não foi possível capturar a implementação e compará-la visualmente com a referência no mesmo viewport. Nenhuma aprovação de fidelidade visual é declarada.

## Required next check

Abrir a implementação em um navegador, validar o modal de um loop normal, o cartão de um loop ativo e a distribuição vertical de Comandos da bancada em resoluções desktop e móvel.
