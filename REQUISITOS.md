# Requisitos do protótipo CoerIA

Este documento consolida os requisitos da aplicação a partir dos capítulos 1 e
2 da dissertação, do diagrama `Fluxo_Aplicacao_SOLO.drawio` e do comportamento
já implementado. É a referência funcional da versão atual do protótipo.

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

- Recolher nome da unidade curricular, público-alvo e duração prevista.
- Recolher opcionalmente curso e tipo de formação, ano, semestre, CNAEF, ECTS,
  horas de contacto, trabalho autónomo, finalidades gerais e bibliografia a
  validar pelo docente.
- Aceitar texto introduzido diretamente e um ou mais ficheiros de apoio.
- Extrair texto de `.txt`, `.md`, `.tex`, `.pdf`, `.docx` e `.pptx`.
- Rejeitar ficheiros vazios, formatos não suportados e fontes excessivamente
  grandes com uma mensagem compreensível.
- Permitir escolher OpenAI ou IAedu antes de iniciar a sessão.
- Informar que o conteúdo fornecido é enviado exclusivamente ao fornecedor de
  IA selecionado durante a geração.
- Manter o fornecedor escolhido durante toda a sessão e ao retomá-la.
- Validar o preenchimento manual e apresentar sugestões sem iniciar a sessão.
- Gerar, apenas a pedido, uma proposta inicial editável por IA que preencha todos
  os campos vazios, incluindo os conteúdos programáticos, sem substituir valores
  já introduzidos pelo docente.
- Exigir a escolha exclusiva entre SOLO e Bloom; nunca combinar as duas numa sessão.

### RF02 — Fluxo pedagógico orientado por uma taxonomia

Executar, por ordem, as seguintes etapas:

1. estruturação e validação de conteúdos e objetivos gerais;
2. formulação de resultados de aprendizagem com um único verbo de ação;
3. classificação dos resultados exclusivamente por SOLO ou Bloom;
4. proposta de avaliações formativas ou sumativas;
5. design pedagógico por *backward design*;
6. proposta de atividades formativas com prática, acompanhamento e feedback;
7. validação da matriz de alinhamento;
8. geração e aprovação dos recursos educativos selecionados;
9. validação final da estrutura e do alinhamento.

Cada artefacto deve possuir um formato estruturado e identificadores estáveis
que permitam ligar temas, resultados, atividades, avaliação e recursos.

- Numerar os conteúdos com IDs estáveis.
- Numerar os objetivos gerais com IDs estáveis `OG1`, `OG2`, ...
- Formular entre 4 e 10 resultados de aprendizagem, preferencialmente 5 a 7.
- Ligar todos os resultados a conteúdos e objetivos existentes.
- Classificar o tipo de resultado e a importância da sua ligação aos conteúdos.
- Usar um único verbo pertencente ao vocabulário controlado do nível declarado.
- Na opção SOLO, não usar o nível pré-estrutural para formular resultados.
- Não estabelecer uma equivalência rígida entre níveis SOLO e Bloom.
- Permitir relações muitos-para-muitos entre conteúdos, resultados, avaliações
  e atividades formativas.
- Classificar cada avaliação exclusivamente como `Formativa` ou `Sumativa`;
  é válido existir apenas avaliação sumativa.

### RF03 — Human-in-the-loop

- Parar depois de cada etapa para decisão do docente.
- Permitir aprovação ou reformulação fundamentada.
- Permitir selecionar e reabrir qualquer etapa de autoria já alcançada, mesmo
  depois da conclusão da sessão.
- Tratar a seleção de uma etapa anterior como navegação de consulta: não alterar
  o estado, não criar uma versão e não invalidar dependências nessa operação.
- Quando estiver a consultar uma etapa anterior, permitir selecionar a caixa da
  etapa corrente para regressar ao ponto atual, com o mesmo efeito do botão
  **Voltar ao ponto atual**.
- Disponibilizar a ação **Reformular** dentro da etapa consultada e só iniciar a
  alteração depois de o docente escrever e confirmar o respetivo pedido.
- Disponibilizar edição manual estruturada em todas as etapas de autoria,
  permitindo alterar texto, adicionar linhas e remover linhas.
- Validar a edição manual antes de a persistir; ao guardar, criar uma nova
  versão, preservar a anterior e aplicar a invalidação a jusante sem chamar a IA.
- Apresentar, antes da confirmação e de qualquer chamada à IA, a nova versão a
  criar e as etapas posteriores que ficarão desatualizadas.
- Criar uma nova versão da etapa reaberta e marcar como desatualizados os
  artefactos dependentes, sem apagar as versões históricas nem a fotografia
  coerente anterior à revisão.
- Obrigar a percorrer e aprovar novamente as etapas afetadas até à validação
  final.
- Não alterar o estado persistido se a nova geração falhar.
- Apresentar a validação final num ecrã separado antes da conclusão.

### RF04 — Validação automática

- Validar o esquema e a completude de todas as respostas da IA.
- Confirmar cobertura exata e sem duplicados dos resultados de aprendizagem.
- Confirmar coerência entre a taxonomia escolhida, nível, verbo, atividades e avaliação.
- Detetar resultados com mais de um verbo de ação.
- Derivar deterministicamente o nível taxonómico do verbo aprovado e corrigir
  classificações geradas que divirjam do catálogo SOLO ou Bloom selecionado.
- Verificar a finalidade formativa ou sumativa de cada avaliação.
- Normalizar as ligações de cada avaliação, garantindo que `outcome_id` coincide
  com o primeiro elemento não vazio de `outcome_ids`.
- Verificar prática, acompanhamento e feedback nas atividades formativas.
- Calcular a matriz de alinhamento a partir dos artefactos produzidos.
- Derivar os campos factuais e o estado de cada linha da matriz a partir das
  evidências aprovadas, reservando à IA apenas a fundamentação pedagógica.
- Executar verificações determinísticas sobre os recursos finais.
- Reformular automaticamente recursos inválidos até ao limite configurado.
- Distinguir verificações aprovadas, avisos e erros bloqueantes.
- Nunca aceitar como validação automática apenas uma declaração do modelo.

### RF05 — Avaliação, atividades e recursos educativos

- Permitir avaliações formativas e sumativas, mas nunca uma finalidade mista.
- Não obrigar à existência de avaliação formativa.
- Estruturar atividades formativas com prática, acompanhamento e estratégia de feedback.
- Permitir uma seleção inicial provisória dos tipos de recursos.
- Bloquear temporariamente a seleção durante o desenvolvimento da estrutura.
- Permitir confirmar ou alterar a seleção na matriz de alinhamento, antes da sua aprovação.

Gerar efetivamente cada tipo selecionado pelo docente:

- apresentação PowerPoint;
- ficha de aula;
- teste com chave de correção;
- atividade prática com etapas, entregáveis e critérios.

Cada recurso deve indicar os resultados de aprendizagem a que está associado.
Recursos não selecionados devem permanecer vazios e não ser exportados.

A apresentação PowerPoint deve combinar texto com imagens, diagramas, tabelas,
gráficos ou outros elementos visuais pedagogicamente relevantes. Os visuais
devem ter finalidade, origem e texto alternativo identificados; os diagramas e
gráficos devem ser editáveis quando forem criados pelo sistema. Áudio, vídeo e
storyboards não fazem parte do âmbito.

As imagens raster podem ter uma das seguintes origens:

- ficheiro de imagem fornecido diretamente pelo utilizador;
- imagem extraída de um documento carregado como fonte de referência;
- imagem gerada por IA para o slide.

Para cada imagem, o estado deve guardar o tipo de origem, o identificador da
fonte e o texto alternativo. Uma imagem fornecida deve conservar o nome do
ficheiro e a origem declarada; uma imagem extraída deve conservar o nome do
documento e, quando tecnicamente disponível, a página ou o slide; uma imagem
gerada deve ser identificada como tal e conservar fornecedor, modelo e instrução
de geração. O docente deve poder rever a imagem antes da aprovação do recurso.
Não é permitido descarregar silenciosamente imagens da Web sem proveniência e
condições de utilização conhecidas.

### RF06 — Persistência, versões e rastreabilidade

- Guardar localmente em SQLite o estado completo da sessão.
- Registar data, etapa, proposta, modelo, identificador da resposta, duração,
  utilização de tokens, decisão e feedback do docente.
- Listar sessões existentes e permitir retomá-las pelo identificador.
- Preservar todas as versões geradas, incluindo as substituídas.
- Permitir consultar qualquer versão pela interface.
- Registar a versão ativa de cada etapa e as versões dos artefactos usados como
  dependências de cada nova geração.
- Identificar na interface versões ativas e artefactos desatualizados.
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
- Incluir apenas os recursos selecionados, nos formatos `.pptx` e `.docx`.
- Incluir matriz de alinhamento, rasto de auditoria, manifesto e estado JSON.
- Produzir nomes de ficheiro seguros e independentes do sistema operativo.
- Registar a exportação e a finalização da rastreabilidade na sessão.

### RF08 — Tratamento de erros

- Apresentar falhas de validação, API, ficheiros e exportação sem expor chaves
  ou dados internos sensíveis.
- Não substituir silenciosamente uma falha da API por conteúdo local.
- Permitir repetir a operação sem corromper a sessão anterior.

### RF09 — Colaboração agentic controlada

- Usar um agente especialista para produzir o artefacto da etapa.
- Submeter etapas configuradas a um crítico pedagógico independente com saída
  estruturada em avisos e problemas bloqueantes.
- Permitir uma quantidade configurável e limitada de reformulações automáticas.
- Executar as validações determinísticas fora do julgamento do crítico.
- Registar gerações, críticas, observações, tentativas e consumo agregado.
- Tratar a crítica como apoio à decisão; nunca substituir a aprovação humana.

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
- A interface utiliza português europeu e rótulos consistentes.
- O docente consegue iniciar ou retomar uma sessão sem editar ficheiros.
- O preenchimento inicial é dividido em passos curtos e orientados.
- A autoria apresenta o artefacto e a decisão docente em áreas distintas.
- O ecrã adapta-se a computador, tablet e dispositivo móvel.
- A aplicação disponibiliza uma ação explícita para terminar o servidor local.

### RNF04 — Desempenho e observabilidade

- Cada chamada externa regista duração e utilização de tokens quando fornecida
  pela API.
- Limites de fonte, tempo de chamada e tentativas são configuráveis.
- O contexto enviado a cada agente contém apenas artefactos anteriores
  necessários à etapa.
- As tentativas do ciclo agentic são limitadas e configuráveis para controlar
  latência e custo.

### RNF05 — Manutenibilidade

- Interface, domínio, agentes, fluxo, validação, ingestão, persistência e
  exportação permanecem em módulos separados.
- Regras pedagógicas determinísticas não ficam escondidas nos componentes da
  interface.

## Critérios mínimos de aceitação

- O fluxo completo termina apenas após nove aprovações humanas.
- Uma etapa anterior pode ser consultada sem modificar a sessão; uma revisão só
  começa depois da ação explícita **Reformular**, apresenta previamente o
  impacto, invalida o estado ativo a jusante e preserva versões antigas.
- Uma edição manual inválida não modifica a sessão; uma edição válida fica como
  nova versão à espera de aprovação humana.
- Uma sessão concluída pode ser reaberta e só volta ao estado concluído depois
  de todas as etapas afetadas serem novamente aprovadas.
- Todos os resultados têm classificação na taxonomia exclusiva escolhida, avaliação
  e atividade formativa.
- Cada resultado contém um único verbo de ação.
- Cada avaliação é Formativa ou Sumativa, nunca Mista.
- Todos os conteúdos estão ligados a pelo menos um resultado; todas as
  avaliações e atividades possuem IDs próprios e ligações explícitas.
- A matriz assinala incoerências sem depender da opinião declarada pelo LLM.
- Cada tipo de recurso selecionado gera um ficheiro utilizável.
- Uma sessão persistida pode ser retomada numa nova instância da aplicação.
- A aplicação funciona nos testes sem chaves de API e falha explicitamente
  quando se tenta usar OpenAI ou IAedu sem a respetiva chave.
- O pacote exportado contém recursos, matriz, auditoria e manifesto coerentes.
- O pacote exportado contém o programa da UC em português e apresentações com
  elementos visuais pedagogicamente relevantes.
- Uma apresentação pode utilizar imagens fornecidas pelo utilizador, extraídas
  das fontes documentais ou geradas por IA, mantendo proveniência, texto
  alternativo e validação humana em qualquer das três modalidades.
