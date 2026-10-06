# Controle de válvula Cavro e bomba de fluxo

Aplicação Python com interface de terminal para controlar uma válvula multicanal Cavro e, opcionalmente, uma bomba de fluxo Ismatec ISM832 por comunicação serial. Permite selecionar canais manualmente ou executar receitas temporizadas, coordenando a parada e a retomada da bomba nas trocas de canal.

O projeto está funcional e já foi testado com os dispositivos físicos.

Para dar continuidade ao desenvolvimento, consulte o [Guia de desenvolvimento](GUIA_DESENVOLVIMENTO.md), que propõe a arquitetura na Raspberry Pi, a API REST, a interface Web e o novo modelo de receitas com fases e loops. Essas evoluções ainda não estão implementadas.

## Funcionalidades

- Consulta de firmware, canal atual e estado da válvula (`READY` ou `BUSY`).
- Seleção de canal pelo menor percurso, com preferência pelo sentido horário em caso de empate.
- Confirmação do canal após o movimento.
- Homing manual para referenciar a válvula no canal 1, mediante confirmação do operador.
- Receitas com execução única, número definido de ciclos ou repetição contínua.
- Exibição do tempo restante da etapa e, para um número finito de ciclos, do tempo total restante.
- Controle remoto opcional da bomba, com pausas configuráveis antes da movimentação da válvula e antes da retomada do bombeamento.
- Opção de parar a bomba ao concluir normalmente uma receita.

## Arquivos do projeto

| Arquivo | Responsabilidade |
| --- | --- |
| `main.py` | Ponto de entrada. Abre a porta serial da válvula, consulta o firmware para verificar a comunicação, apresenta o canal atual e inicia o menu. Trata erros gerais, erros de comunicação e interrupções pelo teclado. Fecha a conexão da válvula e garante a tentativa de fechamento do controlador ativo da bomba ao encerrar. |
| `config.py` | Centraliza portas seriais, velocidades de comunicação, endereços dos dispositivos, quantidade de canais, atrasos da bomba e a receita executada pelo programa. |
| `cavro_valve.py` | Implementa a classe `CavroValve` e o mapa `CAVRO_VALVE_ERRORS`. Monta comandos, interpreta respostas, consulta canal e estado, aguarda a conclusão dos movimentos, escolhe o menor percurso e executa o homing. Recebe uma conexão serial já aberta. |
| `flow_pump.py` | Implementa a classe `FlowPumpController` para a Ismatec ISM832. Abre sua própria conexão serial e oferece identificação, partida, parada, retomada, consulta de funcionamento e leitura de velocidade em rpm. Exibe os comandos enviados (`TX`) e as respostas recebidas (`RX`). |
| `flow_pump_loader.py` | Carrega o módulo `flow_pump` somente quando o controle remoto é habilitado. Mantém uma referência ao controlador ativo para que sua porta possa ser fechada no encerramento da aplicação. |
| `recipe.py` | Exibe a receita, permite escolher a quantidade de ciclos e executa as etapas em ordem. Converte minutos para segundos, coordena a seleção dos canais e acompanha os tempos com `time.monotonic()`. Inclui `format_time()` e o auxiliar `run_timing()`; a execução atual de `run_recipe()` utiliza seu próprio laço de temporização. |
| `user_interface.py` | Implementa os menus e o controle manual. Recebe e valida entradas, habilita ou desabilita a integração com a bomba, solicita confirmações e chama as operações da válvula e da receita. Também trata erros e interrupções durante a execução automática. |
| `.gitignore` | Define arquivos que não devem ser versionados, como caches Python, ambientes virtuais, saídas de empacotamento e arquivos de editores e do sistema operacional. |
| `README.md` | Documenta a organização, a configuração e a operação do projeto. |

## Requisitos e instalação

- Python 3 com suporte a f-strings (Python 3.6 ou superior).
- Biblioteca `pyserial`, utilizada para comunicação com os dispositivos.
- Válvula Cavro conectada a uma porta serial acessível ao computador.
- Bomba Ismatec ISM832 conectada a outra porta serial, caso o controle remoto seja utilizado.

As demais dependências utilizadas pertencem à biblioteca padrão do Python. A configuração atual utiliza portas `COM` do Windows.

Na pasta do projeto, instale a dependência:

```powershell
python -m pip install pyserial
```

## Configuração

Edite `config.py` antes de iniciar a aplicação para adequar os parâmetros à conexão dos dispositivos.

### Válvula Cavro

| Parâmetro | Valor atual | Descrição |
| --- | --- | --- |
| `VALVE_SERIAL_PORT` | `"COM22"` | Porta serial da válvula. |
| `VALVE_BAUD_RATE` | `9600` | Taxa de comunicação em baud. |
| `VALVE_ADDRESS` | `"1"` | Endereço utilizado nos comandos Cavro. |
| `VALVE_CHANNEL_COUNT` | `6` | Quantidade de canais usada na validação e no cálculo dos percursos. |

### Bomba de fluxo

| Parâmetro | Valor atual | Descrição |
| --- | --- | --- |
| `FLOW_PUMP_SERIAL_PORT` | `"COM21"` | Porta serial da bomba. |
| `FLOW_PUMP_BAUD_RATE` | `9600` | Taxa de comunicação em baud. |
| `FLOW_PUMP_ADDRESS` | `1` | Endereço utilizado nos comandos da bomba. |
| `FLOW_PUMP_STOP_DELAY_SECONDS` | `0.3` | Espera, em segundos, após a confirmação de parada da bomba. |
| `FLOW_PUMP_RESTART_DELAY_SECONDS` | `0.3` | Espera, em segundos, antes de enviar o comando de partida na retomada. |

As duas conexões utilizam 8 bits de dados, sem paridade, 1 bit de parada e timeout de leitura de 1 segundo. A porta da bomba só é aberta ao habilitar seu controle remoto no menu.

### Receita

A variável `RECIPE` contém uma lista ordenada de tuplas no formato:

```python
(canal, identificacao_da_solucao, duracao_em_minutos)
```

A receita atual é:

```python
RECIPE = [
    (1, "01", 0.25),
    (2, "02", 0.25),
    (3, "03", 0.25),
    (4, "04", 0.25),
    (5, "05", 0.25),
    (6, "06", 0.25),
]
```

Cada etapa dura 15 segundos, totalizando 1 minuto e 30 segundos de temporização por ciclo. O tempo efetivo de execução também inclui a comunicação serial, os movimentos da válvula e os atrasos configurados para a bomba; esses períodos não entram no total programado exibido.

O canal deve estar entre `1` e `VALVE_CHANNEL_COUNT`. A identificação da solução é um rótulo exibido no terminal. A duração é expressa em minutos e aceita valores fracionários. As alterações em `config.py` são carregadas na próxima inicialização do programa.

## Execução

Na pasta do projeto, execute:

```powershell
python main.py
```

O programa abre a conexão com a válvula, consulta seu firmware e apresenta o canal atual. Após essa verificação, mostra o menu principal. O controle remoto da bomba começa desativado.

### Menu principal

| Opção | Ação |
| --- | --- |
| `1` | Mostrar a receita e preparar sua execução automática. |
| `2` | Entrar no controle manual da válvula. |
| `3` | Mostrar as etapas e o tempo programado da receita. |
| `4` | Solicitar o homing da válvula. |
| `5` | Habilitar ou desabilitar o controle remoto da bomba. |
| `Q` | Encerrar o programa. |

Para usar a bomba integrada à válvula, selecione a opção `5` e responda `s`. Essa ação abre a conexão da bomba; a partida ocorre na retomada após uma troca efetiva de canal. Se o carregamento falhar, a interface informa o erro e mantém o controlador anterior, caso exista.

### Execução automática

1. Selecione a opção `1` no menu principal.
2. Escolha executar uma vez, executar um número inteiro positivo de ciclos ou executar continuamente. O modo contínuo solicita uma confirmação adicional.
3. Se o controle remoto da bomba estiver habilitado, escolha se ela deve parar ao final da receita.
4. Pressione `Enter` para iniciar ou digite `Q` para cancelar.

Em cada etapa, o programa seleciona e confirma o canal e então inicia a contagem do tempo da solução. Ao terminar a etapa, passa à próxima tupla de `RECIPE`. Ao terminar um ciclo, repete a sequência conforme o modo escolhido.

Durante a receita, `Ctrl+C` interrompe a execução e retorna ao menu principal. A válvula permanece no canal em que estiver. A opção de parar a bomba ao final é aplicada após a conclusão normal da receita; ela não é executada pelo tratamento de interrupções ou de erros.

### Controle manual

| Comando | Ação |
| --- | --- |
| `1` a `6` | Selecionar um canal na configuração atual. |
| `p` | Consultar o canal atual. |
| `s` | Consultar o estado da válvula e seu código de erro. |
| `h` | Solicitar o homing. |
| `m` | Retornar ao menu principal. |
| `q` | Encerrar o programa. |

As trocas manuais de canal também utilizam a parada e a retomada da bomba quando seu controle remoto está habilitado.

### Homing

O homing é uma operação manual, disponível no menu principal e no controle manual. Após a confirmação, envia `w1,0R`, aguarda a válvula ficar pronta e consulta o canal reportado para verificar a referência no canal 1. Essa operação nunca é chamada automaticamente na inicialização ou na execução da receita.

O homing chama diretamente o controlador da válvula e não utiliza os callbacks de parada e retomada da bomba empregados nas trocas de canal.

## Coordenação entre a válvula e a bomba

A seleção de canal está concentrada em `CavroValve.select_channel()`, que recebe callbacks opcionais para antes e depois do movimento. O controle manual e a receita associam esses callbacks aos métodos `stop()` e `restart()` da bomba quando a integração está ativa.

Quando o canal solicitado difere do atual, a sequência é:

1. Calcular o menor percurso entre os canais.
2. Chamar `stop()` da bomba, se houver um controlador habilitado. Ao receber `*`, o método aguarda o atraso de parada configurado.
3. Enviar o comando de movimento da válvula.
4. Consultar o estado até `READY`, com limite de espera de 10 segundos, e confirmar o canal de destino.
5. Chamar `restart()` da bomba, se habilitada, aguardando o atraso configurado antes de enviar a partida.

Se o canal já estiver selecionado, o método retorna sem movimentar a válvula e sem chamar os callbacks da bomba. A retomada envia uma partida, independentemente do estado de bombeamento anterior. Os retornos booleanos de `stop()` e `restart()` são informados pelos métodos da bomba, mas não são usados por `select_channel()` para decidir se a sequência deve continuar.

## Comunicação implementada

### Válvula Cavro

Os comandos são enviados em ASCII no formato `/{endereço}{comando}\r`. A leitura procura o prefixo `/0`, interpreta o byte de estado e extrai os dados até o terminador `ETX`, quando presente. A resposta é representada por um dicionário com `raw`, `status`, `error`, `ready` e `data`.

| Comando | Utilização no código |
| --- | --- |
| `&` | Consultar o firmware na inicialização. |
| `?6` | Consultar o canal atual. |
| `Q` | Consultar o estado e aguardar a conclusão de uma operação. |
| `I{canal}R` | Selecionar um canal no sentido horário. |
| `O{canal}R` | Selecionar um canal no sentido anti-horário. |
| `w1,0R` | Executar o homing, com espera de até 20 segundos pelo estado pronto. |

O mapa `CAVRO_VALVE_ERRORS` traduz os códigos retornados pelo dispositivo. Falta de resposta, erros de movimento, timeout e divergência entre o canal solicitado e o reportado são tratados pelo controlador e apresentados pela interface.

### Bomba Ismatec ISM832

Os comandos são enviados em ASCII no formato `{endereço}{comando}\r`.

| Método | Comando | Comportamento |
| --- | --- | --- |
| `identify()` | `#` | Retorna a identificação recebida em uma linha. |
| `start()` | `H` | Inicia a bomba e considera `*` uma confirmação de sucesso. |
| `stop()` | `I` | Para a bomba e considera `*` uma confirmação de sucesso. |
| `restart()` | `H` | Aguarda o atraso de retomada e chama `start()`. |
| `shutdown()` | `I` | Chama `stop()` para parar o bombeamento ao final da receita. |
| `is_running()` | `E` | Interpreta `+` como em funcionamento, `-` como parada e outras respostas como estado desconhecido (`None`). |
| `get_speed()` | `S` | Converte a velocidade recebida para um número em rpm ou retorna `None` se a conversão falhar. |
| `close()` | — | Fecha a conexão serial, caso esteja aberta. |

As consultas de identificação, funcionamento e velocidade estão disponíveis na classe, mas não possuem opções próprias no menu atual. O projeto não implementa ajuste de velocidade ou de vazão pelo terminal.

## Encerramento

Ao sair, a aplicação fecha as conexões seriais. Fechar a conexão da bomba ou desabilitar seu controle remoto não envia um comando de parada. A parada ao final da receita depende da opção escolhida antes de sua execução e da conclusão normal dos ciclos programados.
