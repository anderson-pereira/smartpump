# Controle de válvula Cavro e bomba de fluxo

Aplicação local para controlar uma válvula multicanal Cavro e uma bomba de fluxo Ismatec ISM832 por comunicação serial. O mesmo núcleo de aplicação pode ser utilizado pela interface de terminal (CLI) ou pela API REST com interface Web React. É possível selecionar canais, controlar vazão e sentido da bomba, editar receitas hierárquicas e executar protocolos temporizados com acompanhamento em tempo real.

O projeto está funcional e já foi testado com os dispositivos físicos.

Para dar continuidade ao desenvolvimento, consulte o [Guia de desenvolvimento](docs/GUIA_DESENVOLVIMENTO.md). O arquivo [OpenAPI de referência](docs/api/openapi.yaml) descreve o contrato planejado; a documentação gerada em `/docs` pelo servidor FastAPI representa as rotas efetivamente disponíveis na versão em execução.

## Aviso sobre desenvolvimento assistido e live coding

Partes deste projeto foram construídas e revisadas de forma iterativa com técnicas de *live coding* e assistência de inteligência artificial. Esse processo acelera a prototipação, mas não garante, por si só, correção, segurança operacional ou adequação a um experimento específico.

Antes de utilizar alterações com os equipamentos reais:

- revise o código e os contratos afetados;
- execute os testes automatizados e valide primeiro em modo `--mock`;
- faça ensaios curtos e supervisionados, com líquidos e condições seguras;
- confirme portas, canais, sentido da bomba, calibração de vazão, limites e comportamento de parada;
- mantenha disponíveis os meios físicos de parada e os procedimentos de segurança da bancada.

Código gerado ou alterado durante uma sessão de live coding não deve ser colocado diretamente em operação sem revisão, versionamento e validação controlada. Este software não substitui os manuais, intertravamentos ou recomendações de segurança dos fabricantes da válvula, da bomba e dos demais equipamentos do experimento.

## Formas de utilização

| Interface | Entrada | Uso principal |
| --- | --- | --- |
| Web + API | `python -m smartpump.interfaces.api.cli` | Operação cotidiana, conexão de dispositivos, edição e execução de receitas pelo navegador. |
| Terminal interativo | `python -m smartpump` | Operação local pela CLI e diagnóstico sem navegador. |
| Execução direta | `python -m smartpump --recipe ... --execute` | Validação, automação local e testes de receitas por argumentos. |

Os comandos instalados `smartpump` e `smartpump-web` são equivalentes às duas primeiras entradas quando o projeto é instalado com `pip install -e .`.

## Início rápido em modo simulado

No Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"

cd web
npm.cmd install
npm.cmd run build
cd ..

python -m smartpump.interfaces.api.cli --mock
```

Abra `http://127.0.0.1:8000`. O modo `--mock` não abre portas seriais e acelera os tempos das receitas; ele é apropriado para desenvolvimento e demonstração sem a bomba e a válvula.

Em Linux ou Raspberry Pi, use `python3`, `python3 -m venv .venv`, `source .venv/bin/activate` e `npm` no lugar de `py -3`, do script de ativação do PowerShell e de `npm.cmd`.

## Funcionalidades

- Consulta de firmware, canal atual e estado da válvula (`READY` ou `BUSY`).
- Seleção de canal pelo menor percurso, com preferência pelo sentido horário em caso de empate.
- Confirmação do canal após o movimento.
- Homing manual para referenciar a válvula no canal 1, mediante confirmação do operador.
- Receitas com execução única, número definido de ciclos ou repetição contínua.
- Carregamento, validação e execução de receitas externas em JSON pela CLI.
- Catálogo dinâmico que descobre novas receitas em `recipes/` sem reiniciar a aplicação.
- Blocos de repetição independentes e aninháveis dentro das receitas.
- Herança de vazão da receita para blocos e etapas, com sobrescrita no nível mais específico.
- Vazão opcional por etapa, convertida automaticamente em RPM pela calibração `6,4/0,4`.
- Exibição do tempo restante da etapa e, para um número finito de ciclos, do tempo total restante.
- Controle remoto opcional da bomba, com pausas configuráveis antes da movimentação da válvula e antes da retomada do bombeamento.
- Controle manual da bomba por vazão com sinal: positivo para giro horário, negativo para anti-horário e zero para parar; o ajuste direto de RPM permanece disponível como opção avançada.
- Opção de parar a bomba ao concluir normalmente uma receita.
- Modo simulado completo para usar a interface, a válvula, a bomba e as receitas sem nenhum hardware conectado.
- API REST local com documentação OpenAPI interativa, confirmações temporárias e proteção idempotente para comandos físicos.
- Interface Web integrada para conectar dispositivos, controlar a bancada, editar receitas e acompanhar pausa, retomada e interrupção.

## Organização do projeto

```text
smartpump/
├── application/              # SmartPump e casos de uso
├── domain/                   # modelo, validação e compilação de receitas
├── ports/                    # contratos tipados dos dispositivos e persistência
├── infrastructure/
│   ├── drivers/              # Cavro, ISM832, loader e dispositivos simulados
│   └── recipes/              # persistência JSON validada e atômica
├── interfaces/               # CLI e apresentação no terminal
├── settings.py               # parâmetros dos dispositivos e receita padrão
└── __main__.py               # entrada para python -m smartpump
tests/                        # testes automatizados
tools/                        # utilitários manuais de diagnóstico
docs/                         # documentação de arquitetura e planejamento
recipes/                      # receitas externas disponíveis para operação
web/                          # interface Web React/Vite e pacote para publicação
```

`README.md`, `.gitignore` e `pyproject.toml` permanecem na raiz por serem arquivos convencionais de documentação e configuração do projeto.

## Camada de aplicação

`SmartPump` é o ponto de entrada das operações da máquina. A interface de terminal não recebe instâncias de `CavroValve` ou `FlowPumpController`; ela chama métodos como `select_channel()`, `set_pump_flow_rate()`, `activate_recipe()` e `run_active_recipe()`.

```text
interfaces/cli.py (composição)
        |
        +--> interfaces/console.py
        |             |
        |             v
        +------> application/SmartPump
                       |
                       +--> ports/ValveController
                       +--> ports/PumpController
                       +--> ports/RecipeRepository
                                      |
                                      +--> infrastructure/*
```

O serviço emite objetos `SmartPumpEvent` para progresso, mudanças de estado e resultados. A CLI converte esses eventos em texto. Isso mantém as regras operacionais independentes de `input()` e da apresentação, permitindo que outra interface seja adicionada no futuro sem duplicar a coordenação dos equipamentos.

As dependências do serviço são fornecidas no construtor. Em produção são usados os drivers seriais; no modo `--mock`, são usados dispositivos em memória. A API executa receitas em uma thread controlada, publica seu progresso e aceita pausa, retomada e interrupção cooperativas sem expor os drivers diretamente à interface. Durante a pausa, o tempo da etapa fica congelado e a bomba controlada é parada até a retomada.

### Contratos tipados

Os contratos `ValveController`, `PumpController` e `RecipeRepository` estão em `smartpump/ports/`. Eles utilizam `typing.Protocol`, portanto drivers reais, mocks e futuras implementações não precisam herdar de uma classe-base: basta implementarem a assinatura declarada. O atributo `SmartPump._pump` é tipado como `Optional[PumpController]`, permitindo que IDEs e verificadores estáticos conheçam métodos como `stop()`, `restart()`, `set_flow_rate()` e `validate_flow_rate()`.

### Persistência preparada para API

`FileRecipeRepository` oferece leitura, descoberta, criação, atualização e exclusão de receitas JSON. As gravações validam toda a receita, restringem o identificador à pasta configurada e usam troca atômica do arquivo. Cada documento recebe uma revisão SHA-256; `update_recipe()` aceita `expected_revision` para rejeitar alterações concorrentes sobre uma versão antiga. Essas operações são expostas pelo `SmartPump` e pelos endpoints `/api/v1/recipes`, usando `ETag`/`If-Match` na edição e exclusão.

Editar um documento persistido não altera a receita ativa nem uma execução em andamento. Para executar a nova definição, ela precisa ser carregada e ativada explicitamente.

## Interface Web

A interface React em `web/` oferece:

- página **Operar** com comandos de bancada, receita carregada, mapa hierárquico, etapa atual e controles de início, pausa, retomada e interrupção;
- feedback de iteração, ciclo, vazão, canal, sentido e progresso;
- controles manuais bloqueados de forma explicativa durante a execução;
- biblioteca para criar, duplicar, editar, salvar, excluir e carregar receitas com etapas e loops aninhados;
- página **Dispositivos** para descobrir portas seriais, conectar e desconectar válvula e bomba;
- layout responsivo para desktop e telas menores.

A página usa `/api/v1` para consultar estado, editar receitas, executar protocolos e controlar os dispositivos. A mesma aplicação FastAPI serve `web/dist/client`, portanto não é necessário manter outro servidor Web em produção.

O editor ainda não possui reordenação: não é possível mover uma etapa para cima/baixo ou transferi-la entre a raiz e um loop. Importação/exportação, histórico persistente e configurações operacionais completas também permanecem no backlog descrito no [Guia de desenvolvimento](docs/GUIA_DESENVOLVIMENTO.md).

### Web integrada para uso local

Compile o frontend e inicie a API em modo simulado:

```powershell
cd web
npm.cmd install
npm.cmd run build
cd ..
python -m smartpump.interfaces.api.cli --mock
```

Abra:

- aplicação: `http://127.0.0.1:8000`;
- documentação interativa da API: `http://127.0.0.1:8000/docs`;
- esquema OpenAPI gerado: `http://127.0.0.1:8000/openapi.json`.

Para usar o hardware, omita `--mock`:

```powershell
python -m smartpump.interfaces.api.cli
```

Se a porta padrão da válvula não existir ou a conexão falhar, o servidor continua ativo e informa o estado desconectado. Use a página **Dispositivos** para escolher uma das portas descobertas e conectar. A bomba não é iniciada automaticamente.

Opções úteis do servidor:

```text
--host 127.0.0.1       endereço de escuta; use 0.0.0.0 somente em rede controlada
--port 8000            porta HTTP
--mock                 usa dispositivos em memória e não abre portas seriais
--time-scale 0.01      acelera receitas no modo mock
--valve-port COM22     porta inicial da válvula
--pump-port COM21      porta inicial da bomba
--recipes recipes      diretório do catálogo de receitas
--web-dist CAMINHO     build Web servido pela API
--api-only             inicia a API sem exigir ou servir o build Web
```

### Web em modo de desenvolvimento

Use dois terminais. No primeiro, inicie apenas a API simulada:

```powershell
python -m smartpump.interfaces.api.cli --mock --api-only
```

No segundo, inicie o Vite:


```powershell
cd web
npm.cmd install
npm.cmd run dev
```

Abra `http://127.0.0.1:5173`. O servidor Vite encaminha `/api` para `http://127.0.0.1:8000`, mantendo a interface ligada à API real durante o desenvolvimento. Alterações em `web/src/` são recarregadas automaticamente.

Para usar outra porta no backend durante o desenvolvimento, ajuste `server.proxy` em `web/vite.config.mjs` ou preserve a API na porta `8000`.

### Validação do frontend

```powershell
cd web
npm.cmd run test:render
npm.cmd run build
npm.cmd run test:sites
```

## API REST implementada

Todas as rotas usam o prefixo `/api/v1`:

| Grupo | Recursos atuais |
| --- | --- |
| `/status` | Estado consolidado dos dispositivos e da execução atual. |
| `/serial-ports` | Descoberta das portas seriais disponíveis. |
| `/devices/{device}` | Conexão e desconexão de `valve` e `pump`. |
| `/recipes` | Listagem, criação, leitura, prévia, atualização com `If-Match` e exclusão. |
| `/control` | Preparação de confirmações e comandos manuais da válvula/bomba. |
| `/runs` | Início, listagem, consulta, pausa, retomada e interrupção de execuções. |

Comandos físicos exigem um token temporário obtido em `/control/confirmations`. Ações que aceitam `Idempotency-Key` não são repetidas quando a mesma chave e o mesmo conteúdo são reenviados durante o processo atual.

Confirmações, chaves de idempotência e histórico de execuções ainda ficam em memória. Reiniciar o servidor perde esses registros; persistência e recuperação fazem parte das próximas etapas do [Guia de desenvolvimento](docs/GUIA_DESENVOLVIMENTO.md).

## Requisitos e instalação

- Python 3.10 ou superior.
- Node.js 18 ou superior e npm para compilar ou desenvolver a interface Web.
- Acesso a uma porta serial para cada dispositivo no modo hardware.
- Válvula Cavro e bomba Ismatec ISM832 são opcionais no modo `--mock`.

As dependências Python declaradas em `pyproject.toml` incluem FastAPI, Uvicorn e pySerial. Instale o projeto a partir da raiz:


```powershell
python -m pip install -e .
```

Para desenvolvimento e testes da API:

```powershell
python -m pip install -e ".[test]"
```

Para instalar as dependências Web:

```powershell
cd web
npm.cmd install
```

## Configuração

`smartpump/settings.py` contém os padrões usados pela CLI e na tentativa inicial de conexão do servidor Web. Na interface Web, as portas podem ser escolhidas e reconectadas em **Dispositivos** sem reiniciar o processo. Os demais parâmetros ainda são definidos no código; persistência e aplicação revisionada de configurações permanecem como evolução planejada.

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

As duas conexões utilizam 8 bits de dados, sem paridade, 1 bit de parada e timeout de leitura de 1 segundo. Na CLI, a porta da bomba só é aberta ao habilitar seu controle remoto. No servidor Web em modo hardware, a válvula tenta conectar na inicialização e a bomba é conectada pela página **Dispositivos**; falhas iniciais não impedem o servidor de subir.

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

O canal deve estar entre `1` e `VALVE_CHANNEL_COUNT`. A identificação da solução é um rótulo exibido no terminal. A duração é expressa em minutos e aceita valores fracionários. As alterações em `smartpump/settings.py` são carregadas na próxima inicialização do programa.

### Receita externa em JSON

Uma receita pode ser mantida fora do código e carregada com `--recipe`:

```json
{
  "schema_version": 1,
  "name": "Lavagem com bloco repetido",
  "description": "Exemplo de ciclos independentes e herança de vazão.",
  "cycles": 2,
  "flow_rate_ml_min": 1,
  "steps": [
    {
      "name": "Lavagem rápida",
      "cycles": 3,
      "flow_rate_ml_min": 2,
      "steps": [
        {
          "channel": 1,
          "solution": "H2O",
          "duration_minutes": 0.5
        },
        {
          "channel": 3,
          "solution": "H2O em baixa vazão",
          "duration_minutes": 0.25,
          "flow_rate_ml_min": 0.5
        }
      ]
    },
    {
      "channel": 2,
      "solution": "PBS",
      "duration_minutes": 1
    }
  ]
}
```

Um item de `steps` pode ser uma etapa concreta, identificada por `channel`, ou um bloco, identificado por outro array `steps`. Blocos podem ser aninhados em até 20 níveis e possuem `cycles` próprio. O `cycles` da raiz ainda aceita um inteiro positivo ou `null` para execução contínua; em blocos internos ele deve ser um inteiro positivo, pois um loop interno contínuo impediria a receita de avançar.

`flow_rate_ml_min` pode aparecer na raiz, em qualquer bloco ou na etapa concreta. Quando omitido, o valor é herdado do nível superior. O nível mais interno tem precedência: no exemplo, o primeiro canal usa `2 mL/min`, o segundo usa `0,5 mL/min` e a etapa PBS usa `1 mL/min` herdado da raiz. Um valor explícito `null` também sobrescreve a herança e significa manter a velocidade e o sentido já configurados ao iniciar a bomba. O valor `0` para a bomba durante aquela etapa.

Cada etapa concreta exige canal válido, solução não vazia e duração positiva. Vazões positivas giram a bomba no sentido horário e vazões negativas no sentido anti-horário.

A aplicação converte o módulo da vazão usando `RPM = |vazão| × (6,4 / 0,4)`, ou seja, `16 RPM/(mL/min)`. Quando o controle da bomba está ativo, todas as vazões não nulas são convertidas e verificadas contra a faixa de 1,60 a 160,00 RPM da ISM832 antes de qualquer movimento. Com essa calibração, os módulos operacionais ficam entre `0,1` e `10 mL/min`, e `-0,4 mL/min` corresponde a `6,4 RPM` no sentido anti-horário. Em cada etapa, a aplicação para a bomba se necessário, seleciona o canal e então aplica sentido, velocidade e partida; vazão zero mantém a bomba parada. Se a bomba estiver parada no início de uma execução pelo menu, o operador escolhe se deseja controlá-la; ao recusar, a receita continua somente com a válvula e não aplica vazões.

A validação rejeita campos desconhecidos, vazões não numéricas ou não finitas, blocos vazios, ciclos internos não finitos, mais de 10.000 etapas executáveis após a expansão dos blocos e execuções finitas com duração superior a sete dias. A compatibilidade do módulo da vazão com os limites de RPM é responsabilidade do controlador da bomba. Os blocos são compilados em um plano de execução linear validado antes de qualquer acesso ao hardware.

Os arquivos `*.json` colocados diretamente em `recipes/` são descobertos durante a execução. Abra a opção `7` do menu principal para reler a pasta, ou pressione `R` dentro do catálogo para atualizar novamente. Uma receita nova ou modificada pode ser selecionada sem encerrar a aplicação. Arquivos inválidos são ignorados como opções de execução e aparecem acompanhados do erro de validação.

## Interface de terminal (CLI)

Na pasta do projeto, abra o menu interativo com:

```powershell
python -m smartpump
```

Se o projeto foi instalado em modo editável, o comando `smartpump` produz o mesmo resultado. Consulte todos os argumentos com `python -m smartpump --help`.

Também estão disponíveis os modos externos:

```powershell
# Validar e resumir sem abrir portas seriais
python -m smartpump --recipe recipes/channel_wash.json --validate-only

# Carregar a receita no menu interativo
python -m smartpump --recipe recipes/channel_wash.json

# Sobrescrever a quantidade de ciclos do arquivo
python -m smartpump --recipe recipes/channel_wash.json --cycles 3

# Executar diretamente, ainda solicitando confirmação no terminal
python -m smartpump --recipe recipes/channel_wash.json --execute

# Controlar a bomba na execução direta e pará-la ao final
python -m smartpump --recipe recipes/channel_wash.json --execute --control-pump

# Execução automatizada; --yes é a confirmação explícita da CLI
python -m smartpump --recipe recipes/channel_wash.json --execute --control-pump --yes
```

Use `--continuous` no lugar de `--cycles` para ciclagem contínua. Os argumentos da CLI prevalecem sobre `cycles` do JSON. `--control-pump` e `--yes` só são aceitos com `--execute`. Sem `--recipe`, a aplicação continua usando `RECIPE` de `smartpump/settings.py`.

O programa abre a conexão com a válvula, consulta seu firmware e apresenta o canal atual. Após essa verificação, mostra o menu principal. O controle remoto da bomba começa desativado.

### Modo simulado (sem bomba e sem válvula)

Use `--mock` para executar a mesma interface com dispositivos mantidos apenas em memória. Nesse modo nenhuma porta `COM` é aberta, e as operações simuladas aparecem no terminal com o prefixo `[MOCK]`.

```powershell
# Abrir o menu completo sem hardware
python -m smartpump --mock

# Abrir uma receita externa no menu simulado
python -m smartpump --mock --recipe recipes/channel_wash.json

# Executar diretamente, incluindo o controle simulado da bomba
python -m smartpump --mock --recipe recipes/channel_wash.json --execute --control-pump --yes

# Usar outra aceleração: 1 minuto da receita = 0,06 segundo real
python -m smartpump --mock --time-scale 0.001 --recipe recipes/channel_wash.json --execute --yes
```

O padrão do modo mock é `--time-scale 0.01`: cada minuto programado leva 0,6 segundo real. Um fator `1` conserva os tempos originais. `--time-scale` só é aceito junto com `--mock`, evitando acelerar por engano uma execução com equipamentos reais.

O catálogo dinâmico também funciona no modo simulado. Assim, é possível adicionar ou alterar arquivos em `recipes/`, atualizar a opção `7` e testar a seleção sem reiniciar o programa. A simulação valida o fluxo do software, as receitas e os comandos do operador, mas não substitui a validação física de comunicação, sentido da válvula, calibração ou vazão.

### Menu principal

| Opção | Ação |
| --- | --- |
| `1` | Mostrar a receita e preparar sua execução automática. |
| `2` | Entrar no controle manual da válvula. |
| `3` | Mostrar as etapas e o tempo programado da receita. |
| `4` | Solicitar o homing da válvula. |
| `5` | Habilitar ou desabilitar o controle remoto da bomba. |
| `6` | Abrir o controle manual da bomba. |
| `7` | Descobrir e selecionar uma receita do catálogo dinâmico. |
| `Q` | Encerrar o programa. |

Para usar a bomba integrada à válvula, selecione a opção `5` e responda `s`. Essa ação abre a conexão da bomba; a partida ocorre na retomada após uma troca efetiva de canal. Se o carregamento falhar, a interface informa o erro e mantém o controlador anterior, caso exista.

### Controle manual da bomba

Depois de habilitar o controle remoto na opção `5`, use a opção `6` para controlar a bomba. A ação principal solicita diretamente uma vazão entre `-10` e `+10 mL/min`: `+` seleciona o sentido horário, `-` seleciona o anti-horário e `0` para a bomba. Vírgula e ponto decimal são aceitos. Identificação, estado, partida, parada, consulta de velocidade e configuração avançada em RPM continuam disponíveis.

Ao trocar o canal da válvula pelo controle manual, a aplicação preserva o estado anterior da bomba: uma bomba parada permanece parada; uma bomba em funcionamento é parada durante o movimento e reiniciada em seguida. Se o estado da bomba não puder ser determinado, a troca é bloqueada por segurança.

### Execução automática

1. Selecione a opção `1` no menu principal.
2. Escolha executar uma vez, executar um número inteiro positivo de ciclos ou executar continuamente. O modo contínuo solicita uma confirmação adicional.
3. Se o controle remoto da bomba estiver habilitado, escolha se ela deve parar ao final da receita.
4. Pressione `Enter` para iniciar ou digite `Q` para cancelar.

Em cada etapa, o programa seleciona e confirma o canal e então inicia a contagem do tempo da solução. Ao terminar a etapa, passa à próxima tupla de `RECIPE`. Ao terminar um ciclo, repete a sequência conforme o modo escolhido.

Durante a receita, `Ctrl+C` interrompe a execução e abre a confirmação de saída descrita abaixo. Se a saída for cancelada, a interface retorna ao menu principal. A válvula permanece no canal em que estiver. A opção de parar a bomba ao final é aplicada após a conclusão normal da receita; ela não é executada pelo tratamento de interrupções ou de erros.

Em qualquer tela ou operação, `Ctrl+C` é tratado como uma solicitação de saída. A aplicação só encerra após uma confirmação explícita. Se a saída não for confirmada, a operação corrente é cancelada e a interface retorna ao menu principal; durante a inicialização, a comunicação é reiniciada. Pressionar `Ctrl+C` novamente na própria pergunta de confirmação não encerra o processo.

### Controle manual

| Comando | Ação |
| --- | --- |
| `1` a `6` | Selecionar um canal na configuração atual. |
| `p` | Consultar o canal atual. |
| `s` | Consultar o estado da válvula e seu código de erro. |
| `h` | Solicitar o homing. |
| `m` | Retornar ao menu principal. |
| `q` | Encerrar o programa. |

As trocas manuais de canal consultam primeiro o estado da bomba. Se ela estiver funcionando, utilizam a parada e a retomada; se estiver parada, fazem apenas o movimento da válvula.

### Homing

O homing é uma operação manual, disponível no menu principal e no controle manual. Após a confirmação, envia `w1,0R`, aguarda a válvula ficar pronta e consulta o canal reportado para verificar a referência no canal 1. Essa operação nunca é chamada automaticamente na inicialização ou na execução da receita.

O homing chama diretamente o controlador da válvula e não utiliza os callbacks de parada e retomada da bomba empregados nas trocas de canal.

## Coordenação entre a válvula e a bomba

A seleção de canal está concentrada em `CavroValve.select_channel()`, que recebe callbacks opcionais para antes e depois do movimento. O controle manual preserva o estado anterior da bomba. Nas receitas, após a troca de canal, a vazão assinada determina o sentido, a velocidade e se a bomba deve partir ou permanecer parada.

Quando o canal solicitado difere do atual, a sequência é:

1. Calcular o menor percurso entre os canais.
2. Chamar `stop()` da bomba, se houver um controlador habilitado. Ao receber `*`, o método aguarda o atraso de parada configurado.
3. Enviar o comando de movimento da válvula.
4. Consultar o estado até `READY`, com limite de espera de 10 segundos, e confirmar o canal de destino.
5. Chamar `restart()` da bomba, se habilitada, aguardando o atraso configurado antes de enviar a partida.

Se o canal já estiver selecionado, o método retorna sem movimentar a válvula e sem chamar os callbacks da bomba. Na execução automática, a retomada envia uma partida após cada troca. No controle manual, a retomada só é configurada quando a bomba estava em funcionamento antes do movimento.

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
| `set_clockwise()` | `J` | Configura o giro no sentido horário. |
| `set_counterclockwise()` | `K` | Configura o giro no sentido anti-horário. |
| `restart()` | `H` | Aguarda o atraso de retomada e chama `start()`. |
| `shutdown()` | `I` | Chama `stop()` para parar o bombeamento ao final da receita. |
| `is_running()` | `E` | Interpreta `+` como em funcionamento, `-` como parada e outras respostas como estado desconhecido (`None`). |
| `get_speed()` | `S` | Converte a velocidade recebida para um número em rpm ou retorna `None` se a conversão falhar. |
| `set_speed(rpm)` | `Sdddddd` | Valida a faixa da ISM832, converte RPM em centésimos com seis dígitos e considera `*` uma confirmação de sucesso. |
| `set_flow_rate(ml_min)` | `I`, `J`/`K`, `Sdddddd`, `H` | Interpreta o sinal, para com segurança, configura sentido e RPM e inicia; o valor zero envia apenas a parada quando necessária. |
| `close()` | — | Fecha a conexão serial, caso esteja aberta. |

As operações manuais estão disponíveis na opção `6` do menu principal. Nas receitas externas, o operador informa vazão em mL/min; o RPM é um detalhe interno da integração com a bomba.

## Testes e verificações

Na raiz do projeto:

```powershell
python -m unittest
python -m compileall smartpump tests
```

No frontend:

```powershell
cd web
npm.cmd run test:render
npm.cmd run build
npm.cmd run test:sites
```

Os testes automatizados cobrem domínio de receitas, coordenação dos drivers, modo mock, proteção de `Ctrl+C`, persistência JSON, API, confirmações, idempotência e execução em segundo plano. Eles não substituem a validação em bancada com a versão integrada.

## Encerramento

Ao sair, a aplicação fecha as conexões seriais. A conexão da bomba é aberta em duas fases para que uma interrupção durante a inicialização possa fechá-la de forma determinística. O controlador ativo é reutilizado em vez de tentar abrir novamente a mesma porta, e o objeto do pySerial só é descartado depois que `close()` confirma o estado fechado.

Fechar a conexão da bomba ou desabilitar seu controle remoto não envia um comando de parada. A parada ao final da receita depende da opção escolhida antes de sua execução e da conclusão normal dos ciclos programados.
