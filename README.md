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

1. dados iniciais, fontes, caracterização da unidade curricular e objetivos
   gerais opcionais em texto livre;
2. resultados de aprendizagem com nível SOLO ou Bloom, um único verbo de ação
   principal, modo de IA e pressupostos contextuais opcionais;
3. conteúdos com IDs associados aos resultados formulados;
4. atividades de ensino-aprendizagem com prática, acompanhamento e feedback;
5. tarefas e critérios de avaliação, com finalidade formativa ou sumativa e
   associação explícita tanto às atividades de ensino-aprendizagem que as
   preparam como aos resultados cuja evidência avaliam;
6. planeamento das aulas, com duração, tipo de sessão, atividades ou tarefas de
   avaliação opcionais e um campo de texto opcional; a soma das durações deve
   corresponder exatamente às horas de contacto;
7. geração de recursos educativos e validação automática;
8. validação final da estrutura e do alinhamento.

Seguindo o alinhamento construtivo de Biggs e Tang em *Teaching for Quality
Learning at University*, os resultados de aprendizagem
constituem a primeira decisão pedagógica formal. Os conteúdos, documentos e
objetivos introduzidos pelo docente continuam a delimitar o contexto inicial.
Depois de os resultados serem formulados, os conteúdos podem ser estruturados e
associados a esses resultados; os objetivos gerais permanecem como texto livre.
As atividades de ensino-aprendizagem são então definidas antes das tarefas de
avaliação. Cada tarefa identifica as atividades que preparam o desempenho a
avaliar e os resultados avaliados diretamente, recolhe as evidências e aplica
os critérios correspondentes. O planeamento das aulas organiza depois as sessões
concretas. Pode associar-lhes atividades e tarefas quando seja útil, sem repetir
obrigatoriamente todos os componentes; a duração total deve corresponder
exatamente às horas de contacto.
Esta sequência é uma orientação pedagógica, não uma barreira técnica: todas as
etapas permanecem navegáveis e editáveis desde o início.

O alinhamento é verificado pela correspondência entre os resultados de
aprendizagem, as atividades de ensino-aprendizagem e as tarefas e critérios de
avaliação. Os verbos dos resultados funcionam como marcadores dessa coerência.
O enquadramento de Brabrand e Denny em *Constructive Alignment in the Age of AI*
acrescenta uma dimensão ortogonal: cada resultado indica `AI-off` (aprendizagem
sem IA), `AI-on` (aprendizagem com IA como meio) ou `on-AI` (aprendizagem sobre
a utilização da IA). `AI-off` é o valor por defeito. As atividades e tarefas
herdam o modo dos resultados associados; uma linha que junte resultados com
modos diferentes deve ser dividida. Esta classificação refere-se ao trabalho do
estudante e não à utilização facultativa da IA pelo CoerIA para apoiar o docente.
O protótipo usa conteúdos com IDs estáveis, 4 a 10 resultados de aprendizagem
(preferencialmente 5 a 7), tipos de resultado, verbos taxonómicos controlados e
relações muitos-para-muitos. A aplicação verifica essas relações diretamente e
produz uma síntese automática do alinhamento, sem exigir uma etapa ou matriz
editável adicional. Os recursos selecionados são posteriormente produzidos a
partir dos artefactos aprovados.
A `minutaProgramasUCs.xls` não é uma
referência oficial do alinhamento ou do fluxo; permanece apenas como documento
histórico ou institucional.

Nos dados iniciais, o CoerIA regista separadamente a classificação nacional
CNAEF e a classificação internacional **ISCED-F 2013**, ambas através de código
e designação, sem exigir correspondência entre ambas. Cada classificação é
escolhida no respetivo catálogo oficial em português e a designação é preenchida
automaticamente. A CNAEF aceita os códigos nacionais de três dígitos aprovados
pela Portaria n.º 256/2005. O ISCED-F aceita códigos existentes nos níveis geral
(dois dígitos), específico (três dígitos) e detalhado (quatro dígitos), sendo o
nível detalhado recomendado quando estiver disponível. Em ambos os seletores, a
lista apresenta o código e a designação para facilitar a pesquisa, enquanto o
valor selecionado mostra apenas o código.

O docente escolhe SOLO ou Bloom no início da sessão; as duas taxonomias nunca
são combinadas. Cada avaliação é exclusivamente formativa ou sumativa, podendo
uma UC conter apenas avaliações sumativas. O preenchimento inicial pode ser
validado localmente e, a pedido, ter todos os campos vazios preenchidos por uma
proposta editável da IA, sem substituir os dados já introduzidos pelo docente.
Para classificar essa proposta, a IA recebe as correspondências completas entre
códigos e designações; a aplicação volta a canonicalizar localmente os dois
valores e constrói a mensagem apresentada ao docente sem reutilizar designações
livres produzidas pelo modelo.

Durante uma operação de IA pedida explicitamente, a interface identifica o
âmbito e mostra o indicador de atividade existente e o tempo decorrido. Não é
mostrada uma percentagem artificial, pois os fornecedores não disponibilizam
progresso percentual fiável. A navegação e a edição manual não apresentam este
estado porque não contactam o fornecedor.

Na tabela dos resultados de aprendizagem, a taxonomia escolhida não é repetida
como coluna. O nível é apresentado e editado através de
um seletor numerado: `SOLO 2` a `SOLO 5` ou `Bloom 1` a `Bloom 6`. Assim, a
classificação é validada logo na primeira etapa e não necessita de um ecrã
autónomo. O valor canónico continua guardado no modelo para validação e
exportação. Nas propostas da IA, o nível é canonicalizado a partir do verbo
controlado antes da validação, evitando repetir a chamada apenas por essa
divergência. Na edição manual, o seletor de verbos mostra exclusivamente os
verbos do nível escolhido na mesma linha. Os resultados usam sempre IDs no
formato `RA1`, `RA2`, …; a geração normaliza-os pela ordem das linhas e o editor
atribui automaticamente o próximo ID, sem permitir edição livre desse campo.
O campo **Modo de IA** é editável na mesma tabela através de uma lista controlada
e começa em `AI-off`. Nas tabelas de atividades e tarefas, o modo é apresentado
como valor informativo herdado dos resultados selecionados, evitando repetir a
mesma decisão.
Os **Pressupostos para a formulação** surgem nesta mesma etapa como um campo
opcional. Podem registar conhecimentos prévios ou restrições contextuais que a
IA deve considerar, mas não são gerados obrigatoriamente, não fazem parte da
estrutura dos conteúdos e não impedem o avanço quando ficam vazios.
Biggs e Tang distinguem *Teaching/Learning Activities* e *Assessment Tasks*. Na
interface portuguesa, o CoerIA representa estes conceitos como `AE1`, `AE2`, …
(atividades de ensino-aprendizagem) e `TA1`, `TA2`, … (tarefas de avaliação).
Os prefixos são atribuídos automaticamente e tornam inequívocas as referências
usadas na verificação automática do alinhamento. Em cada tarefa `TA<n>`, o
docente seleciona uma ou mais atividades `AE<n>`; a aplicação confirma que elas
existem e seleciona diretamente os `RA<n>` cuja evidência a tarefa avalia. O triângulo
`RA ↔ AE`, `AE ↔ TA` e `RA ↔ TA` evita considerar um resultado avaliado apenas
porque partilha uma atividade com outro. A tabela das tarefas de avaliação é a
única que apresenta três tipos de identificador (`TA`, `AE` e `RA`), pois reúne
as duas relações necessárias no mesmo local. As restantes tabelas apresentam no
máximo dois tipos. No planeamento das aulas, cada sessão pode referenciar apenas
os componentes `AE` e `TA` que nela decorrem, mas essa associação é opcional.

A seleção dos recursos é feita no início da etapa **Geração de recursos educativos**. As
imagens extraídas dos documentos ficam reunidas no seletor visual de cada slide,
sem uma galeria duplicada no cartão da etapa. Os recursos são produzidos com
base nas relações já registadas entre resultados, conteúdos, atividades de
ensino-aprendizagem e tarefas de avaliação.

Podem ser produzidos quatro tipos de recurso: apresentação PowerPoint, ficha de
aula, teste com chave de correção e atividade prática. As apresentações devem
integrar imagens, diagramas, tabelas, gráficos ou outros elementos visuais com
finalidade pedagógica. Antes da síntese final, a apresentação inclui
automaticamente uma secção com todas as tarefas de avaliação, respetiva
finalidade, resultados abrangidos, evidências e critérios aprovados; esta secção
é repartida por vários slides quando necessário para manter a legibilidade. Na
etapa **Geração de recursos educativos**, cada tipo selecionado
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
o programa da UC — incluindo a política de utilização da IA —, os ficheiros
selecionados, síntese automática do alinhamento,
auditoria,
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
trabalho autónomo. Os **Objetivos gerais** são recolhidos neste formulário num
campo opcional de texto livre. Exprimem a finalidade ampla da unidade curricular
e permanecem distintos do **Texto de base e fontes de referência**, que fornece
apenas contexto documental. Não recebem IDs nem constituem uma ligação estrutural
do alinhamento.

Na etapa **Conteúdos curriculares**, a autoria concentra-se numa única tabela,
sem uma síntese global ou uma lista de temas duplicada. Cada linha usa **Tema**
para a designação breve e **Descrição do tema** para caracterizar, em
formulação expositiva, os conceitos, princípios, processos, aplicações e limites
da matéria. As propostas
da IA que iniciem estas descrições por verbos de ação ou de desempenho são
rejeitadas para reformulação, evitando que a tabela repita objetivos ou
resultados de aprendizagem.

Os **Dados iniciais** constituem o primeiro ponto da mesma barra de etapas. Depois
de iniciar o desenho curricular, selecionar esse ponto permite regressar ao
formulário para corrigir a identificação, a taxonomia, o fornecedor, o texto de
base e a caracterização, sem abrir uma área separada da sessão. A partir desse
formulário, os restantes pontos da barra continuam navegáveis. Se existirem
alterações por guardar, o docente escolhe explicitamente entre guardar, descartar
ou permanecer nos dados iniciais. O botão **Etapa anterior** da formulação dos
resultados também regressa a este primeiro ponto. As fontes documentais já
incorporadas são listadas e podem ser mantidas ou removidas; também podem ser
adicionados novos ficheiros. A gravação preserva os artefactos existentes,
invalida propostas de IA pendentes baseadas no contexto anterior e assinala as
etapas preenchidas para
revisão antes de uma nova validação final.

A barra de etapas permite abrir qualquer ponto de autoria desde a criação da
sessão. A navegação não chama a IA, não exige completude e não apaga dados. Em
qualquer etapa, **Editar campos e tabelas** ativa a edição no próprio artefacto;
podem ser alterados textos, adicionadas linhas e removidas linhas. Guardar cria
uma nova versão mesmo que o rascunho ainda esteja incompleto. Se a alteração
ocorrer antes de artefactos já preenchidos, esses artefactos são preservados e
assinalados como **Rever após alterações anteriores**.
Na tabela **Planeamento das aulas**, cada linha dispõe ainda de ações para subir
ou descer uma posição, permitindo reorganizar a sequência sem voltar a introduzir
os dados da aula.
Uma barra de ferramentas superior permanece visível durante a deslocação da
página e reúne o contexto da etapa, **Etapa anterior**, **Etapa seguinte**,
**Editar campos e tabelas** e as ações facultativas de IA. A edição manual fica
no grupo geral da etapa, visualmente separada da área **Assistência com IA**. No modo de edição,
a mesma barra substitui essas ações por **Cancelar edição** e **Guardar
rascunho**, evitando que os comandos necessários fiquem fora do ecrã. Ao
criar ou rever **Dados iniciais**, a mesma barra apresenta **Validar dados** como
ação local e separa **Gerar proposta inicial por IA**; o antigo bloco de ações
deixou de ser apresentado. Na validação final, conserva o regresso à etapa
anterior e identifica a verificação global obrigatória. O botão **?** abre uma
ajuda contextual que explica cada ação visível e indica quando existe utilização
de IA ou custo de API.

Ao executar **Validar dados**, a página desloca-se automaticamente para o parecer.
Os resultados são selecionáveis: cada problema ou sugestão desloca a página para
o campo correspondente e realça-o temporariamente. O controlo da carga de
trabalho realça em conjunto **Horas de contacto** e **Trabalho autónomo**. As
observações de **Verificar esta etapa com IA** usam os mesmos cartões e guardam
um destino estrutural explícito, escolhido entre os elementos existentes no
artefacto; a interface localiza a linha, slide ou secção por posição e identidade
estruturada, sem procurar correspondências parciais no texto. Pareceres antigos
sem destino válido recaem no título do conteúdo da etapa, não no cartão inteiro.
Cada cartão da barra conserva também uma cor de fundo própria para o respetivo
estado — por preencher, rascunho, verificado, concluído, pendente ou a rever — e
mantém o estado escrito. As cores são claras e distinguem-se do fundo geral da
página; o ponto atual conserva o fundo verde em gradiente já usado na seleção.

**Criar etapa completa com IA** é a primeira ação apresentada na área de IA da
barra de ferramentas e
pede uma proposta para toda a etapa, considerando o rascunho atual; o conteúdo
só se torna uma nova versão depois da revisão do docente. Em **Recursos
educativos**, esta ação apresenta primeiro uma confirmação explícita, porque
pode executar uma chamada por tipo de recurso e chamadas adicionais para gerar
imagens da apresentação. A proposta resultante reutiliza os mesmos separadores e
o mesmo editor da edição manual, mostra apenas os recursos selecionados e permite
ajustar o conteúdo antes de aplicar a proposta editada como uma única versão.
No **Planeamento das aulas**, o pedido inclui ainda um resumo explícito dos
conteúdos e das cadeias `RA → AE → TA`, o catálogo descritivo das atividades e
tarefas e as horas de contacto. A proposta distribui todos esses componentes,
usa em conjunto o rascunho existente e os artefactos anteriores, e torna o foco
curricular de cada aula visível no texto opcional.

Na mesma barra, **Pedir propostas à IA** abre um diálogo para escolher o âmbito
e escrever uma instrução sem ocupar permanentemente espaço no artefacto. Para
uma célula, linha ou tabela, o fornecedor recebe um esquema de resposta
limitado exatamente a esse fragmento, sem gerar primeiro a etapa inteira. O
seletor não oferece os identificadores técnicos próprios das linhas como campos
isolados para reformulação. A proposta fica pendente até o docente comparar o
valor atual com a sugestão apresentada na própria célula. O docente pode editar,
aceitar ou rejeitar cada alteração de forma independente. Linhas novas ou a
remover são decididas como uma unidade. **Aplicar alterações aceites** reúne as
decisões numa única nova versão; rejeitar todas conserva o rascunho sem alterações.

**Verificar esta etapa com IA**, também disponível na barra, guarda um parecer
facultativo que nunca impede avançar. O parecer fica identificado pela versão dos
artefactos que analisou; depois de qualquer alteração é apresentado como
desatualizado até o docente pedir uma nova verificação. Alegações da IA sobre IDs,
cobertura ou somas não substituem nem contradizem os controlos determinísticos.

Os controlos determinísticos dos recursos são executados durante a produção e a
edição da etapa **Geração de recursos educativos**, mas o relatório consolidado não é
apresentado nesse artefacto. O respetivo estado surge na etapa **Validação final
da estrutura e do alinhamento**, em **Qualidade automática dos recursos**, com
cartões selecionáveis que abrem a etapa, recurso, slide ou linha correspondente, e
uma linha por controlo, estado `✅`/`⚠️`/`❌` e o respetivo detalhe. Esse relatório
é recalculado antes da validação final e da exportação, sem confiar numa cópia
anterior guardada na sessão.

Numa sessão concluída, a barra de etapas fica em modo de consulta. A reabertura
exige o botão próprio, a seleção da etapa, um motivo e uma confirmação explícita.

O card **Versões e rastreabilidade** permanece recolhido por defeito para reduzir
a carga visual da área de trabalho. Depois de aberto, o separador **Versões**
permite consultar e restaurar qualquer versão não ativa das seis etapas de
autoria. A ação de restauro surge à direita do seletor de
etapa e versão. O restauro exige apenas confirmação e volta a tornar
ativa a versão escolhida, sem criar uma nova versão nem apagar as restantes. Os
passos posteriores preenchidos ficam assinalados para revisão e a
verificação global é recalculada; o relatório final, por ser derivado, não é
restaurável.

Cada entrada da lista de sessões disponibiliza ainda uma **cópia de segurança**
portátil em ZIP. O ficheiro `sessao.json`, indentado e organizado por secções em
português, permite consultar e copiar manualmente os dados iniciais, fontes,
conteúdos das etapas, recursos, versões e rastreabilidade. Os ficheiros de apoio
originais preservados, as imagens documentais e as imagens da apresentação são
extraídos como ficheiros normais para `anexos/`, acompanhados por um índice com
origem, tipo, dimensão e SHA-256. O estado técnico restaurável fica separado em
`estado_tecnico.json` e o `LEIA-ME.txt` explica a estrutura do pacote.

A ação **Restaurar cópia de segurança** valida a estrutura, os anexos e a
compatibilidade do esquema antes de criar uma nova sessão na conta autenticada;
as cópias da versão anterior, com `estado_sessao.json`, continuam a ser aceites.
O restauro nunca substitui a sessão de origem nem outra sessão existente. Os
ficheiros carregados passam a ser preservados integralmente nas novas sessões.
Numa sessão antiga, criada antes desta preservação, o ZIP inclui o texto já
extraído e as imagens disponíveis, mas identifica os ficheiros originais que já
não podem ser recuperados. Como a cópia pode conter materiais fornecidos pelo
docente, deve ser guardada num local protegido. As chaves de API pertencem à
configuração do servidor e não são incluídas. Descarregar a cópia é uma operação
de leitura: não atualiza a sessão nem acrescenta um evento de auditoria. Depois
de os bytes serem entregues à interface, o ficheiro ZIP temporário é eliminado;
o mesmo controlo de ciclo de vida aplica-se ao pacote final de recursos.

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
de seleção de cada slide. O modelo recebe somente o catálogo textual das candidatas
(ID, descrição disponível, ficheiro, página ou slide, tipo e dimensões); os bytes e
as miniaturas permanecem locais e não são anexados ao pedido de IA. Com base nesse
catálogo, o modelo pode sugerir uma candidata quando a descrição for suficiente,
mas a seleção visual continua sob controlo do docente. Uma imagem documental
claramente adequada tem prioridade sobre a geração de uma nova imagem por IA. A possibilidade
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
- `prism/ai_modes.py`: vocabulário e regras de alinhamento `AI-off`/`AI-on`/`on-AI`;
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
