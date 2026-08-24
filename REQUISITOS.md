# Requisitos do protótipo CoerIA

Este documento consolida os requisitos da aplicação a partir dos capítulos 1 e
2 da dissertação, do alinhamento construtivo descrito por Biggs e Tang em
*Teaching for Quality Learning at University*, do diagrama
`Fluxo_Aplicacao_SOLO.drawio` e do comportamento já implementado. É a referência
funcional da versão atual do protótipo. A `minutaProgramasUCs.xls` pode ser
consultada como documento histórico ou institucional, mas não constitui uma
referência oficial para o alinhamento nem para o fluxo do CoerIA.

## Objetivo e âmbito

O CoerIA apoia docentes e formadores na elaboração do programa completo de uma
unidade curricular e, depois da sua validação, na autoria dos respetivos recursos
educativos. O processo parte dos dados de uma unidade curricular ou ação de formação, aplica
exclusivamente a Taxonomia SOLO ou a Taxonomia de Bloom aos resultados de
aprendizagem e mantém
alinhados conteúdos, atividades de ensino-aprendizagem, avaliação e recursos.
Todas as propostas geradas por IA são submetidas a validação humana.

O protótipo é uma ferramenta de apoio à decisão pedagógica. Não substitui o
docente, não certifica correção factual e não publica automaticamente os
materiais produzidos.

## Requisitos funcionais

### RF01 — Dados iniciais e fontes

- Recolher o nome da unidade curricular e o tipo de formação.
- Recolher curso, ano, CNAEF, ECTS, horas de contacto, trabalho autónomo e
  bibliografia a validar pelo docente.
- Calcular a duração total pela soma das horas de contacto e do trabalho
  autónomo, sem pedir ao docente uma duração prevista redundante.
- Tornar o semestre obrigatório, limitá-lo às opções `1.º semestre` e
  `2.º semestre` e selecionar a primeira por defeito.
- Aceitar texto introduzido diretamente e um ou mais ficheiros de apoio.
- Tratar o texto introduzido e os ficheiros como informação de referência; os
  conteúdos programáticos formais são definidos na etapa posterior aos
  resultados de aprendizagem.
- Extrair texto de `.txt`, `.md`, `.tex`, `.pdf`, `.docx` e `.pptx`.
- Rejeitar ficheiros vazios e formatos não suportados com uma mensagem compreensível.
- Para conjuntos de fontes acima do orçamento normal do contexto, permitir criar
  e editar a sessão sem executar uma redução por IA; registar que a preparação
  de contexto foi adiada.
- Apenas rejeitar quando for ultrapassado o limite absoluto de ingestão configurado.
- Permitir escolher OpenAI ou IAedu antes de iniciar a sessão.
- Apresentar a escolha do fornecedor junto das ações facultativas de assistência
  por IA, antes do preenchimento manual orientado.
- Informar que o conteúdo fornecido só é enviado ao fornecedor selecionado
  quando o docente pede explicitamente uma operação de IA.
- Manter o fornecedor escolhido durante toda a sessão e ao retomá-la.
- Validar o preenchimento manual e apresentar sugestões sem iniciar a sessão.
- Gerar, apenas a pedido, uma proposta inicial editável por IA que preencha todos
  os campos vazios, incluindo a informação de referência, sem substituir valores
  já introduzidos pelo docente.
- Não pedir objetivos gerais na criação da sessão; estes são formulados ou
  introduzidos uma única vez na etapa de conteúdos e objetivos curriculares.
- Exigir a escolha exclusiva entre SOLO e Bloom; nunca combinar as duas numa sessão.

### RF02 — Fluxo pedagógico orientado por uma taxonomia

Disponibilizar a seguinte sequência pedagógica recomendada, mantendo todas as
etapas navegáveis e editáveis:

1. formulação de resultados de aprendizagem com nível SOLO ou Bloom e um único
   verbo de ação principal;
2. estruturação de conteúdos associados aos resultados formulados
   e registo dos objetivos gerais em texto livre;
3. autoria de atividades de ensino-aprendizagem com prática, acompanhamento e feedback;
4. autoria de tarefas e critérios de avaliação, com finalidade formativa ou sumativa;
5. organização da sequência pedagógica, articulando em cada resultado o foco,
   a atividade de ensino-aprendizagem e a tarefa de avaliação;
6. matriz de alinhamento;
7. recursos educativos selecionados;
8. verificação global determinística da estrutura e do alinhamento.

O alinhamento segue Biggs e Tang: os resultados de aprendizagem são o elemento
central; as atividades de ensino-aprendizagem e as tarefas de avaliação devem
mobilizar as ações expressas nesses resultados, e os critérios de avaliação
devem permitir julgar em que medida o desempenho esperado foi atingido. A
matriz torna explícitas e verificáveis estas relações.

Cada artefacto deve possuir um formato estruturado e identificadores estáveis
que permitam ligar temas, resultados, atividades, avaliação e recursos.

- Numerar os conteúdos com IDs estáveis.
- Formular entre 4 e 10 resultados de aprendizagem, preferencialmente 5 a 7.
- Identificar os resultados exclusivamente como `RA1`, `RA2`, …; numa proposta
  completa, derivar estes IDs deterministicamente pela ordem das linhas. Na
  edição manual, apresentar o ID como campo não editável e atribuir o próximo
  número automaticamente às linhas novas.
- Identificar as atividades de ensino-aprendizagem como `AE1`, `AE2`, … e as
  tarefas de avaliação como `TA1`, `TA2`, …, localizando para português a
  distinção entre *Teaching/Learning Activities* e *Assessment Tasks* usada por
  Biggs e Tang. Atribuir estes IDs automaticamente, apresentá-los como campos não
  editáveis e conservar as respetivas referências na matriz de alinhamento.
- Usar os documentos, conteúdos e objetivos fornecidos pelo docente como contexto
  de entrada para formular os resultados, sem os transformar previamente numa
  etapa curricular formal.
- Na segunda etapa, associar cada conteúdo a um ou mais resultados formulados; o
  conjunto das associações deve cobrir exatamente todos os resultados, sem linhas
  desligadas nem IDs desconhecidos.
- Registar os objetivos gerais num único campo de texto livre, sem IDs e sem os
  incluir como relação estrutural da matriz de alinhamento.
- Classificar o tipo de cada resultado de aprendizagem.
- Usar um único verbo de ação principal pertencente ao vocabulário controlado do nível declarado; infinitivos subordinados podem ser usados em complementos, mas não como ações principais coordenadas.
- Na opção SOLO, não usar o nível pré-estrutural para formular resultados.
- Integrar a classificação taxonómica na primeira etapa, como atributo de cada
  resultado, sem criar um ecrã autónomo para a classificação.
- Nas tabelas de resultados de aprendizagem e da matriz de alinhamento, omitir a
  coluna redundante da taxonomia e mostrar o nível num seletor com designação e número:
  `SOLO 2`–`SOLO 5` ou `Bloom 1`–`Bloom 6`.
- Não estabelecer uma equivalência rígida entre níveis SOLO e Bloom.
- Permitir relações muitos-para-muitos entre conteúdos, resultados, avaliações
  e atividades de ensino-aprendizagem.
- Classificar cada avaliação exclusivamente como `Formativa` ou `Sumativa`;
  é válido existir apenas avaliação sumativa.

### RF03 — Human-in-the-loop

- Criar novas sessões em modo **manual-first**, sem executar um LLM.
- Permitir abrir qualquer etapa de autoria desde o início, sem exigir que as
  etapas anteriores estejam preenchidas ou aprovadas.
- Permitir avançar e recuar livremente sem chamar a IA, validar completude,
  criar conteúdo ou apagar artefactos.
- Disponibilizar edição manual estruturada em todas as etapas de autoria,
  transformando a tabela apresentada no próprio local e permitindo alterar
  texto, adicionar linhas e remover linhas, sem abrir um editor separado nem
  mudar os campos visíveis ou a respetiva ordem.
- Apresentar a ação **Editar campos e tabelas** no canto superior direito do
  cartão que contém o artefacto, alinhada verticalmente com o respetivo título,
  e designar a navegação para a frente como **Etapa seguinte**.
- Permitir guardar rascunhos incompletos; validar apenas a forma estrutural
  mínima necessária para a persistência.
- Não acrescentar uma coluna de numeração de linhas no modo de edição.
- Substituir a escrita manual de referências a IDs de etapas anteriores por
  seletores fechados, com escolha única ou múltipla conforme a cardinalidade.
- Ao alterar uma etapa anterior, criar uma nova versão, preservar integralmente
  o conteúdo posterior e assinalar os artefactos preenchidos a jusante para
  revisão; nunca os apagar automaticamente.
- Permitir pedir uma verificação por IA em qualquer etapa de autoria. O parecer
  deve ser guardado, não deve alterar o artefacto e nunca deve bloquear a
  navegação.
- Apresentar sempre a ação **Criar versão com IA**, ao lado de **Pedir propostas
  à IA**, para obter uma proposta completa de toda a etapa com base no contexto,
  no rascunho atual e nos artefactos anteriores. A proposta só se torna uma nova
  versão depois da revisão e aplicação explícitas pelo docente.
- Na etapa de recursos, identificar inequivocamente que essa ação gera os tipos
  de recurso selecionados, pode efetuar várias chamadas ao fornecedor e exige
  confirmação explícita antes de iniciar, incluindo o aviso sobre eventual
  geração de imagens para a apresentação.
- Permitir pedir assistência de IA apenas depois de o docente escolher o âmbito
  exato — etapa, tabela, linha ou campo — e escrever uma instrução.
- Excluir os identificadores técnicos próprios de cada linha dos âmbitos ao nível
  do campo, pois não constituem conteúdo pedagógico a reformular pela IA.
- Para um âmbito inferior à etapa, pedir ao fornecedor apenas um fragmento com o
  esquema exato da célula, linha ou tabela selecionada; não gerar a etapa inteira
  para depois extrair um índice.
- Apresentar a assistência como proposta pendente diretamente nos campos e
  tabelas existentes, colocando a sugestão sob o valor atual e sem expor o JSON
  como interface principal.
- Permitir editar, aceitar ou rejeitar independentemente cada célula alterada;
  tratar linhas novas ou propostas para remoção como decisões ao nível da linha.
- Aplicar em conjunto apenas as alterações aceites e criar uma única nova versão;
  rejeitar todas preserva o rascunho.
- Permitir restaurar uma versão não ativa de cada etapa de autoria mediante
  confirmação, sem exigir motivo e sem criar uma nova versão. O restauro altera
  apenas a versão ativa, preserva todo o histórico, assinala os passos posteriores
  para revisão e invalida a verificação global; o relatório final derivado não
  pode ser restaurado.
- Apresentar a ação de restauro à direita do seletor de etapa e versão.
- Não alterar o artefacto ativo nem persistir uma proposta parcial se a chamada à
  IA falhar.
- Apresentar a verificação global determinística num ecrã separado e torná-la a
  única barreira obrigatória à conclusão.

### RF04 — Validação automática

- Validar o esquema e a completude das propostas devolvidas pela IA antes de as
  apresentar, sem confundir essa validação com a aceitação humana.
- Aceitar rascunhos manuais incompletos durante a autoria e reservar os
  controlos bloqueantes de completude e alinhamento para a verificação global.
- Confirmar cobertura exata e sem duplicados dos resultados de aprendizagem.
- Confirmar coerência entre a taxonomia escolhida, nível, verbo, atividades e avaliação.
- Detetar resultados com mais de um verbo de ação.
- Confirmar deterministicamente a compatibilidade entre o nível e o verbo
  aprovados segundo o catálogo SOLO ou Bloom selecionado.
- Nas propostas geradas pela IA, canonicalizar o nível a partir do verbo
  controlado antes de repetir a chamada e registar a correção nos metadados.
- Canonicalizar os IDs dos resultados para `RA1`, `RA2`, … antes da validação,
  sem repetir uma chamada apenas porque o fornecedor devolveu outra notação.
- Na edição manual dos resultados, filtrar o seletor de verbo pelo nível
  escolhido na mesma linha; pares em falta ou incompatíveis devem ser
  assinalados pela verificação global.
- Verificar a finalidade formativa ou sumativa de cada avaliação.
- Normalizar as ligações de cada avaliação, garantindo que `outcome_id` coincide
  com o primeiro elemento não vazio de `outcome_ids`.
- Verificar prática, acompanhamento e feedback nas atividades de ensino-aprendizagem.
- Verificar a matriz de alinhamento relativamente aos artefactos produzidos.
- Derivar os campos factuais e o estado de cada linha da matriz a partir das
  evidências aprovadas, reservando à IA apenas a fundamentação pedagógica.
- Executar verificações determinísticas sobre os recursos finais.
- Gerar e validar separadamente cada tipo de recurso selecionado.
- Pedir ao fornecedor apenas o conteúdo do recurso corrente e derivar
  deterministicamente a seleção e os campos vazios dos restantes recursos.
- Reformular automaticamente apenas o recurso inválido até ao limite
  configurado, sem repetir os restantes recursos já válidos.
- Persistir como rascunhos técnicos os recursos já validados quando um tipo
  posterior falha e retomá-los apenas se a seleção e todas as entradas
  pedagógicas permanecerem inalteradas.
- Derivar deterministicamente os IDs sequenciais e a cotação total do teste e
  indicar explicitamente os resultados de aprendizagem em falta quando a
  cobertura estiver incompleta.
- Na atividade prática, filtrar IDs desconhecidos, ordenar as etapas,
  acrescentar uma etapa baseada no enunciado aprovado para cada resultado em
  falta e normalizar proporcionalmente os pesos dos critérios para 100%,
  registando todas as correções nos metadados.
- Distinguir verificações aprovadas, avisos e erros bloqueantes.
- Nunca aceitar como validação automática apenas uma declaração do modelo.
- Na verificação global, executar deterministicamente os validadores de todas
  as sete etapas de autoria e impedir a conclusão enquanto existir um erro.

### RF05 — Avaliação, atividades e recursos educativos

- Permitir avaliações formativas e sumativas, mas nunca uma finalidade mista.
- Não obrigar à existência de avaliação formativa.
- Estruturar atividades de ensino-aprendizagem com prática, acompanhamento e estratégia de feedback.
- Apresentar a seleção dos tipos de recursos e das imagens documentais no início
  da etapa **Recursos educativos**, antes de qualquer geração, sem repetir essa
  decisão no formulário inicial nem nas linhas da matriz de alinhamento.

Gerar efetivamente cada tipo selecionado pelo docente:

- apresentação PowerPoint;
- ficha de aula;
- teste com chave de correção;
- atividade prática com etapas, entregáveis e critérios.

Cada tipo deve corresponder a uma execução independente, com indicação do tipo
corrente e da posição no conjunto selecionado. No fim, o sistema deve validar
também o conjunto agregado antes de o apresentar ao docente.

Cada recurso deve indicar os resultados de aprendizagem a que está associado.
Recursos não selecionados devem permanecer vazios e não ser exportados.

A apresentação PowerPoint deve combinar texto com imagens, diagramas, tabelas,
gráficos ou outros elementos visuais pedagogicamente relevantes. Os visuais
devem ter finalidade, origem e texto alternativo identificados; os diagramas e
gráficos devem ser editáveis quando forem criados pelo sistema. Áudio, vídeo e
storyboards não fazem parte do âmbito.

As imagens raster tratadas pelo protótipo podem ter uma das seguintes origens:

- imagem extraída de um documento carregado como fonte de referência;
- imagem gerada por IA para o slide, possibilidade ativa por defeito nas novas
  sessões e sempre sujeita à revisão e aprovação do docente.

Para cada imagem, o estado deve guardar o tipo de origem, o identificador da
fonte e o texto alternativo. Uma imagem extraída deve conservar o nome do
documento e, quando tecnicamente disponível, a página ou o slide; uma imagem
gerada deve ser identificada como tal e conservar fornecedor, modelo, instrução,
tamanho e qualidade de geração. A extração de PDF deve examinar todas as páginas
antes de aplicar o limite do catálogo, eliminar imagens pequenas ou fragmentárias,
normalizar os candidatos para PNG/JPEG RGB, equilibrar a seleção entre páginas e,
quando objetos próximos constituam uma figura composta, preferir um recorte
renderizado da figura completa. O docente deve selecionar, através de miniaturas,
as imagens documentais que devem ser usadas antes da criação da apresentação. O
pipeline deve garantir que cada imagem selecionada é usada pelo menos uma vez num
slide de conteúdo; quando o fornecedor suporta visão, as miniaturas devem ser
fornecidas ao modelo para melhorar a associação semântica entre imagem e slide. Os
bytes devolvidos por um gerador de imagens devem ser validados
com Pillow; qualquer rejeição ou fallback para diagrama deve produzir um aviso
explícito. O docente deve poder rever a imagem antes da aprovação do recurso.
Não é permitido descarregar silenciosamente imagens da Web
sem proveniência e condições de utilização conhecidas. A entrada direta de
ficheiros de imagem isolados fica fora do âmbito do protótipo, uma vez que o
PowerPoint final permanece editável e permite ao docente acrescentar esses
ficheiros após a exportação.

### RF06 — Persistência, versões e rastreabilidade

- Guardar localmente em SQLite o estado completo da sessão.
- Registar data, etapa, proposta, modelo, identificador da resposta, duração,
  utilização de tokens, decisão e feedback do docente.
- Listar sessões existentes, permitir retomá-las e eliminar definitivamente apenas as sessões pertencentes ao utilizador autenticado, mediante confirmação explícita.
- Preservar todas as versões geradas, incluindo as substituídas.
- Permitir consultar qualquer versão pela interface.
- Registar a versão ativa de cada etapa e as versões dos artefactos usados como
  dependências de cada nova geração.
- Identificar na interface versões ativas e artefactos desatualizados.
- Manter o card de versões e rastreabilidade recolhido por defeito, sem remover o
  acesso ao histórico, ao restauro ou às decisões registadas.
- Guardar uma fotografia coerente dos artefactos e versões ativas antes de cada
  revisão em cascata.

### RF07 — Exportação

- Exportar um pacote `.zip` depois da aprovação final.
- Incluir uma versão editável, exclusivamente em português, do programa da UC,
  construída a partir dos artefactos aprovados e sem nova geração por IA.
- Incluir no programa identificação, carga de trabalho e ECTS, objetivos gerais,
  conteúdos, resultados de aprendizagem e classificação taxonómica, atividades
  de ensino-aprendizagem, avaliação, matriz de alinhamento e bibliografia
  fornecida ou validada pelo docente.
- Antes de preparar o ZIP, permitir ao docente escolher Word (`.docx`), LaTeX
  (`.tex`) ou ambos para todos os documentos textuais exportáveis: programa da
  UC, ficha de aula, teste com chave de correção e atividade prática.
- Manter a apresentação no formato PowerPoint (`.pptx`), independentemente da
  escolha dos formatos documentais.
- Produzir ficheiros LaTeX autónomos em UTF-8, com texto livre devidamente
  escapado e conteúdo equivalente ao documento Word correspondente.
- Quando a compilação PDF estiver configurada no servidor, compilar cada `.tex`
  com um template controlado, sem `shell-escape`, sem shell intermédio e com
  timeout; validar a assinatura do PDF antes de o incluir no ZIP.
- Não entregar silenciosamente um pacote parcial quando a compilação PDF estiver
  ativa mas o compilador não existir, exceder o timeout ou devolver um ficheiro
  inválido.
- Incluir apenas os recursos selecionados e registar no manifesto e na auditoria
  os formatos documentais escolhidos.
- Incluir matriz de alinhamento, rasto de auditoria, manifesto e estado JSON.
- Produzir nomes de ficheiro seguros e independentes do sistema operativo.
- Registar a exportação e a finalização da rastreabilidade na sessão.

### RF08 — Tratamento de erros

- Apresentar falhas de validação, API, ficheiros e exportação sem expor chaves
  ou dados internos sensíveis.
- Não substituir silenciosamente uma falha da API por conteúdo local.
- Permitir repetir a operação sem corromper a sessão anterior.

### RF09 — Colaboração agentic controlada

- Usar um agente especialista apenas quando o docente pede uma proposta num
  âmbito explicitamente selecionado.
- Disponibilizar um crítico pedagógico independente, acionado a pedido, com
  saída estruturada em avisos e problemas, sempre não bloqueante.
- Impedir que o gerador ou o crítico aplique alterações ao artefacto ativo sem
  aceitação humana explícita.
- Executar as validações determinísticas fora do julgamento do crítico.
- Registar propostas, âmbitos, instruções, críticas, decisões humanas,
  tentativas e consumo agregado.

## Requisitos não funcionais

### RNF01 — Segurança e privacidade

- As chaves são obtidas exclusivamente de `OPENAI_API_KEY` e
  `IAEDU_API_KEY`, consoante o fornecedor selecionado.
- Chaves, prompts completos e conteúdo dos ficheiros não são escritos em logs.
- A interface identifica o processamento externo dos dados.
- O servidor é local por predefinição e não ativa partilha pública.

### RNF02 — Reprodutibilidade

- As dependências suportadas são declaradas e limitadas por versões maiores.
- Os testes funcionam sem rede e sem consumo da API.
- O modelo, o esquema e os metadados de cada geração ficam registados.

### RNF03 — Usabilidade e acessibilidade

- A etapa, o progresso, a decisão pendente e os erros são sempre visíveis.
- Durante operações demoradas, indicar a etapa de destino, a fase de execução e
  o tempo decorrido, mantendo um único indicador indeterminado e sem inventar uma
  percentagem que o fornecedor não disponibilize.
- Durante uma espera prolongada, confirmar que a operação continua ativa e que
  a aplicação aguarda a resposta do fornecedor de IA.
- A interface utiliza português europeu e rótulos consistentes.
- A entrada na aplicação apresenta uma página inicial; o formulário de criação
  só é aberto depois de o docente escolher iniciar uma nova sessão.
- O docente consegue iniciar ou retomar uma sessão sem editar ficheiros.
- O preenchimento inicial reúne contexto, fontes e caracterização numa única
  página, com uma ação final para iniciar o desenho curricular alinhado.
- A autoria apresenta o artefacto e a decisão docente em áreas distintas.
- O ecrã adapta-se a computador, tablet e dispositivo móvel.
- A aplicação disponibiliza uma ação explícita para terminar o servidor local.

### RNF04 — Desempenho e observabilidade

- Cada chamada externa regista duração e utilização de tokens quando fornecida
  pela API.
- Limites de ingestão bruta, redução de fonte, tempo de chamada e tentativas são configuráveis.
- O contexto enviado a cada agente contém apenas artefactos anteriores
  necessários à etapa.
- As tentativas do ciclo agentic são limitadas e configuráveis para controlar
  latência e custo.
- O perfil OpenAI predefinido privilegia o menor custo compatível com a Responses
  API e saídas estruturadas, mantendo configuráveis o modelo e o esforço de
  raciocínio.
- A geração textual e estrutural dos recursos é independente da posterior
  geração de imagens.

### RNF05 — Manutenibilidade

- Interface, domínio, agentes, fluxo, validação, ingestão, persistência e
  exportação permanecem em módulos separados.
- Regras pedagógicas determinísticas não ficam escondidas nos componentes da
  interface.

## Critérios mínimos de aceitação

- Uma sessão nova permite abrir e editar todas as etapas sem executar um LLM.
- Um rascunho incompleto pode ser guardado e retomado como nova versão.
- Alterar uma etapa anterior preserva os artefactos posteriores e assinala-os
  para revisão quando contêm trabalho.
- Uma verificação facultativa da IA nunca bloqueia a passagem à etapa seguinte.
- Uma proposta da IA não modifica o artefacto antes da aceitação humana; a
  rejeição deixa o rascunho intacto.
- O fluxo completo termina apenas depois de a verificação global determinística
  confirmar a estrutura, as relações, a taxonomia e os recursos.
- Uma sessão concluída pode ser reaberta; qualquer alteração posterior exige
  repetir a verificação global antes de nova conclusão. A barra de etapas é só de
  leitura nesse estado e a reabertura exige uma ação e confirmação próprias.
- Todos os resultados têm classificação na taxonomia exclusiva escolhida, avaliação
  e atividade de ensino-aprendizagem.
- Cada resultado contém um único verbo de ação principal; infinitivos subordinados em complementos são permitidos, mas ações principais coordenadas são rejeitadas.
- Cada avaliação é Formativa ou Sumativa, nunca Mista.
- Todos os conteúdos estão ligados a pelo menos um resultado; todas as tarefas
  de avaliação usam IDs `TA<n>`, todas as atividades de ensino-aprendizagem usam
  IDs `AE<n>` e ambas possuem ligações explícitas.
- A matriz assinala incoerências sem depender da opinião declarada pelo LLM.
- Cada tipo de recurso selecionado gera um ficheiro utilizável.
- Uma sessão persistida pode ser retomada numa nova instância da aplicação.
- A aplicação funciona nos testes sem chaves de API e falha explicitamente
  quando se tenta usar OpenAI ou IAedu sem a respetiva chave.
- O pacote exportado contém recursos, matriz, auditoria e manifesto coerentes.
- A escolha Word, LaTeX ou ambos é respeitada para o programa da UC, ficha de
  aula, teste e atividade prática, sem alterar a exportação da apresentação.
- O pacote exportado contém o programa da UC em português e apresentações com
  elementos visuais pedagogicamente relevantes.
- Uma apresentação pode utilizar imagens extraídas das fontes documentais ou
  geradas por IA, mantendo proveniência, texto alternativo e validação humana em
  ambas as modalidades; ficheiros de imagem isolados podem ser acrescentados pelo
  docente ao PowerPoint editável após a exportação.
