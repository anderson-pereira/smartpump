# Guia de desenvolvimento: controle laboratorial pela Raspberry Pi

## 1. Objetivo e escopo

Este documento orienta a continuidade do projeto por um aluno de graduação. O objetivo é executar o controle da válvula Cavro e da bomba Ismatec ISM832 em uma Raspberry Pi, oferecendo uma API REST e uma página Web simples para configuração, operação e acompanhamento pela rede do laboratório.

O código atual está funcional e já foi testado com os dispositivos físicos. O [README.md](README.md) descreve essa implementação. **As funcionalidades e contratos deste guia são propostas para desenvolvimento; ainda não estão implementados.** Os nomes de arquivos da arquitetura também representam a organização futura.

A primeira entrega deve permitir:

- Configurar e conectar os dispositivos pela página Web.
- Consultar conexão, estado, falhas e necessidade de homing.
- Controlar manualmente os dispositivos com confirmação das ações.
- Criar, visualizar, editar, salvar e reutilizar receitas em JSON.
- Executar receitas com fase inicial, sequência intermediária com loops independentes e fase final.
- Acompanhar e interromper uma execução, preservando o registro do que ocorreu.
- Continuar executando na Raspberry Pi se o navegador for fechado ou perder a conexão.

O armazenamento deve continuar simples, em arquivos locais. Não são necessários banco de dados, serviços de nuvem, aplicação de página única com framework complexo ou múltiplos serviços na primeira versão.

## 2. Boas práticas e responsabilidades

### 2.1. Princípios obrigatórios

| Princípio | Aplicação neste projeto |
| --- | --- |
| Responsabilidade única | O driver conhece comandos seriais; o executor conhece receitas; o repositório conhece arquivos; a API conhece HTTP; a página conhece apresentação e interação. |
| Separação em arquivos e módulos | Agrupar funções relacionadas em módulos pequenos. Evitar concentrar rotas, acesso serial, regras e HTML em um único arquivo. Não criar um arquivo por função sem necessidade. |
| Dependências explícitas | Fornecer drivers, armazenamento e relógio aos serviços por construtores ou parâmetros. Evitar estado global espalhado e abertura de portas durante imports. |
| Uma implementação por regra | A validação e a coordenação dos dispositivos devem ser compartilhadas por API, executor e eventual interface de terminal. |
| Validação no servidor | A página ajuda o usuário, mas o servidor decide se uma receita, configuração ou ação é válida e permitida no estado atual. |
| Estados e erros explícitos | Diferenciar parado, executando, desconectado, desconhecido e em falha. Uma resposta ausente não significa sucesso. |
| Clareza | Usar nomes descritivos, anotações de tipo, unidades explícitas e docstrings nas interfaces. Comentar decisões e restrições, sem repetir o código. |
| Configuração separada do código | Parâmetros operacionais devem ser persistidos em JSON e editáveis pela Web. Não gerar ou editar arquivos Python pela interface. |
| Observabilidade | Usar `logging` e eventos estruturados no lugar de `print()` na lógica de controle. Registrar comandos, confirmações, mudanças de estado e erros. |
| Desenvolvimento incremental | Fazer commits pequenos, com objetivo claro. Preservar uma referência da versão já validada e validar cada etapa antes de integrar a próxima. |

O domínio e os drivers não devem chamar `input()`, depender de HTTP ou apresentar caixas de confirmação. Por exemplo, `home()` deve realizar a operação; a interface solicita a confirmação e o serviço verifica a autorização antes de chamá-lo.

Drivers devem retornar resultados definidos ou lançar exceções específicas, como `CommunicationError`, `DeviceFault` e `CommandTimeout`. Uma falha de parada da bomba deve impedir a movimentação automática seguinte. Evitar capturar uma exceção, apenas imprimir uma mensagem e continuar como se a operação tivesse sido concluída.

### 2.2. Organização sugerida

```text
app/
  main.py                       # Montagem da aplicação e ciclo de vida
  domain/
    recipes.py                  # Modelos de fases, etapas e loops
    states.py                   # Estados de dispositivos, operações e execuções
    errors.py                   # Exceções da aplicação
    validation.py               # Regras de receitas e limites
  devices/
    interfaces.py               # Contratos dos drivers
    cavro.py                    # Protocolo da válvula
    ismatec.py                  # Protocolo da bomba
    serial_transport.py         # Abertura, leitura, escrita e fechamento serial
    simulated.py                # Dispositivos simulados para desenvolvimento
  services/
    device_manager.py           # Conexões, exclusão mútua e coordenação física
    recipe_service.py           # Validação, prévia e gestão de receitas
    executor.py                 # Execução de fases, etapas e loops
    confirmations.py            # Preparação e validação de confirmações
    settings_service.py         # Validação e aplicação de configurações
  storage/
    recipe_repository.py        # Receitas em JSON
    settings_repository.py      # Configurações em JSON
    run_repository.py           # Cópias das receitas executadas e eventos
  api/
    schemas.py                  # Contratos de entrada e saída HTTP
    status.py                   # Rotas de consulta de estado
    recipes.py                  # Rotas de receitas e prévias
    runs.py                     # Rotas de execução e histórico
    control.py                  # Rotas de ações manuais e confirmações
    settings.py                 # Rotas de configuração e portas
    auth.py                     # Autenticação e sessão
  web/
    index.html                  # Estrutura da página
    styles.css                  # Apresentação
    api.js                      # Chamadas HTTP e tratamento de respostas
    recipes.js                  # Editor e visualização das receitas
    control.js                  # Estado, comandos e confirmações
data/
  settings.json
  recipes/<recipe_id>.json
  runs/<run_id>/run.json
  runs/<run_id>/events.jsonl
tests/
  unit/
  integration/
  acceptance/
pyproject.toml                  # Dependências e configuração das ferramentas
README.md
GUIA_DESENVOLVIMENTO.md
```

Criar módulos conforme as etapas de implementação, incluindo os `__init__.py` necessários; a árvore é um mapa de responsabilidades, não uma exigência de criar arquivos vazios antecipadamente. Não versionar dados de experimentos, credenciais ou configurações específicas da bancada. Manter exemplos fictícios em uma pasta própria.

### 2.3. Tecnologias propostas

- Manter Python e `pyserial`, reaproveitando os protocolos já validados.
- Usar FastAPI com modelos Pydantic para contratos tipados, validação e documentação OpenAPI. Esses recursos são descritos na [documentação oficial do FastAPI](https://fastapi.tiangolo.com/features/).
- Servir HTML, CSS e JavaScript pela mesma aplicação. Começar com consultas periódicas de estado, sem exigir WebSocket.
- Usar um único processo de aplicação e um executor dedicado de hardware. Múltiplos workers são processos distintos; nesta arquitetura, cada um poderia criar seu próprio controlador e disputar as portas. Essa decisão decorre do modelo de [workers do FastAPI/Uvicorn](https://fastapi.tiangolo.com/deployment/server-workers/).
- Fixar as versões das dependências efetivamente validadas e documentar a versão do Python adotada na Raspberry Pi. Usar ambiente virtual e ferramentas de formatação, análise estática e testes.

Não executar uma receita longa dentro da requisição HTTP. O servidor recebe a solicitação, valida e entrega o trabalho ao executor; a resposta informa como acompanhar o resultado. O executor deve continuar independente da conexão do navegador.

## 3. Modelo de receitas

### 3.1. Fases e nós

Uma receita deve ter `name`, `description`, versão de formato e três fases ordenadas:

| Campo | Significado |
| --- | --- |
| `initial` | Preparação, executada uma única vez antes da sequência intermediária. |
| `main` | Sequência principal, com etapas e loops independentes. |
| `final` | Finalização programada, executada uma única vez após a conclusão normal da sequência principal. |

Cada fase é uma lista. As fases inicial e final podem ser vazias quando o experimento não as exigir; `main` deve conter pelo menos uma etapa executável. Na primeira versão, permitir loops apenas em `main`, inclusive dentro de outros loops até o limite de profundidade definido. Isso mantém claras as fases de preparação e finalização.

Existem dois tipos de nó:

| Tipo | Campos obrigatórios | Semântica |
| --- | --- | --- |
| `step` | `id`, `type`, `description`, `channel`, `solution`, `duration_seconds` | Selecionar o canal e manter a etapa pelo tempo definido. |
| `loop` | `id`, `type`, `description`, `repeat`, `steps` | Executar a lista `steps` inteira exatamente `repeat` vezes. |

Todos os nós, incluindo loops, devem ter uma descrição não vazia. Um loop não escolhe um canal: suas etapas internas fazem isso. Os identificadores dos nós devem ser únicos dentro da receita para que a execução possa apontar exatamente a etapa e a iteração atuais.

Usar segundos inteiros positivos no JSON, com resolução de um segundo. A Web pode receber minutos e segundos e converter explicitamente. `repeat: 10` significa dez execuções totais do bloco, não uma execução mais dez repetições.

Não adotar simultaneamente repetição global implícita e loops explícitos. Para repetir um protocolo, envolver os passos desejados em um loop. A primeira versão deve aceitar somente receitas finitas; ciclagem infinita e pausa/retomada ficam para uma evolução com regras próprias de temporização e recuperação.

### 3.2. Exemplo completo em JSON

No exemplo fornecido para o loop 02, o título indica canais 4 e 5, mas os tempos citam canais 2 e 3. **Neste guia foi adotada a intenção de alternar os canais 4 e 5**, por 2 e 3 minutos, respectivamente. A água da etapa final foi associada ao canal 1, assim como na etapa inicial. São dados fictícios, a conferir com a montagem real antes do uso.

```json
{
  "schema_version": 1,
  "id": "exemplo-laboratorial",
  "revision": 1,
  "name": "Lavagem e alternância de soluções",
  "description": "Exemplo fictício com preparação, dois loops independentes e lavagem final.",
  "initial": [
    {
      "id": "lavagem-inicial",
      "type": "step",
      "description": "Preparar o circuito com água antes do protocolo.",
      "channel": 1,
      "solution": "H2O",
      "duration_seconds": 600
    }
  ],
  "main": [
    {
      "id": "exposicao-canal-6",
      "type": "step",
      "description": "Aplicar a solução do canal 6 por vinte minutos.",
      "channel": 6,
      "solution": "Solução do canal 6",
      "duration_seconds": 1200
    },
    {
      "id": "loop-01",
      "type": "loop",
      "description": "Alternar os canais 2 e 3 em dez repetições.",
      "repeat": 10,
      "steps": [
        {
          "id": "loop-01-canal-2",
          "type": "step",
          "description": "Aplicar a solução do canal 2 por dois minutos em cada repetição.",
          "channel": 2,
          "solution": "Solução do canal 2",
          "duration_seconds": 120
        },
        {
          "id": "loop-01-canal-3",
          "type": "step",
          "description": "Aplicar a solução do canal 3 por três minutos em cada repetição.",
          "channel": 3,
          "solution": "Solução do canal 3",
          "duration_seconds": 180
        }
      ]
    },
    {
      "id": "lavagem-entre-loops",
      "type": "step",
      "description": "Lavar com água entre os dois blocos de alternância.",
      "channel": 1,
      "solution": "H2O",
      "duration_seconds": 300
    },
    {
      "id": "loop-02",
      "type": "loop",
      "description": "Alternar os canais 4 e 5 em dez repetições.",
      "repeat": 10,
      "steps": [
        {
          "id": "loop-02-canal-4",
          "type": "step",
          "description": "Aplicar a solução do canal 4 por dois minutos em cada repetição.",
          "channel": 4,
          "solution": "Solução do canal 4",
          "duration_seconds": 120
        },
        {
          "id": "loop-02-canal-5",
          "type": "step",
          "description": "Aplicar a solução do canal 5 por três minutos em cada repetição.",
          "channel": 5,
          "solution": "Solução do canal 5",
          "duration_seconds": 180
        }
      ]
    },
    {
      "id": "lavagem-apos-loops",
      "type": "step",
      "description": "Lavar com água após os blocos de alternância.",
      "channel": 1,
      "solution": "H2O",
      "duration_seconds": 300
    }
  ],
  "final": [
    {
      "id": "lavagem-final",
      "type": "step",
      "description": "Finalizar o protocolo com dez minutos de água.",
      "channel": 1,
      "solution": "H2O",
      "duration_seconds": 600
    }
  ]
}
```

Esse exemplo corresponde a **45 etapas executadas e 9.000 segundos (150 minutos)** de permanência programada: 10 + 20 + 50 + 5 + 50 + 5 + 10 minutos. Cada loop tem 20 etapas e duração de 50 minutos. Esses totais não incluem comunicação, movimentação ou esperas de estabilização. Etapas consecutivas no mesmo canal continuam distintas no registro, mesmo sem movimento entre elas.

### 3.3. Validação e prévia

Validar ao salvar, importar, gerar a prévia e iniciar a execução. A última validação também deve considerar a configuração e os dispositivos atuais.

- Rejeitar nomes, descrições e soluções vazios, campos desconhecidos e tipos incorretos.
- Exigir canais inteiros positivos, durações positivas e repetições inteiras positivas. Para executar, exigir também que os canais pertençam ao intervalo configurado na bancada. Rejeitar booleanos usados como números.
- Rejeitar loops vazios, IDs duplicados e versões de formato não suportadas.
- Adotar limites explícitos e configuráveis: proposta inicial de 3 níveis de loop, 1.000 repetições por loop, 10.000 etapas após expansão e 7 dias de duração programada total. São limites de software a ajustar com o responsável pelo laboratório, não limites físicos dos equipamentos.
- Calcular contagem e duração recursivamente antes de expandir ou executar. Interromper a validação assim que ultrapassar um limite; um JSON pequeno pode representar uma execução enorme.
- Separar erros estruturais, que impedem salvar, de incompatibilidades com a bancada, que impedem executar. Uma receita guardada pode continuar disponível mesmo que a configuração atual não permita usá-la.
- A prévia deve trazer resumo por fase, lista hierárquica, duração de cada bloco, duração total, número total de etapas, canais/soluções e avisos de compatibilidade.
- Oferecer visualização expandida ou paginada das repetições, com caminhos como `main / loop-01 / repetição 3 de 10 / canal 2`.

O texto `solution` documenta o líquido esperado; o software não identifica o conteúdo físico do reservatório. A página deve mostrar a associação canal/solução para conferência na confirmação inicial. A configuração pode manter rótulos dos canais; divergências entre esses rótulos e a receita devem ser resolvidas antes de iniciar.

### 3.4. Persistência e reutilização

Armazenar uma receita por arquivo em `data/recipes/<recipe_id>.json`. O servidor gera IDs e nomes de arquivo seguros; o nome informado pelo usuário é metadado e nunca deve ser utilizado diretamente como caminho. `schema_version` identifica o formato; `revision` aumenta a cada edição; `created_at` e `updated_at` devem ser adicionados pelo servidor em UTC, no formato ISO 8601.

Permitir criar, listar, pesquisar por nome, editar, duplicar, excluir, exportar e importar. Na API, duplicar significa criar uma nova receita a partir do conteúdo de uma existente; importar utiliza a mesma validação da criação. IDs, revisões e datas de arquivos importados não devem sobrescrever automaticamente uma receita local.

Gravar em arquivo temporário no mesmo sistema de arquivos, descarregar os dados e substituir o destino de forma atômica. Serializar escritas concorrentes, manter uma cópia anterior recuperável e tratar JSON corrompido sem sobrescrevê-lo silenciosamente. A API deve impedir que uma edição antiga sobrescreva outra mais recente por meio de revisão/`ETag`.

Ao iniciar, salvar em `run.json` uma cópia imutável da receita, da configuração efetiva e das opções de operação, com identificadores, revisões e hashes. Edições ou exclusões posteriores na biblioteca não alteram essa execução nem seu histórico. Registrar eventos em JSON Lines, um objeto por linha, com horário, execução, fase, etapa, pilha de iterações, ação, resultado e erro quando houver.

## 4. Regras de execução e controle físico

### 4.1. Um único responsável pelo hardware

Somente `device_manager` e seu executor podem acessar os drivers. Serializar comandos e consultas de cada conexão; duas requisições não podem ler a resposta uma da outra. Reservar o conjunto bomba/válvula durante uma execução e permitir no máximo uma execução ativa.

Rotas HTTP apenas solicitam trabalho ou consultam uma cópia do estado. Uma thread dedicada pode ser usada na primeira versão, com fila limitada e prioridade para interrupções. Não segurar um bloqueio durante toda a duração de uma etapa: usar esperas interrompíveis, relógio monotônico e verificações frequentes de cancelamento.

Durante uma receita, bloquear seleção manual de canal, homing, partida manual, desconexão e aplicação de configurações. A interrupção da execução é permitida. Consultas, prévias e edição da biblioteca permanecem disponíveis. Um comando pendente deve ser revalidado imediatamente antes de acessar o hardware; a situação pode ter mudado após a requisição.

### 4.2. Estados observáveis

| Recurso | Estados ou campos propostos |
| --- | --- |
| Conexão de cada dispositivo | `disconnected`, `connecting`, `connected`, `fault` |
| Válvula | `ready`, `busy`, `unknown`, `fault`; canal atual ou `null`; `homing_required`: `true`, `false` ou `null` |
| Bomba | `running`, `stopped`, `unknown`, `fault`; velocidade em rpm ou `null` |
| Execução | `starting`, `running`, `stopping`, `completed`, `stopped`, `failed`, `interrupted` |
| Operação avulsa | `queued`, `running`, `succeeded`, `failed` |

`unknown` significa ausência de informação confiável; não equivale a pronto. `homing_required: null` significa que ainda não foi possível determinar a necessidade. Falhas e mensagens que apenas sugerem homing devem ser apresentadas sem transformar toda falha de comunicação em uma conclusão de que homing é necessário.

Estados de execução seguem `starting → running → completed`, com `stopping → stopped` para interrupção confirmada e `failed` para falhas. `interrupted` identifica uma execução que estava ativa antes da queda ou reinicialização do processo. Não retomar automaticamente uma execução interrompida.

### 4.3. Sequência de uma etapa

O início da execução deve exigir dispositivos necessários conectados, estado conhecido, receita compatível, ausência de operação conflitante e confirmação válida. Definir na execução `pump_mode: "controlled"` ou `"external"`:

- `controlled`: o servidor coordena partida e parada da bomba. A bomba é requisito para iniciar.
- `external`: o servidor controla apenas a válvula. A confirmação deve informar que parada, partida e continuidade do fluxo dependem do operador ou de outro sistema. Não alegar que a aplicação parou essa bomba.

No modo controlado:

1. Confirmar a parada da bomba antes de qualquer movimentação necessária da válvula. Uma falha impede o próximo comando de movimento.
2. Aguardar o atraso de parada configurado.
3. Selecionar o canal, aguardar `READY` e confirmar a posição.
4. Aguardar o atraso de retomada quando aplicável, iniciar a bomba e confirmar o resultado.
5. Começar a temporização da etapa somente após concluir essa preparação.

Na primeira etapa, verificar e estabelecer explicitamente o bombeamento mesmo se a válvula já estiver no canal desejado. Para etapas consecutivas no mesmo canal, preservar o bombeamento confirmado e iniciar a próxima temporização sem uma parada desnecessária. Em modo externo, temporizar após a confirmação do canal, deixando explícito que o fluxo não foi verificado.

No controle manual, uma troca de canal deve preservar o estado anterior da bomba: se estava parada, permanece parada; se estava funcionando, a retomada deve constar da confirmação. Homing com integração ativa exige parada confirmada e mantém a bomba parada ao terminar. Um estado desconhecido bloqueia movimentos e partidas, mas deve permitir uma solicitação de parada ou recuperação adequada ao protocolo.

### 4.4. Conclusão, interrupção e falhas

Na conclusão normal, executar `final` e depois parar a bomba no modo controlado. Só marcar `completed` após confirmar essa parada; falha na finalização resulta em `failed`. Essa é a política inicial proposta; manter bombeamento após a receita exigiria uma opção futura explícita e confirmada. No modo externo, registrar que a parada não está sob controle do servidor.

Na interrupção solicitada pelo operador, impedir novas etapas, tentar parar a bomba controlada e deixar a válvula na posição alcançada. **Não executar automaticamente a fase final**, pois ela pode acrescentar líquido e alterar o experimento. Uma lavagem de recuperação deve ser uma nova operação ou receita confirmada.

Em falha, impedir novos movimentos e tentar parar a bomba controlada quando houver comunicação. Se a parada não puder ser confirmada, registrar `failed`, exibir estado físico desconhecido e informar que a intervenção local é necessária. Nunca apresentar “bomba parada” apenas porque a conexão foi fechada. Uma parada protetiva automática é parte da política autorizada ao iniciar o controle e não espera nova confirmação do navegador.

O botão Web de interrupção representa uma solicitação operacional. Ele não deve prometer parada física imediata de um movimento já enviado nem substituir os meios locais de parada dos equipamentos. Timeouts de leitura e do comando atual devem limitar o tempo até o executor processar a interrupção.

Perder a conexão do navegador não interrompe a receita: o executor local continua e a página reconectada recupera o estado. Uma reinicialização da Raspberry Pi ou do processo marca a execução anterior como `interrupted`, invalida confirmações pendentes e exige recuperação explícita. O comportamento físico durante falta de energia ou perda de comunicação deve ser verificado em bancada; não pode ser garantido pela API.

## 5. Confirmações e concorrência entre operadores

Toda ação iniciada pelo usuário que possa afetar os dispositivos deve ter uma confirmação específica: conectar/reconectar, desconectar, selecionar canal, executar homing, iniciar/parar bomba, iniciar/interromper receita e aplicar configurações. Excluir ou sobrescrever uma receita também deve ter confirmação na interface por alterar dados reutilizáveis.

**Uma confirmação de início autoriza a receita completa exibida**, incluindo seus loops, finalização e política de parada. Não solicitar um clique em cada etapa automática, o que impediria o uso autônomo. Alterar parâmetros, receita ou destino invalida a confirmação anterior.

Fluxo proposto, aplicado pelo servidor e pela página:

1. O usuário seleciona a ação. A página solicita uma preparação em `POST /api/v1/control/confirmations`.
2. O servidor valida a ação sem comandar hardware e retorna um token temporário, o resumo dos efeitos e as revisões relevantes.
3. A página mostra uma caixa de confirmação com ação, dispositivo, canal/solução, receita/revisão, duração e consequências. O botão deve dizer, por exemplo, “Confirmar início da receita”. Cancelar é a opção inicialmente em foco; abrir o diálogo não pode confirmar a ação.
4. Somente após o clique explícito, a página envia a ação ao endpoint correspondente com `X-Confirmation-Token` e `Idempotency-Key`.
5. O servidor verifica token, sessão, método, rota, conteúdo e estado; reserva o recurso e consome a confirmação de forma atômica. O executor verifica novamente as condições físicas antes de agir.

O token deve ser imprevisível, de uso único e expirar após um prazo curto (proposta: 60 segundos). Vinculá-lo ao conteúdo normalizado da ação, à receita e configuração pertinentes e à geração do controle. Atualizações do relógio de progresso não devem invalidá-lo; uma nova execução, desconexão ou troca de configuração pode invalidá-lo. Para interromper, vinculá-lo à execução identificada e aceitar enquanto ela estiver ativa.

Repetir uma requisição com a mesma `Idempotency-Key`, sessão e conteúdo deve retornar a operação original, sem comandar o dispositivo outra vez. Reutilizar a chave com outro conteúdo deve produzir conflito. Consultar a chave antes de rejeitar um token já consumido em uma repetição legítima. Persistir o vínculo entre chave e operação antes de despachar o trabalho; após reiniciar, nunca reenviar automaticamente um comando cujo resultado físico seja desconhecido.

O servidor não consegue provar que uma pessoa leu a caixa de diálogo. O token impõe a preparação e a correspondência da ação; autenticação, bloqueios e intertravamentos continuam necessários. Não aceitar simplesmente `confirmed: true` como substituto do fluxo.

## 6. API REST proposta

### 6.1. Organização

Adotar o prefixo `/api/v1`. As ideias originais de `/api/status`, `/api/recipes` e `/api/control` são preservadas, com recursos adicionais para separar responsabilidades:

| Grupo | Responsabilidade |
| --- | --- |
| `/status` | Visão consolidada da aplicação e dos dispositivos. |
| `/recipes` | Biblioteca de definições reutilizáveis. |
| `/runs` | Execuções concretas, progresso e histórico. |
| `/control` | Preparação de confirmações e comandos manuais com tipos definidos. |
| `/settings` | Configuração persistida e aplicação no equipamento. |
| `/serial-ports` | Portas disponíveis na Raspberry Pi. |
| `/operations` | Resultado de ações demoradas que não são receitas. |
| `/auth` | Sessão de acesso à aplicação. |

Separar `/recipes` de `/runs` evita confundir edição de um protocolo com controle de uma execução. `/control` deve ter um conjunto fechado de comandos tipados; não expor envio arbitrário de bytes ou comandos seriais pelo navegador.

### 6.2. Endpoints

Todos os caminhos abaixo são relativos a `/api/v1`. `C` indica confirmação emitida pelo servidor; operações com efeito físico também exigem `Idempotency-Key`.

| Método e caminho | Entrada/resultado principal | Confirmação |
| --- | --- | --- |
| `GET /status` | Estado consolidado, execução ativa, falhas, atualização dos dados e ações permitidas. | Não |
| `GET /serial-ports` | Lista de portas e metadados disponíveis, sem abrir dispositivos. | Não |
| `GET /settings` | Configuração desejada, configuração efetiva e suas revisões, sem segredos. | Não |
| `PUT /settings` | Validar e salvar configuração desejada completa; não aplicá-la ao hardware. | Não |
| `POST /settings/apply` | Aplicar a revisão desejada especificada e reconectar conforme necessário; retorna uma operação. | C |
| `GET /recipes` | Lista resumida com ID, nome, descrição, revisão, duração e quantidade de etapas; busca e paginação. | Não |
| `POST /recipes` | Criar/importar/duplicar a partir de conteúdo validado; servidor atribui ID e revisão. | Não |
| `GET /recipes/{id}` | Obter o JSON completo e `ETag`; também atende exportação. | Não |
| `PUT /recipes/{id}` | Substituir conteúdo usando `If-Match` para impedir sobrescrita concorrente. | Na interface |
| `DELETE /recipes/{id}` | Excluir definição usando `If-Match`; preservar registros de execuções. | Na interface |
| `POST /recipes/preview` | Validar um rascunho e calcular sua prévia sem salvar ou comandar hardware. | Não |
| `POST /control/confirmations` | Preparar ação tipada, sem efeito físico; retornar token, resumo e validade. | Preparação |
| `POST /control/commands` | Executar comando manual permitido; retornar ID de operação. | C |
| `GET /operations/{id}` | Consultar `queued/running/succeeded/failed`, resultado e erro. | Não |
| `POST /runs` | Iniciar uma receita salva, indicando ID, revisão e modo da bomba; retornar ID de execução. | C |
| `GET /runs` | Listar histórico com filtros e paginação. | Não |
| `GET /runs/{id}` | Progresso, fase, etapa, iterações, tempos, resultado e cópias usadas. | Não |
| `GET /runs/{id}/events` | Eventos paginados com cursor. | Não |
| `POST /runs/{id}/stop` | Solicitar interrupção com motivo; resposta assíncrona. | C |
| `POST /auth/login` | Abrir sessão com credenciais válidas. | Não |
| `POST /auth/logout` | Encerrar sessão do navegador sem interromper a receita. | Não |
| `GET /auth/session` | Informar identidade autenticada e permissões. | Não |

Usar `200` para consultas/alterações concluídas, `201` para receita ou confirmação criada, `204` para exclusão concluída e `202` para uma ação aceita ainda em processamento. Uma resposta `202` não significa que o movimento terminou nem que a bomba iniciou: a página deve acompanhar a operação ou execução retornada. Incluir `Location` apontando para esse recurso.

`If-Match` deve ser obrigatório também em `PUT /settings`. Retornar `412` para revisão divergente e `428` quando a precondição obrigatória não foi enviada. Aplicar configurações durante uma execução deve retornar `409`.

### 6.3. Comandos e contratos mínimos

`POST /control/commands` recebe `{ "action": "...", "parameters": { ... } }`. Validar o corpo por tipo de ação:

| `action` | Parâmetros | Regras |
| --- | --- | --- |
| `devices.connect` | `device`: `valve`, `pump` ou `all` | Usar configuração efetiva; não executar homing ou partida automaticamente. |
| `devices.disconnect` | `device`: `valve`, `pump` ou `all` | Exigir ausência de execução e estado de repouso confirmado; parar primeiro se necessário. |
| `valve.select_channel` | `channel` | Exigir ausência de execução e aplicar coordenação da bomba. |
| `valve.home` | Objeto vazio | Exigir ausência de execução e bomba controlada parada antes do movimento. |
| `pump.start` | Objeto vazio | Exigir ausência de execução e condições conhecidas para bombeamento. |
| `pump.stop` | Objeto vazio | Durante receita, orientar o cliente a usar `/runs/{id}/stop`, preservando a coerência do executor. |

Se houver bombeamento manual ativo, desconexão de qualquer dispositivo e aplicação de configurações ficam bloqueadas até uma parada confirmada. Modo externo exige informar na confirmação que o servidor não conhece nem controla o estado da bomba externa.

Exemplo de preparação de início:

```json
{
  "method": "POST",
  "path": "/api/v1/runs",
  "body": {
    "recipe_id": "exemplo-laboratorial",
    "recipe_revision": 1,
    "pump_mode": "controlled"
  }
}
```

O endpoint de confirmações aceita apenas a lista de rotas e corpos permitidos, não URLs arbitrárias. O início confirmado envia exatamente o objeto `body` a `POST /runs`, com os dois cabeçalhos definidos anteriormente. A preparação de uma receita deve associar o token ao plano validado e à configuração efetiva; o cliente não escolhe o hash considerado confiável pelo servidor.

Exemplo de resposta ao início aceito:

```json
{
  "run_id": "run-0001",
  "state": "starting",
  "recipe_id": "exemplo-laboratorial",
  "recipe_revision": 1,
  "status_url": "/api/v1/runs/run-0001"
}
```

Contrato mínimo de `GET /status`:

| Campo | Conteúdo |
| --- | --- |
| `server_time`, `uptime_seconds` | Referências temporais do servidor. |
| `settings_revision`, `effective_settings_revision` | Revisões desejada e em uso. |
| `devices.valve` | Conexão, estado, canal, necessidade de homing, última leitura válida e falha. |
| `devices.pump` | Habilitada ou não, conexão, estado, velocidade, última leitura válida e falha. |
| `active_run` | `null` ou ID, estado, fase, etapa, pilha de loops e tempos. |
| `active_operation` | `null` ou ID e estado de uma operação manual. |
| `allowed_actions` | Ações atualmente permitidas e motivos das demais estarem bloqueadas. |

Informar `observed_at` e `stale` por dispositivo, com limite de validade configurado. A API deve retornar a última observação com sua idade, sem inventar canal ou estado quando não houver leitura confiável. As consultas de status usam o estado mantido pelo executor; não devem disparar acesso serial concorrente.

`GET /runs/{id}` deve incluir `step_id`, fase, índice global, total de etapas, pilha de `{loop_id, iteration, repeat}`, tempo restante da etapa, tempo programado restante e tempo real decorrido. Separar tempos programados de uma previsão de término, pois os movimentos acrescentam duração.

### 6.4. Erros e documentação do contrato

Usar um formato uniforme:

```json
{
  "error": {
    "code": "device_not_ready",
    "message": "A válvula não está pronta para iniciar a receita.",
    "details": { "device": "valve", "state": "unknown" },
    "request_id": "req-0001"
  }
}
```

Documentar `401` para ausência de autenticação, `403` para ação sem permissão ou confirmação inválida, `404` para recurso inexistente, `409` para conflito de estado/confirmação obsoleta/chave reutilizada com outro conteúdo, `422` para dados inválidos e `503` para indisponibilidade do controlador. Falhas ocorridas após um `202` ficam registradas na operação/execução, sem alterar retroativamente a resposta HTTP.

Antes de implementar a página, publicar o contrato OpenAPI com corpos completos, campos obrigatórios, enums, limites, erros e exemplos de cada rota. Os contratos deste guia devem ser traduzidos em modelos e testes, incluindo campos ainda apresentados em tabelas. Usar nomes e códigos estáveis; as mensagens podem ser exibidas em português.

## 7. Página Web

Uma página com navegação simples entre quatro áreas é suficiente:

| Área | Conteúdo e interações |
| --- | --- |
| Painel | Estado da conexão com a Raspberry Pi, estado de cada dispositivo, canal atual, solução, falhas, execução ativa e acesso à interrupção confirmada. |
| Receitas | Biblioteca com nome/descrição, editor por fases, adição/reordenação de etapas e loops, duplicação, importação/exportação, prévia e início confirmado. |
| Controle manual | Seleção de canal, homing, partida e parada, com ações bloqueadas e motivos visíveis quando indisponíveis. |
| Configurações | Portas, comunicação, dispositivos habilitados, rótulos de canais, atrasos, limites e aplicação confirmada. |

O editor deve trabalhar com formulários, sem exigir que o usuário escreva JSON. Cada etapa mostra descrição, canal, solução e duração; cada loop mostra descrição, repetições, etapas internas e duração calculada. Oferecer botões de mover para cima/baixo, além de eventual arrastar e soltar, para permitir uso por teclado.

Antes de iniciar, apresentar a receita completa em árvore, as fases inicial/final destacadas, os loops recolhíveis, as repetições, os totais, o modo da bomba, a política de parada e a revisão que será usada. Uma alteração ainda não salva precisa ser salva como nova revisão antes de iniciar. A prévia deve usar o cálculo do servidor.

Durante a execução, destacar fase, descrição da etapa, canal, solução e iteração de cada loop ativo. Mostrar falhas com texto, sem depender somente de cores. Não permitir que editar a biblioteca pareça editar a execução atual.

Consultar o estado inicialmente a cada segundo, com intervalo configurável e recuo após falhas de rede. Se os dados estiverem desatualizados, mostrar “conexão perdida”/“estado desatualizado” e desabilitar novos comandos até atualizar. Não mostrar uma interrupção como concluída antes de o servidor confirmar seu resultado. Após timeout de uma ação, consultar sua operação ou repetir com a mesma chave, sem criar outra ação às cegas.

A caixa de confirmação deve impedir cliques duplicados enquanto aguarda resposta e nunca reaparecer confirmada após atualizar a página. O acesso por outro navegador deve mostrar a mesma execução e respeitar os bloqueios do servidor.

## 8. Configurações pela Web e instalação na Raspberry Pi

### 8.1. Configuração operacional

Todos os parâmetros de operação dos dispositivos devem ser acessíveis na página:

| Grupo | Parâmetros |
| --- | --- |
| Cada conexão serial | Porta, baud rate, bits de dados, paridade, bits de parada, timeout de leitura/escrita e endereço do dispositivo. |
| Válvula | Quantidade de canais, rótulo de solução por canal, timeout de movimento e timeout de homing. |
| Bomba | Habilitação da integração, atraso após parada e atraso antes da partida. |
| Execução | Limites de duração, repetições, profundidade e etapas expandidas. |
| Monitoramento | Intervalo de consulta dos dispositivos, intervalo de atualização da Web e tempo máximo para considerar uma leitura atual. |

Expor somente valores suportados pelos protocolos; permitir preencher campos não significa que qualquer combinação é válida. Não inferir que a Ismatec permite alterar velocidade pela API atual: o código existente apenas consulta rpm. Implementar ajuste de velocidade/vazão somente após definir o contrato e validar o comando no equipamento.

Listar portas usando `serial.tools.list_ports`, que oferece identificação e metadados quando disponíveis, conforme a [documentação do pySerial](https://pyserial.readthedocs.io/en/latest/tools.html#serial.tools.list_ports). Mostrar caminho, descrição e identificação USB disponível. A enumeração não comprova que o dispositivo correto está conectado; a aplicação deve verificar sua resposta ao conectar.

Na Raspberry Pi, preferir identificadores persistentes disponíveis em `/dev/serial/by-id/`, verificando sua existência na instalação, em vez de depender da ordem de `/dev/ttyUSB0` e `/dev/ttyUSB1`. Permitir informar um caminho alternativo válido. Não aceitar a mesma porta para os dois dispositivos nem permitir caminhos de arquivos arbitrários como portas.

Separar **salvar configuração desejada** de **aplicar ao hardware**. A página deve mostrar diferenças e revisões pendentes. A aplicação é uma operação confirmada, permitida somente sem execução ou movimento e com bombeamento controlado parado. Abrir/verificar os dispositivos com os novos parâmetros; em falha parcial, fechar os recursos da tentativa, registrar a falha e não declarar a nova revisão efetiva. Preservar os valores anteriores para reaplicação explícita, sem iniciar bombeamento ou homing durante recuperação.

O provisionamento do sistema operacional — Wi-Fi/Ethernet, usuário do serviço, permissões e instalação — é uma tarefa inicial de implantação. O operador não deve precisar de terminal para configurações rotineiras de bomba, válvula ou receitas. A configuração de rede da própria Raspberry Pi pode permanecer fora da página na primeira versão; o [guia oficial de acesso remoto](https://www.raspberrypi.com/documentation/computers/remote-access.html) é a referência para implantação e administração.

### 8.2. Implantação e acesso

Executar como serviço gerenciado pelo sistema, com usuário dedicado e permissões apenas para as portas e diretórios necessários, sem rodar toda a aplicação como `root`. Usar um único processo controlador, sem recarga automática em produção, e impedir execução simultânea do terminal antigo sobre os mesmos dispositivos.

Iniciar o serviço em estado sem execução e sem partida ou homing automáticos. Detectar registros de execuções interrompidas e apresentar a necessidade de recuperação. Um reinício automático do serviço não autoriza retomar comandos físicos.

A página deve exigir autenticação, inclusive na rede do laboratório. Proposta inicial: uma conta local de operador com senha definida na instalação, sessão no servidor e cookie `HttpOnly`/`SameSite`, proteção contra CSRF nas alterações e HTTPS na implantação. Não embutir senha ou chave de controle no JavaScript. Restringir acesso à rede autorizada e não publicar portas diretamente na Internet. Confirmação de ação não substitui autenticação.

Servir Web e API na mesma origem, evitando liberar CORS indiscriminadamente. Guardar credenciais fora dos JSON exportáveis e do repositório. Documentar backup/restauração de `data/`, espaço disponível para eventos e política de retenção, sem apagar automaticamente registros de experimentos sem uma regra acordada.

## 9. Aproveitamento do código atual

| Origem | Evolução proposta |
| --- | --- |
| `cavro_valve.py` | Preservar comandos e interpretação já validados; separar interação de terminal, padronizar erros e expor o driver à coordenação central. |
| `flow_pump.py` | Reaproveitar comandos, tornar falhas explícitas e verificar a confirmação de parada/partida antes de continuar. Separar protocolo de mensagens de interface. |
| `recipe.py` | Substituir tuplas globais pelo modelo validado e executor independente de terminal, com fases, pilha de loops e eventos. |
| `config.py` | Migrar parâmetros operacionais para configurações persistidas, usando os valores atuais como referência inicial. |
| `flow_pump_loader.py` | Transferir o ciclo de vida dos dispositivos para o gerenciador, eliminando a dependência de um controlador global. |
| `user_interface.py` | Aproveitar o fluxo operacional como referência para a Web. Se o terminal for mantido, fazê-lo consumir os mesmos serviços ou a API. |
| `main.py` | Separar inicialização, encerramento e montagem de dependências das interações com o operador. |

Mudanças comportamentais que precisam de verificação específica: partida da bomba quando a primeira etapa já usa o canal atual; homing com parada coordenada; bloqueio de movimento após falha de parada; preservação do estado da bomba em controle manual; parada ao interromper/finalizar; ausência de retomada automática após reinício. A validação física da versão atual não valida automaticamente essas novas regras.

## 10. Plano de implementação e critérios de aceite

| Etapa | Entrega | Critério de aceite |
| --- | --- | --- |
| 1. Preparar a base | Ambiente reproduzível, contratos dos drivers e dispositivos simulados. | Importar módulos não abre portas; é possível desenvolver sem hardware. |
| 2. Modelar receitas | Modelos, validação, persistência JSON e cálculo de prévia. | O exemplo deste guia produz 45 etapas e 9.000 segundos; descrições ausentes e loops inválidos são rejeitados. |
| 3. Construir o executor | Fases, loops, estados, cópias imutáveis e eventos. | Ordem correta, inicial/final uma vez, interrupção sem fase final e nenhuma repetição involuntária. |
| 4. Centralizar controle | Coordenação dos dispositivos, configuração persistida e exclusão mútua. | Falha de parada bloqueia movimento; duas solicitações não comandam a mesma porta simultaneamente. |
| 5. Implementar API | Contratos OpenAPI, autenticação, confirmações, idempotência e erros. | Ações sem confirmação são rejeitadas; clique/reenvio duplicado produz uma única operação. |
| 6. Implementar Web | Painel, editor, prévia, controle e configurações. | Usuário monta o exemplo, salva, reabre, confere e executa sem editar Python ou JSON manualmente. |
| 7. Integrar Raspberry Pi | Serviço local, acesso pela rede, permissões e recuperação. | Fechar o navegador não para a receita; reiniciar o serviço não retoma uma execução antiga. |
| 8. Validar em bancada | Roteiro registrado com equipamentos físicos e condições controladas. | Confirmar sequenciamento, tempos, canais, modos da bomba, falhas e interrupções antes de liberar para experimentos. |

### Testes necessários

- **Domínio:** duração e contagem recursivas, loops independentes e aninhados, descrições obrigatórias, limites, IDs duplicados e incompatibilidade de canais.
- **Executor com relógio simulado:** ordem das ações, primeira etapa no canal atual, ausência de dupla partida, atraso/temporização, cancelamento durante espera, falha de comando e fase final somente na conclusão normal. Não aguardar 150 minutos em testes automatizados.
- **API:** validação, estados conflitantes, confirmação vencida ou de outro conteúdo/sessão, alterações após a prévia, token consumido, idempotência, duas solicitações simultâneas e consulta de ações já aceitas.
- **Armazenamento:** gravação interrompida, JSON corrompido, edição concorrente, caminho inválido, importação e preservação da cópia usada em uma execução.
- **Integração simulada:** perda de comunicação, estado desconhecido, aplicação parcial de configuração e reinício com execução ativa.
- **Bancada:** conferir a sequência física com receitas curtas e registrar resultado, modelo/configuração dos equipamentos e versão do código. Confirmar com o responsável o comportamento durante perda de energia e comunicação.

O desenvolvimento está pronto para entrega quando houver documentação atualizada, exemplos de receita, API documentada, testes relevantes aprovados e registro da validação física da nova versão. O aluno deve conseguir explicar a responsabilidade de cada módulo e demonstrar por que um clique duplicado, uma página desatualizada ou uma falha de comunicação não inicia uma sequência física indevida.
