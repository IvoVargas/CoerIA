# CoerIA — Do programa da UC aos recursos educativos alinhados

**Sistema de IA com agentes para elaboração de programas de unidades
curriculares e recursos educativos pedagogicamente alinhados.**

O CoerIA transforma os dados de uma unidade curricular ou ação de formação num
programa completo e, a partir da estrutura aprovada, num conjunto de recursos
educativos alinhados com a taxonomia escolhida — SOLO ou Bloom. O protótipo
mantém o docente no centro do processo: cada etapa gera uma única proposta e
fica suspensa até ser aprovada ou devolvida com feedback.

Nas etapas pedagogicamente mais sensíveis, um segundo agente atua como crítico:
revê a proposta do especialista e pode provocar uma reformulação automática
limitada. As regras determinísticas são executadas separadamente e a decisão do
docente continua a ser obrigatória e soberana.

## Fluxo

1. conteúdos e objetivos gerais com IDs;
2. resultados de aprendizagem com um único verbo;
3. classificação exclusiva por SOLO ou Bloom;
4. avaliação formativa ou sumativa;
5. design pedagógico por *backward design*;
6. atividades formativas com prática, acompanhamento e feedback;
7. matriz de alinhamento;
8. recursos educativos e validação automática;
9. validação final da estrutura e do alinhamento.

O modelo curricular segue a orientação da `minutaProgramasUCs.xls`: conteúdos
com IDs estáveis, 4 a 10 resultados de aprendizagem (preferencialmente 5 a 7),
tipos de resultado, verbos taxonómicos controlados e relações muitos-para-muitos entre
conteúdos, resultados, avaliação e atividades. A matriz acrescenta os recursos
selecionados a essa cadeia de alinhamento.

O docente escolhe SOLO ou Bloom no início da sessão; as duas taxonomias nunca
são combinadas. Cada avaliação é exclusivamente formativa ou sumativa, podendo
uma UC conter apenas avaliações sumativas. O preenchimento inicial pode ser
validado localmente e, a pedido, ter todos os campos vazios preenchidos por uma
proposta editável da IA, sem substituir os dados já introduzidos pelo docente.

Durante a geração de uma etapa, a interface identifica a etapa de destino,
apresenta a fase efetivamente reportada pelo fluxo, o indicador de atividade
existente e o tempo decorrido. Não é mostrada uma percentagem artificial, pois os
fornecedores de IA não disponibilizam progresso percentual fiável. Se uma
resposta demorar, a interface indica explicitamente que continua a aguardar o
fornecedor; nos recursos educativos, assinala que esta é normalmente a etapa
mais demorada.

Na classificação taxonómica e na matriz de alinhamento, a taxonomia escolhida
não é repetida como coluna. O nível é apresentado e editado através de um
seletor numerado: `SOLO 2` a `SOLO 5` ou `Bloom 1` a `Bloom 6`. O valor canónico
continua guardado no modelo para validação e exportação.

A seleção inicial dos recursos é provisória: fica bloqueada durante a construção
da estrutura e pode ser confirmada ou alterada na matriz de alinhamento.

Podem ser produzidos quatro tipos de recurso: apresentação PowerPoint, ficha de
aula, teste com chave de correção e atividade prática. As apresentações devem
integrar imagens, diagramas, tabelas, gráficos ou outros elementos visuais com
finalidade pedagógica. Depois da aprovação final, a aplicação exporta um ZIP com
o programa da UC, os ficheiros selecionados, matriz de alinhamento, auditoria,
manifesto e estado completo da sessão.

As versões, decisões e métricas de geração são guardadas em SQLite, por
predefinição em `data/prism.db`. Na instalação pública, cada sessão fica
associada ao identificador pseudónimo do docente autenticado e não é listada
nem carregada por outro participante. O nome técnico do ficheiro e o pacote Python `prism` são
mantidos temporariamente por compatibilidade com sessões e instalações
anteriores à adoção da identidade CoerIA. A interface permite a cada docente
retomar as respetivas sessões e consultar todas as versões, incluindo propostas
substituídas por reformulações. A barra de etapas permite abrir para consulta
qualquer ponto de autoria já alcançado, incluindo numa sessão concluída, sem
alterar o estado. Dentro dessa página, o docente pode escolher **Reformular**;
só então descreve a alteração e vê quais as etapas dependentes que ficarão
desatualizadas. Depois da confirmação, o estado coerente anterior é preservado e
a nova revisão tem de voltar a ser validada até ao fim do fluxo.

Durante a consulta, selecionar a caixa do ponto atual tem o mesmo efeito de
**Voltar ao ponto atual**. O docente também pode escolher **Editar manualmente**
em qualquer etapa de autoria: a própria área da tabela passa para modo de
edição, sem abrir uma interface separada, conservando os campos visíveis e a
respetiva ordem; as linhas podem ser adicionadas ou removidas. As relações
técnicas não apresentadas ao docente são preservadas internamente. Guardar cria
uma nova versão sem chamada à IA, depois de validação estrutural, e invalida
apenas os artefactos
posteriores dependentes.

As tabelas editáveis não acrescentam uma coluna de numeração. Os campos que
referenciam conteúdos, objetivos, resultados, avaliações ou atividades de
etapas anteriores usam seletores de escolha única ou múltipla, evitando a
introdução manual de identificadores inexistentes.

A especificação completa e os critérios de aceitação encontram-se em
[`REQUISITOS.md`](REQUISITOS.md).
A decisão e o microciclo gerador–crítico estão descritos em
[`ARQUITETURA_AGENTIC.md`](ARQUITETURA_AGENTIC.md).

## Fontes aceites

É possível combinar texto direto com vários ficheiros `.txt`, `.md`, `.tex`,
`.pdf`, `.docx` e `.pptx`. Os limites predefinidos são 12 MB por ficheiro e
120 000 caracteres no conjunto das fontes. PDFs constituídos apenas por imagem
necessitam de OCR externo.

Na versão alvo, as imagens da apresentação podem ser fornecidas diretamente
pelo utilizador, extraídas destes documentos de referência ou geradas por IA. A
extração das imagens internas dos documentos e o carregamento direto de
ficheiros de imagem ainda se encontram em implementação; a ingestão atual
extrai o respetivo conteúdo textual.

## Configuração do fornecedor de IA

O docente escolhe **OpenAI** ou **IAedu** antes de iniciar cada sessão. O
fornecedor fica associado à sessão e não é trocado durante o fluxo. Defina apenas
as chaves que pretende usar fora do projeto; nunca as escreva no código ou num
ficheiro partilhado:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "a_sua_chave", "User")
[Environment]::SetEnvironmentVariable("IAEDU_API_KEY", "a_sua_chave", "User")
```

Feche e reabra o terminal depois da configuração. Basta existir a chave do
fornecedor que será usado. O BAT também lê diretamente as variáveis guardadas no
perfil do utilizador. O perfil OpenAI predefinido privilegia o custo: usa
[`gpt-5-nano`](https://developers.openai.com/api/docs/models/gpt-5-nano), com
raciocínio `minimal`, tanto no gerador como no crítico. Este modelo suporta a
Responses API e saídas estruturadas e custa, à data desta configuração, USD 0,05
por milhão de tokens de entrada e USD 0,40 por milhão de tokens de saída. O
modelo pode ser alterado através de `COERIA_OPENAI_MODEL`.

O endpoint e o canal IAedu disponibilizados para esta aplicação já têm valores
predefinidos no código. Podem ser substituídos através de
`COERIA_IAEDU_ENDPOINT` e `COERIA_IAEDU_CHANNEL_ID`. A aplicação envia os
pedidos IAedu como `multipart/form-data`, incluindo `channel_id`, um `thread_id`
por cliente, `user_info` e `message`, e recompõe os eventos de streaming do tipo
`token`. Consulte `.env.example` para conhecer todas as opções; esse ficheiro
não é carregado automaticamente.

As respostas que cumprem o esquema JSON mas falham uma regra pedagógica ou
aritmética são reformuladas automaticamente até ao limite definido por
`COERIA_OPENAI_VALIDATION_RETRIES` (duas repetições por predefinição). Todas as
tentativas são contabilizadas nas métricas de duração e tokens.
Cada tipo de recurso selecionado é gerado e validado numa chamada separada. Se
um recurso falhar a validação de qualidade, apenas esse tipo é reformulado até
ao limite `COERIA_RESOURCE_QUALITY_MAX_REVISIONS`; os recursos já válidos não
voltam a ser gerados. A geração de imagens constitui uma operação posterior e
separada da geração textual e estrutural da apresentação.

O ciclo gerador–crítico é controlado por `COERIA_AGENTIC_CRITIC_ENABLED`,
`COERIA_AGENTIC_CRITIC_STAGES` e `COERIA_AGENTIC_MAX_REVISIONS`. A crítica é
estruturada, fica registada nos metadados e no rasto de auditoria, e não bloqueia
nem aprova a etapa em nome do docente. Por predefinição, os recursos não são
submetidos a uma chamada adicional do crítico: conservam as validações
determinísticas por tipo e a aprovação humana final. Desativar o crítico ou
reduzir as etapas abrangidas diminui chamadas e custos sem alterar o fluxo de
aprovação humana.

As antigas variáveis `AGIR_SOLO_*` e `PRISM_*` continuam a ser reconhecidas como
fallback para não quebrar instalações existentes; quando coexistem, prevalece a
variável `COERIA_*`.

Os conteúdos introduzidos e os artefactos anteriores necessários a cada etapa
são enviados exclusivamente ao fornecedor selecionado. A chave, os prompts
completos e o conteúdo dos ficheiros não são escritos nos registos locais.

## Ambiente oficial e reprodução

Durante o estudo com docentes, a utilização oficial do CoerIA é feita na
instalação HTTPS em [coeria.ivovargas.pt](https://coeria.ivovargas.pt). Os
docentes necessitam apenas de um navegador e das credenciais pseudónimas
fornecidas para o estudo; não instalam a aplicação nem disponibilizam chaves de
API próprias.

A versão 0.1.0 foi validada em Ubuntu 26.04 LTS, com Python 3.14.4. As versões
diretas das bibliotecas estão fixadas em `requirements.txt` e a reprodução
exata do ambiente Linux validado usa `requirements-vps.lock`. A instalação,
configuração, atualização, diagnóstico, backup e recuperação estão descritos
em [`deploy/README.md`](deploy/README.md). Os modelos aí incluídos não contêm
segredos.

Em produção, a autenticação é obrigatória por omissão. O servidor necessita de
`COERIA_ACCESS_FILE`, `COERIA_STORAGE_SECRET` e de um diretório persistente em
`NICEGUI_STORAGE_PATH`. O ficheiro de acessos contém apenas hashes `scrypt`; os
códigos em claro devem permanecer fora do repositório e ser distribuídos
individualmente aos participantes. Para criar um administrador e 12 docentes:

```powershell
.\.venv\Scripts\python.exe scripts\generate_access_credentials.py `
  --participants 12 `
  --hashes-out C:\tmp\coeria-access.json `
  --codes-out C:\tmp\Credenciais_CoerIA.csv
```

Os dois caminhos de saída têm de ser novos, para impedir a substituição
acidental de credenciais já distribuídas.

### Desenvolvimento e testes técnicos

A execução local não é uma modalidade suportada para os participantes. Pode ser
usada pelo investigador exclusivamente para desenvolvimento e testes. O
ambiente local validado usa Python 3.13.11:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes usam um agente determinístico, não necessitam de chaves e não
consomem APIs. A interface NiceGUI organiza o trabalho em dados iniciais,
autoria por etapa, validação final, histórico e rastreabilidade. O botão do
cabeçalho termina apenas a sessão autenticada; não encerra o serviço alojado.

## Estrutura

- `app.py`: interface NiceGUI e interações do utilizador;
- `prism/application_service.py`: casos de uso independentes da interface;
- `prism/presentation.py`: apresentação dos artefactos e versões;
- `prism/agents.py`: agentes, esquemas JSON e seleção do fornecedor;
- `prism/providers.py`: configuração e adaptador de streaming da IAedu;
- `prism/assistance.py`: validação e proposta inicial assistida;
- `prism/curriculum.py`: vocabulários SOLO/Bloom e regras do modelo curricular;
- `prism/workflow.py`: estado e fluxo LangGraph;
- `prism/quality.py`: validações determinísticas independentes do modelo;
- `prism/ingestion.py`: extração e limites das fontes documentais;
- `prism/persistence.py`: sessões, versões e auditoria em SQLite;
- `prism/auth.py`: autenticação por código, sessão assinada e limitação de tentativas;
- `prism/exporter.py`: PowerPoint, documentos Word e pacote ZIP;
- `tests/`: testes do fluxo, histórico, ingestão, persistência e recursos.

## Limitações assumidas

- O docente continua responsável pela correção factual e adequação pedagógica.
- A validação automática verifica estrutura, cobertura e consistência; não
  certifica a verdade de todo o conteúdo gerado.
- A crítica por LLM é uma segunda opinião pedagógica, não uma certificação.
- Não existe publicação automática em LMS nem colaboração simultânea.
- O protótipo não executa OCR, áudio ou vídeo.
- A entrada direta, a extração documental e a geração de imagens raster ainda
  não estão concluídas. Quando não existe uma imagem de origem controlada, a
  apresentação recorre a diagramas e elementos gráficos nativos, sem inventar
  proveniência.

## Licença

O código do CoerIA é disponibilizado sob a licença MIT. Consulte o ficheiro
[`LICENSE`](LICENSE).
