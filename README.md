# CoerIA — Do programa da UC aos recursos educativos alinhados

**Sistema de IA com agentes para elaboração de programas de unidades
curriculares e recursos educativos pedagogicamente alinhados.**

O CoerIA apoia a transformação dos dados de uma unidade curricular ou ação de
formação num programa completo e num conjunto de recursos educativos alinhados
com a taxonomia escolhida — SOLO ou Bloom. A autoria é **manual-first**: criar uma
sessão, abrir qualquer etapa, preencher campos e tabelas, guardar rascunhos e
avançar não executa um LLM nem exige uma chave de API.

A IA é facultativa e pode ser usada de duas formas independentes: verificação
não bloqueante de uma etapa ou assistência localizada numa etapa, tabela, linha
ou campo escolhido pelo docente. A assistência produz sempre uma proposta com o
valor atual e o valor sugerido diretamente nos campos e tabelas. Cada célula
alterada pode ser editada, aceite ou rejeitada; nada é aplicado antes de uma
aceitação humana explícita. A conclusão depende de uma verificação global
determinística, não de uma decisão declarada pelo modelo.

## Fluxo

1. resultados de aprendizagem com nível SOLO ou Bloom e um único verbo de ação principal;
2. conteúdos com IDs associados aos resultados formulados e objetivos gerais em texto livre;
3. atividades de ensino-aprendizagem com prática, acompanhamento e feedback;
4. tarefas e critérios de avaliação, com finalidade formativa ou sumativa;
5. organização da sequência pedagógica;
6. matriz de alinhamento;
7. recursos educativos e validação automática;
8. validação final da estrutura e do alinhamento.

Seguindo o alinhamento construtivo de Biggs e Tang em *Teaching for Quality
Learning at University*, os resultados de aprendizagem
constituem a primeira decisão pedagógica formal. Os conteúdos, documentos e
objetivos introduzidos pelo docente continuam a delimitar o contexto inicial.
Depois de os resultados serem formulados, os conteúdos podem ser estruturados e
associados a esses resultados; os objetivos gerais permanecem como texto livre.
As atividades de ensino-aprendizagem são então definidas antes das tarefas de
avaliação, que recolhem as evidências e aplicam os critérios correspondentes.
Esta sequência é uma orientação pedagógica, não uma barreira técnica: todas as
etapas permanecem navegáveis e editáveis desde o início.

O alinhamento é verificado pela correspondência entre os resultados de
aprendizagem, as atividades de ensino-aprendizagem e as tarefas e critérios de
avaliação. Os verbos dos resultados funcionam como marcadores dessa coerência.
O protótipo usa conteúdos com IDs estáveis, 4 a 10 resultados de aprendizagem
(preferencialmente 5 a 7), tipos de resultado, verbos taxonómicos controlados e
relações muitos-para-muitos. A matriz acrescenta os conteúdos a essa cadeia de
alinhamento; os recursos selecionados são posteriormente produzidos a partir dela.
A `minutaProgramasUCs.xls` não é uma
referência oficial do alinhamento ou do fluxo; permanece apenas como documento
histórico ou institucional.

O docente escolhe SOLO ou Bloom no início da sessão; as duas taxonomias nunca
são combinadas. Cada avaliação é exclusivamente formativa ou sumativa, podendo
uma UC conter apenas avaliações sumativas. O preenchimento inicial pode ser
validado localmente e, a pedido, ter todos os campos vazios preenchidos por uma
proposta editável da IA, sem substituir os dados já introduzidos pelo docente.

Durante uma operação de IA pedida explicitamente, a interface identifica o
âmbito e mostra o indicador de atividade existente e o tempo decorrido. Não é
mostrada uma percentagem artificial, pois os fornecedores não disponibilizam
progresso percentual fiável. A navegação e a edição manual não apresentam este
estado porque não contactam o fornecedor.

Na tabela dos resultados de aprendizagem e na matriz de alinhamento, a taxonomia
escolhida não é repetida como coluna. O nível é apresentado e editado através de
um seletor numerado: `SOLO 2` a `SOLO 5` ou `Bloom 1` a `Bloom 6`. Assim, a
classificação é validada logo na primeira etapa e não necessita de um ecrã
autónomo. O valor canónico continua guardado no modelo para validação e
exportação. Nas propostas da IA, o nível é canonicalizado a partir do verbo
controlado antes da validação, evitando repetir a chamada apenas por essa
divergência. Na edição manual, o seletor de verbos mostra exclusivamente os
verbos do nível escolhido na mesma linha. Os resultados usam sempre IDs no
formato `RA1`, `RA2`, …; a geração normaliza-os pela ordem das linhas e o editor
atribui automaticamente o próximo ID, sem permitir edição livre desse campo.
Biggs e Tang distinguem *Teaching/Learning Activities* e *Assessment Tasks*. Na
interface portuguesa, o CoerIA representa estes conceitos como `AE1`, `AE2`, …
(atividades de ensino-aprendizagem) e `TA1`, `TA2`, … (tarefas de avaliação).
Os prefixos são atribuídos automaticamente e tornam inequívocas as referências
apresentadas na matriz de alinhamento.

A seleção dos recursos é feita no início da etapa **Recursos educativos**. As
imagens extraídas dos documentos ficam reunidas no seletor visual de cada slide,
sem uma galeria duplicada no cartão da etapa. A matriz permanece dedicada às
relações entre resultados, conteúdos, atividades de ensino-aprendizagem e tarefas de avaliação;
os recursos são produzidos posteriormente com base nesse alinhamento.

Podem ser produzidos quatro tipos de recurso: apresentação PowerPoint, ficha de
aula, teste com chave de correção e atividade prática. As apresentações devem
integrar imagens, diagramas, tabelas, gráficos ou outros elementos visuais com
finalidade pedagógica. Na etapa **Recursos educativos**, cada tipo selecionado
tem um separador próprio tanto na consulta como na edição, evitando apresentar
slides, secções, questões e critérios numa única sequência extensa. No separador
da apresentação, a consulta integra a miniatura da imagem associada na coluna
**Modo visual**, sem repetir a proveniência, avisos técnicos ou uma galeria
separada. A edição é organizada por slide e mostra apenas
os campos pedagógicos aplicáveis. A imagem associada é escolhida numa galeria de
miniaturas; a proveniência e o identificador técnico são preenchidos
automaticamente, e a miniatura escolhida fica visível no próprio slide. A galeria
inclui todas as imagens documentais candidatas, além das imagens carregadas pelo
docente ou geradas durante a edição. O mesmo
seletor permite gerar, por pedido explícito, até duas imagens adicionais: a IA
textual pode sugerir uma instrução baseada no slide, que o docente revê antes de
usar a Image API. Também é possível carregar uma imagem do computador; essa
imagem é processada localmente e não é enviada ao LLM. Depois da aprovação final,
a aplicação exporta um ZIP com
o programa da UC, os ficheiros selecionados, matriz de alinhamento, auditoria,
manifesto e estado completo da sessão. Antes de preparar o pacote, o docente
escolhe se os documentos editáveis — programa da UC, ficha de aula, teste e
atividade prática — são incluídos em Word (`.docx`), LaTeX (`.tex`) ou em ambos
os formatos. A apresentação mantém sempre o formato PowerPoint (`.pptx`). Os
ficheiros LaTeX são documentos autónomos em UTF-8 e escapam o texto gerado ou
introduzido pelo docente para preservar uma estrutura compilável. Na instalação
da VPS, a compilação PDF pode ser ativada; nesse caso, cada `.tex` é acompanhado
pelo respetivo `.pdf`, produzido por `pdflatex` sem `shell-escape` e com limite
de tempo.

As versões, decisões, propostas de IA e respetivas decisões são guardadas em
SQLite, por predefinição em `data/prism.db`. Na instalação pública, cada sessão
fica associada ao identificador pseudónimo do docente autenticado e não é
listada nem carregada por outro participante. O nome técnico do ficheiro e o
pacote Python `prism` são mantidos temporariamente por compatibilidade com
sessões anteriores. A interface permite retomar e eliminar as próprias sessões.
Ao entrar, o docente encontra primeiro uma página inicial e escolhe explicitamente
se pretende iniciar uma nova sessão; as sessões guardadas permanecem acessíveis no
menu lateral. A configuração da nova sessão apresenta contexto, fontes e
caracterização numa única página. O tipo de formação fornece o enquadramento
anteriormente pedido como público-alvo e o semestre obrigatório inicia-se em
`1.º semestre`. O fornecedor é escolhido junto das ações facultativas de IA e a
duração total é calculada automaticamente pela soma das horas de contacto e do
trabalho autónomo. Os objetivos gerais não são pedidos nesta configuração
inicial: são formulados ou introduzidos apenas na etapa **Conteúdos e objetivos
curriculares**, evitando duplicação e mantendo essa etapa disponível para uma
primeira proposta completa por IA.

Depois de iniciar o desenho curricular, **Editar dados iniciais** permite regressar
ao mesmo formulário para corrigir a identificação, a taxonomia, o fornecedor, o
texto de base e a caracterização. As fontes documentais já incorporadas são
listadas e podem ser mantidas ou removidas; também podem ser adicionados novos
ficheiros. A gravação preserva os artefactos existentes, invalida propostas de IA
pendentes baseadas no contexto anterior e assinala as etapas preenchidas para
revisão antes de uma nova validação final.

A barra de etapas permite abrir qualquer ponto de autoria desde a criação da
sessão. A navegação não chama a IA, não exige completude e não apaga dados. Em
qualquer etapa, **Editar campos e tabelas** ativa a edição no próprio artefacto;
podem ser alterados textos, adicionadas linhas e removidas linhas. Guardar cria
uma nova versão mesmo que o rascunho ainda esteja incompleto. Se a alteração
ocorrer antes de artefactos já preenchidos, esses artefactos são preservados e
assinalados como **Rever após alterações anteriores**.
O botão de edição encontra-se no canto superior direito do cartão do conteúdo;
**Etapa seguinte** navega sem executar a IA.

**Criar etapa completa com IA** é a primeira ação apresentada na zona de IA e
pede uma proposta para toda a etapa, considerando o rascunho atual; o conteúdo
só se torna uma nova versão depois da revisão do docente. Em **Recursos
educativos**, esta ação apresenta primeiro uma confirmação explícita, porque
pode executar uma chamada por tipo de recurso e chamadas adicionais para gerar
imagens da apresentação. A proposta resultante reutiliza os mesmos separadores e
o mesmo editor da edição manual, mostra apenas os recursos selecionados e permite
ajustar o conteúdo antes de aplicar a proposta editada como uma única versão.

Depois, no bloco **Assistência com IA**, **Pedir propostas à IA** permite pedidos
dirigidos e exige a escolha prévia do âmbito e uma instrução. Para uma célula,
linha ou tabela, o fornecedor recebe um esquema de resposta
limitado exatamente a esse fragmento, sem gerar primeiro a etapa inteira. O
seletor não oferece os identificadores técnicos próprios das linhas como campos
isolados para reformulação. A proposta fica pendente até o docente comparar o
valor atual com a sugestão apresentada na própria célula. O docente pode editar,
aceitar ou rejeitar cada alteração de forma independente. Linhas novas ou a
remover são decididas como uma unidade. **Aplicar alterações aceites** reúne as
decisões numa única nova versão; rejeitar todas conserva o rascunho sem alterações.

**Verificar esta etapa com IA**, apresentada no fim do cartão, guarda um parecer
facultativo que nunca impede avançar. O parecer fica identificado pela versão dos
artefactos que analisou; depois de qualquer alteração é apresentado como
desatualizado até o docente pedir uma nova verificação. Alegações da IA sobre IDs,
cobertura ou somas não substituem nem contradizem os controlos determinísticos.

Os controlos determinísticos dos recursos são executados durante a produção e a
edição da etapa **Recursos educativos**, mas o relatório consolidado não é
apresentado nesse artefacto. O respetivo estado surge na etapa **Validação final
da estrutura e do alinhamento**, em **Qualidade automática dos recursos**, com
uma linha por controlo, estado `✅`/`⚠️`/`❌` e o respetivo detalhe. Esse relatório
é recalculado antes da validação final e da exportação, sem confiar numa cópia
anterior guardada na sessão.

Numa sessão concluída, a barra de etapas fica em modo de consulta. A reabertura
exige o botão próprio, a seleção da etapa, um motivo e uma confirmação explícita.

O card **Versões e rastreabilidade** permanece recolhido por defeito para reduzir
a carga visual da área de trabalho. Depois de aberto, o separador **Versões**
permite consultar e restaurar qualquer versão não ativa das sete etapas de
autoria. A ação de restauro surge à direita do seletor de
etapa e versão. O restauro exige apenas confirmação e volta a tornar
ativa a versão escolhida, sem criar uma nova versão nem apagar as restantes. Os
passos posteriores preenchidos ficam assinalados para revisão e a
verificação global é recalculada; o relatório final, por ser derivado, não é
restaurável.

As tabelas editáveis não acrescentam uma coluna de numeração. Os campos que
referenciam conteúdos, resultados, avaliações ou atividades de
etapas anteriores usam seletores de escolha única ou múltipla, evitando a
introdução manual de identificadores inexistentes.

A especificação completa e os critérios de aceitação encontram-se em
[`REQUISITOS.md`](REQUISITOS.md).
A decisão e o microciclo gerador–crítico estão descritos em
[`ARQUITETURA_AGENTIC.md`](ARQUITETURA_AGENTIC.md).

## Fontes aceites

É possível combinar texto direto com vários ficheiros `.txt`, `.md`, `.tex`,
`.pdf`, `.docx` e `.pptx`. O limite predefinido é 12 MB por ficheiro e o limite
absoluto de ingestão é 2 000 000 de caracteres no conjunto das fontes. A criação
da sessão conserva o texto extraído e não o envia a um fornecedor, mesmo acima do
orçamento normal de 120 000 caracteres; nesse caso, o estado regista que uma
redução de contexto foi adiada. PDFs constituídos apenas por imagem necessitam
de OCR externo.

Se o docente pedir posteriormente assistência ou verificação por IA, a redução
adiada é executada antes dessa chamada. O texto original permanece preservado na
sessão e o modelo recebe a versão reduzida.

O CoerIA extrai o conteúdo textual destes documentos e, quando aplicável,
imagens internas de `.pdf`, `.docx` e `.pptx`, conservando a proveniência
documental disponível. Nos PDFs, todas as páginas são examinadas antes de aplicar
o limite do catálogo visual; imagens pequenas e fragmentos são filtrados, os
candidatos são normalizados para PNG/JPEG RGB e distribuídos entre páginas.
Objetos raster próximos que formem uma figura composta são renderizados como um
recorte único. Todas as imagens documentais candidatas ficam disponíveis no popup
de seleção de cada slide. Quando o fornecedor é OpenAI, as respetivas miniaturas
são também fornecidas ao modelo durante a criação da apresentação: o modelo avalia
a adequação pedagógica, pode associar uma candidata ao slide semanticamente mais
adequado e não é obrigado a usar imagens irrelevantes. Uma imagem documental
adequada tem prioridade sobre a geração de uma nova imagem por IA. A possibilidade
de gerar imagens por IA fica ativa por defeito
nas novas sessões; cada imagem gerada continua identificada e sujeita à revisão e
aprovação do docente. Os bytes gerados são validados pelo Pillow e qualquer
fallback para diagrama é apresentado como aviso explícito. Durante a edição da
apresentação, o docente pode ainda carregar uma imagem isolada a partir do seu
computador; esta é processada localmente e não é enviada ao LLM.

## Configuração do fornecedor de IA

O docente escolhe **OpenAI** ou **IAedu** antes de iniciar cada sessão. O
fornecedor fica associado à sessão, mas não é contactado durante a criação,
navegação ou edição manual. Uma chave só é necessária quando o docente pede
explicitamente uma proposta, uma verificação ou uma imagem. Defina apenas as
chaves que pretende usar fora do projeto; nunca as escreva no código ou num
ficheiro partilhado:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "a_sua_chave", "User")
[Environment]::SetEnvironmentVariable("IAEDU_API_KEY", "a_sua_chave", "User")
```

Feche e reabra o terminal depois da configuração. Basta existir a chave do
fornecedor que será usado. O BAT também lê diretamente as variáveis guardadas no
perfil do utilizador. O perfil OpenAI predefinido usa `gpt-4o-mini` em todas as
chamadas textuais da aplicação — proposta inicial, gerador pedagógico, crítico e
recursos. Esta variante já era usada nos recursos pela maior robustez no
seguimento de instruções estruturadas e passa agora a substituir `gpt-5-nano`
nas restantes etapas, privilegiando consistência com um custo ainda reduzido.
Como `gpt-4o-mini` não usa `reasoning.effort`, esse parâmetro só é enviado quando
um modelo compatível for configurado. O modelo pode ser alterado globalmente
através de `COERIA_OPENAI_MODEL`; `COERIA_OPENAI_RESOURCE_MODEL` e
`COERIA_OPENAI_CRITIC_MODEL` permanecem disponíveis apenas para substituições
específicas.

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
voltam a ser gerados. Em cada chamada, o modelo devolve apenas o conteúdo do
recurso corrente; a seleção e as estruturas vazias dos restantes recursos são
acrescentadas deterministicamente pela aplicação. Isto impede o modelo de
alterar a seleção do docente e reduz os tokens de saída. A geração de imagens
constitui uma operação posterior e separada da geração textual e estrutural da
apresentação. Esta possibilidade fica ativa por defeito nas novas sessões. As imagens
podem ser extraídas de documentos de referência ou geradas pela OpenAI Image API;
antes da exportação, o docente vê as imagens selecionadas e aprova o recurso. A
geração por IA usa `OPENAI_API_KEY` independentemente de o fornecedor pedagógico
da sessão ser OpenAI ou IAedu. Por predefinição usa `gpt-image-2`, qualidade `low`,
formato horizontal 16:9 (`1536x864`) e no máximo duas imagens por apresentação.
Fornecedor, modelo, instrução, tamanho e qualidade ficam registados no estado e no
manifesto de exportação.

Se uma chamada falhar depois de outros recursos já terem sido validados, estes
ficam guardados como rascunhos técnicos associados à mesma seleção e aos mesmos
artefactos de entrada. A tentativa seguinte reutiliza-os e retoma no recurso em
falta; uma alteração da seleção ou dos artefactos anteriores invalida
automaticamente esses rascunhos. No teste, os IDs sequenciais das questões e a
cotação total são derivados deterministicamente; o modelo continua responsável
pelo enunciado, resposta e associação de cada questão a um resultado.
Na atividade prática, a aplicação remove ligações a IDs desconhecidos, ordena
as etapas, acrescenta uma etapa explícita baseada no enunciado aprovado de cada
resultado que tenha ficado sem cobertura e normaliza proporcionalmente os pesos
positivos dos critérios para 100%. Estas correções ficam registadas nos
metadados e todo o conteúdo continua sujeito à aprovação do docente.

O gerador e o crítico são agora ações independentes. O gerador produz uma
proposta apenas para o âmbito escolhido; o crítico devolve observações sem
reescrever o artefacto. Ambas as operações ficam registadas, mas apenas a
aceitação explícita de uma proposta pode criar uma nova versão com conteúdo de
IA. As validações determinísticas permanecem independentes do modelo.

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
- `prism/source_reduction.py`: redução automática e auditável de fontes extensas;
- `prism/persistence.py`: sessões, versões e auditoria em SQLite;
- `prism/auth.py`: autenticação por código, sessão assinada e limitação de tentativas;
- `prism/exporter.py`: PowerPoint, documentos Word/LaTeX e pacote ZIP;
- `tests/`: testes do fluxo, histórico, ingestão, persistência e recursos.

## Limitações assumidas

- O docente continua responsável pela correção factual e adequação pedagógica.
- A validação automática verifica estrutura, cobertura e consistência; não
  certifica a verdade de todo o conteúdo gerado.
- A crítica por LLM é uma segunda opinião pedagógica, não uma certificação.
- Não existe publicação automática em LMS nem colaboração simultânea.
- O protótipo não executa OCR, áudio ou vídeo.
- A entrada direta de ficheiros de imagem isolados não faz parte do âmbito do
  protótipo; o docente pode acrescentá-los posteriormente ao PowerPoint editável.
  O CoerIA extrai imagens de documentos de referência e pode gerar imagens por IA
  por predefinição, mantendo proveniência e aprovação humana. Quando
  não existe uma imagem de origem controlada ou a geração falha, a apresentação
  recorre a diagramas e elementos gráficos nativos, sem inventar proveniência.

## Licença

O código do CoerIA é disponibilizado sob a licença MIT. Consulte o ficheiro
[`LICENSE`](LICENSE).
