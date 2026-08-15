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
substituídas por reformulações.

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
perfil do utilizador. O modelo OpenAI predefinido é `gpt-5.6-terra`; pode ser
alterado através de `COERIA_OPENAI_MODEL`.

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
Os recursos que falham a validação final de qualidade são também reformulados
automaticamente até ao limite `COERIA_RESOURCE_QUALITY_MAX_REVISIONS`.

O ciclo gerador–crítico é controlado por `COERIA_AGENTIC_CRITIC_ENABLED`,
`COERIA_AGENTIC_CRITIC_STAGES` e `COERIA_AGENTIC_MAX_REVISIONS`. A crítica é
estruturada, fica registada nos metadados e no rasto de auditoria, e não bloqueia
nem aprova a etapa em nome do docente. Desativar o crítico reduz chamadas e
custos sem alterar o fluxo de aprovação humana.

As antigas variáveis `AGIR_SOLO_*` e `PRISM_*` continuam a ser reconhecidas como
fallback para não quebrar instalações existentes; quando coexistem, prevalece a
variável `COERIA_*`.

Os conteúdos introduzidos e os artefactos anteriores necessários a cada etapa
são enviados exclusivamente ao fornecedor selecionado. A chave, os prompts
completos e o conteúdo dos ficheiros não são escritos nos registos locais.

## Instalação e execução

Depois de concluída a instalação, no Windows pode iniciar a aplicação com um
duplo clique em `Arrancar_CoerIA.bat`, localizado na pasta principal do
projeto. O ficheiro valida o ambiente virtual e a chave da API, inicia o
servidor e abre automaticamente a interface no navegador.

A partir da pasta `Aplicacao`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe app.py
```

A interface é iniciada localmente e não ativa partilha pública. Os testes usam
um agente determinístico, não necessitam de chave e não consomem a API.
O BAT define explicitamente `COERIA_AUTH_MODE=disabled`, pelo que os códigos de
acesso não são pedidos nesta execução exclusivamente local.

A interface utiliza NiceGUI e organiza o trabalho em ecrãs orientados: dados
iniciais, autoria por etapa, validação final, histórico e rastreabilidade. O
botão do cabeçalho termina apenas a sessão autenticada. No arranque local, o
servidor é terminado na consola com `Ctrl+C` ou fechando a respetiva janela.

### Acesso na instalação pública

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
