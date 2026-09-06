# A5 — Registo de testes manuais ponta a ponta

## Campanha de validação da versão candidata final

**Estado da campanha:** CONCLUÍDA — E2E-01 APROVADO; E2E-02, E2E-03 E
E2E-04 APROVADOS COM OBSERVAÇÕES; E2E-05, E2E-06 E E2E-07 APROVADOS APÓS
CORREÇÕES; E2E-08 APROVADO  
**Versão de referência corrigida:** `v0.3.94`  
**Commit de referência:** `1608ec68843f1e99053338817ab34a62cb24f389`  
**Ambiente de referência:** `https://coeria.ivovargas.pt/`  
**Regra de validade:** toda a evidência manual obtida antes de `v0.3.83`
permanece apenas histórica. Os oito cenários devem ser executados novamente,
desde o início, em sessões novas criadas na versão congelada. Não são aceites
sessões nem cópias de segurança de esquemas anteriores.

Os resultados registados anteriormente para as versões v0.2.11–v0.2.15 são
preservados no fim deste documento como histórico de desenvolvimento. Deixaram
de ser evidência válida para a versão atual devido às alterações estruturais do
fluxo, da autoria manual, da assistência por IA, das versões, dos recursos, das
imagens, da validação final e da exportação.

### Pré-condição automatizada

**Estado:** APROVADO PARA `v0.3.94`

- Data inicial: 02-09-2026; repetição mais recente após correções: 06-09-2026.
- Ambiente local: Windows; Python 3.13.11.
- Dependências principais: NiceGUI 3.16.0; LangGraph 1.2.11; OpenAI 2.54.0;
  python-docx 1.2.0; python-pptx 1.0.2; pytest 9.1.1.
- Comando local: `python -m pytest -q --basetemp=.pytest-final`.
- Resultado local em `v0.3.94`: **333 testes e 7 subtestes aprovados em 28,17 s**,
  incluindo compilação real LaTeX/PDF e sem consumo de APIs.
- Resultado na VPS durante o deploy de `v0.3.94`: **333 testes e 7 subtestes
  aprovados em 57,75 s**, usando uma base de dados temporária e sem alterar a
  base de produção.
- A cobertura automatizada inclui a rejeição de bases, estados e backups de
  versões anteriores e a aceitação exclusiva do esquema de sessão 33 e do
  formato de backup 3.

### Pré-condição da VPS

**Estado:** APROVADO EM 06-09-2026

- commit instalado: `1608ec68843f1e99053338817ab34a62cb24f389`;
- tag apresentada pelo Git: `v0.3.94`;
- configuração: `COERIA_APP_VERSION=0.3.94`;
- Python da VPS: 3.14.4;
- base de produção no início da campanha: **0 sessões**;
- serviços `coeria`, `nginx` e `coeria-backup.timer`: `active`;
- `http://127.0.0.1:7860/login`: HTTP 200;
- `https://coeria.ivovargas.pt/login`: HTTP 200.

### Regras de execução manual

- Executar os casos numa instalação da VPS correspondente ao commit indicado.
- Registar data, versão apresentada na interface, identificador da sessão e
  fornecedor usado.
- Criar uma sessão nova para cada cenário; não reutilizar sessões nem backups
  de qualquer campanha anterior.
- Guardar apenas evidência sem chaves, credenciais, dados pessoais ou conteúdo
  confidencial das fontes.
- Uma correção durante a campanha exige novo commit/tag/deploy e repetição dos
  casos afetados; os restantes só permanecem válidos quando a análise de impacto
  o justificar.
- Distinguir sempre controlos determinísticos, apreciação humana e parecer
  facultativo de um LLM.

## E2E-01 — Autoria integralmente manual com SOLO

**Estado da execução, após reteste em `v0.3.86`:** APROVADO

### Execução atual — v0.3.83

- Início: 02-09-2026.
- Fim: 02-09-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA v0.3.83.
- Utilizador de teste: D12.
- Sessão: «Introdução à Literacia Digital — E2E-01 v0.3.83»;
  identificador `60a6fbbc-41d9-4e4d-afa6-2b08caf46a0d`.
- Estado inicial confirmado: utilizador autenticado e base sem sessões guardadas.
- Modo previsto: autoria manual, Taxonomia SOLO e nenhuma chamada de IA.

**Objetivo:** demonstrar que o CoerIA é utilizável sem executar qualquer LLM e
que a verificação global, e não a navegação, constitui a barreira obrigatória.

### Critérios

- abrir a página inicial e iniciar uma nova sessão;
- confirmar semestre obrigatório e `1.º semestre` selecionado por defeito;
- selecionar SOLO e criar a sessão sem pedir uma proposta à IA;
- abrir livremente as oito etapas, avançar e recuar sem gerar conteúdo;
- guardar e retomar pelo menos um rascunho incompleto;
- preencher e editar manualmente tabelas, incluindo adicionar e remover linhas;
- confirmar IDs automáticos `RA<n>`, `AE<n>` e `TA<n>` e seletores de relações;
- verificar que uma estrutura incompleta falha apenas na validação global e que
  os controlos indicam concretamente o que falta;
- completar a estrutura, concluir a sessão e confirmar persistência após refresh;
- exportar um pacote Word e abrir os ficheiros produzidos.

### Resultado atual — v0.3.83

- Página inicial, início de sessão nova, semestre obrigatório com `1.º semestre`
  por defeito e Taxonomia SOLO: **OK**.
- Navegação pelas oito etapas ainda vazias, sem executar IA: **OK**.
- Validação global da estrutura vazia: **OK** — apresentou faltas concretas e
  impediu a conclusão, sem impedir a navegação entre etapas.
- Persistência e retoma do rascunho incompleto após atualização e nova
  autenticação: **OK**.
- Edição manual: **OK** — foi adicionada e removida uma quinta linha de RA e
  ficaram quatro RA, quatro temas, quatro AE, quatro TA e quatro aulas.
- IDs automáticos e seletores de relações: **OK** — `RA1`–`RA4`, `C1`–`C4`,
  `AE1`–`AE4` e `TA1`–`TA4`; relações C→RA, AE→RA, TA→AE e TA→RA guardadas.
- Modos de utilização de IA: **OK** — `AI-off` por defeito e coerente nos
  artefactos relacionados.
- Planeamento das aulas: **OK** — quatro aulas de 60 minutos, total de 240
  minutos, correspondente às quatro horas de contacto.
- Recursos: **OK** até à exportação — apenas «Apresentação geral da UC» foi
  selecionada e foram introduzidos manualmente seis slides, incluindo o slide de
  avaliação.
- Validação global final: **OK** — 20 controlos aprovados, zero avisos e zero
  erros; a sessão foi concluída e retomada após atualização como `completed`.
- Auditoria: **OK** — não foi registada qualquer execução real de IA; constam
  apenas autoria manual, validação determinística e tentativa de exportação.
- Exportação pelo botão da interface: **FALHOU** — o navegador não recebeu o
  download e não foi criado um ZIP na pasta de transferências.

### Reteste da exportação e da apresentação — v0.3.86

- Data: 03-09-2026.
- Versão instalada na VPS: `v0.3.86`; commit
  `80696ff1f2d9ac1ff5d9ae184b22097c0cd9e111`.
- Regressão local: **319 testes aprovados, 1 ignorado por condição do ambiente e
  7 subtestes aprovados**.
- Regressão no deploy da VPS: **320 testes e 7 subtestes aprovados**; serviços
  `coeria`, `nginx` e `coeria-backup.timer` ativos; HTTP e HTTPS com resposta 200.
- Persistência da conclusão: **OK** — a mesma sessão foi retomada na v0.3.86
  como concluída, com os 20 controlos determinísticos aprovados.
- Exportação pelo botão da interface: **OK** — o pedido autenticado ao endereço
  descartável de utilização única recebeu HTTP 200 e entregou 87 977 bytes. O
  endereço não é reutilizável, não fica em cache e expira automaticamente.
- Nota sobre a instrumentação: o navegador integrado efetuou o pedido e recebeu
  a resposta, confirmado pelo registo de acesso do Nginx, embora a camada de
  automação não tenha exposto o evento de download nem o caminho local do
  ficheiro. Para inspecionar o conteúdo, o mesmo exportador foi executado em
  modo de leitura sobre a sessão persistida e produziu um pacote com os mesmos
  87 977 bytes; esta execução não alterou a sessão.
- Pacote verificado: SHA-256
  `4F9268F4F1052BEADD6EC272647859A30BB19350D68F196320910FF58E6ABAA7`;
  contém estado JSON, manifesto JSON, rastreabilidade CSV, síntese de alinhamento
  CSV, programa da UC em DOCX e apresentação em PPTX.
- Manifesto: **OK** — formato `word`, apenas «Apresentação PowerPoint»
  selecionada, qualidade com 20 controlos aprovados, zero avisos e zero erros.
- DOCX: **OK** — abriu no Microsoft Word sem reparação, tem sete tabelas e foi
  renderizado em quatro páginas A4; as secções 1–10 estão presentes, incluindo
  atividades de ensino-aprendizagem, tarefas de avaliação, planeamento das aulas
  e síntese do alinhamento. Não há linhas de dados partidas entre páginas. Foi
  registada a observação visual menor `DOC-03` relativa à largura de algumas
  colunas; não afeta a abertura nem a integridade do conteúdo.
- PPTX: **OK** — abriu estruturalmente, contém seis slides em formato 16:9 e
  passou o teste automático sem *overflow*. Os seis slides foram renderizados e
  inspecionados; os quatro diagramas usam a grelha 2×2, preservam a ordem 1–4 e
  já não partem palavras em locais impróprios.
- Registos após o reteste: **OK** — sem nova exceção da aplicação e sem erros ou
  avisos na consola do navegador.

### Defeitos encontrados

- **EXP-01 — RESOLVIDO E RETESTADO EM `v0.3.86`:** depois de preparar o ZIP, `handle_export`
  chama `_render_workspace(...)`, que elimina o *slot* da interface, e só depois
  executa `ui.notify(...)`. A VPS registou `RuntimeError: The parent element this
  slot belongs to has been deleted` em `app.py:5336`. A exceção interrompe o
  fluxo de download na interface. Em `v0.3.84` a notificação passou a anteceder
  qualquer reconstrução; em `v0.3.85` deixou de existir reconstrução após a
  entrega; em `v0.3.86` os bytes passaram a ser servidos por um URL autenticado,
  aleatório, de utilização única e com expiração de cinco minutos, sem acumular
  ZIP temporário. O reteste confirmou HTTP 200 e 87 977 bytes entregues.
- **VIS-04 — RESOLVIDO E RETESTADO EM `v0.3.86`:** o PPTX exportado não tem *overflow*, mas as caixas estreitas
  dos diagramas partem palavras em locais impróprios, por exemplo
  «Atualida/de», «Evidênci/a», «Linguage/m» e «Comunic/ar». O problema é visual e
  não invalida a estrutura do ficheiro. O exportador passou a dispor quatro
  elementos numa grelha 2×2; a inspeção dos seis slides confirmou a correção.
- **DOC-03 — menor/não bloqueante:** nas tabelas mais largas do programa Word,
  algumas colunas estreitas quebram termos e identificadores por várias linhas,
  por exemplo «Taxonomia», «identificar», `AE1` e `TA1`. O documento abre sem
  reparação, todo o texto permanece legível e nenhuma linha é partida entre
  páginas; a observação não invalida o critério do E2E-01, mas deve ser tratada
  numa melhoria posterior da paginação do programa.

### Diagnóstico isolado do exportador

Para separar o defeito da interface da geração documental, foi executado na VPS
um diagnóstico que invocou diretamente o exportador sobre o estado persistido,
sem modificar a sessão. Foi criado o ZIP `coeria-e2e01-v0383.zip` (87 859 bytes;
SHA-256 `A66117864C8A6930FB04F38E06095993017C4BE1D0201520FF53B5593A49DF41`).

- Conteúdo: estado JSON legível, manifesto JSON, rastreabilidade CSV, síntese de
  alinhamento CSV, programa da UC em DOCX e apresentação em PPTX: **OK**.
- Manifesto: formato `word`, apenas apresentação selecionada, sessão `completed`
  e qualidade com 20 controlos aprovados, zero avisos e zero erros: **OK**.
- DOCX: pacote Open XML válido, 224 parágrafos, sete tabelas e 24 linhas com
  `w:cantSplit`; contém RA, temas, atividades, tarefas e planeamento das aulas:
  **OK estruturalmente**. A renderização visual não foi concluída neste posto de
  teste por ausência de LibreOffice; isto não substitui o download pela UI.
- PPTX: pacote Open XML válido, seis slides e seis títulos esperados; renderização
  visual concluída e teste automático sem *overflow*: **OK COM OBSERVAÇÃO
  `VIS-04`**.

### Conclusão atual

O percurso manual, a validação global, a conclusão persistente e a exportação
estão funcionais. `EXP-01` e `VIS-04` foram corrigidos, publicados e retestados
na VPS. O E2E-01 fica **APROVADO em `v0.3.86`**.

### Execução histórica — v0.3.36

- Data: 26-08-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA v0.3.36.
- Utilizador de teste: D12.
- Sessão: «Introdução à Literacia Digital».
- Fornecedor configurado: OpenAI, sem executar qualquer chamada de IA.
- Taxonomia: SOLO.
- Recurso selecionado: apenas Apresentação PowerPoint.

### Resultado histórico — v0.3.36/v0.3.37

- Página inicial e início de nova sessão: **OK**.
- Semestre obrigatório e `1.º semestre` por defeito: **OK**.
- Criação e preenchimento integral sem LLM: **OK**.
- Navegação livre, incluindo acesso às etapas 7 e 8 com a estrutura incompleta:
  **OK**.
- Validação global da estrutura incompleta: **OK**, bloqueou a conclusão e indicou
  resultados em falta nas atividades de avaliação, atividades de
  ensino-aprendizagem e matriz.
- Notificação bloqueante fechável: **OK**.
- Adição e remoção manual de linhas: **OK**.
- IDs automáticos e não editáveis `RA1`–`RA4`, `AE1`–`AE4` e `TA1`–`TA4`:
  **OK**.
- Seletores de relações C→RA, AE→RA, TA→RA e matriz: **OK**.
- Guardar, atualizar a página e retomar rascunho incompleto: **OK**.
- Estrutura final: quatro RA, quatro conteúdos, quatro atividades de ensino,
  quatro tarefas de avaliação, sequência pedagógica, quatro linhas de matriz e
  quatro slides editados manualmente: **OK**.
- Validação final determinística: **OK**, todos os controlos aprovados após a
  correção dos diagramas dos slides 1 e 4.
- Conclusão e persistência após refresh: **OK**; a sessão foi retomada como
  concluída e com exportação disponível.
- Exportação Word: **OK**; foi descarregado o ZIP
  `coeria_Introdução_à_Literacia_Digital_z70pw428.zip` (84 365 bytes).
- Conteúdo do ZIP: **OK** — programa da UC em DOCX, apresentação em PPTX, matriz,
  rastreabilidade, manifesto e estado JSON; não incluiu ficha, teste ou atividade
  prática, que não tinham sido selecionados.
- Coerência do manifesto e do estado: **OK** — `quality.passed = true`, 16
  controlos aprovados, apenas «Apresentação PowerPoint» selecionada, formato
  `word`, sessão `completed`, etapa final ativa, quatro slides e os três recursos
  não selecionados vazios.
- Abertura estrutural do DOCX: **OK**; `word/document.xml` foi lido sem erro e
  contém identificação, carga de trabalho, objetivos, conteúdos, RA1–RA4 e as
  restantes secções do programa.
- Renderização visual do DOCX: **OK COM OBSERVAÇÕES**; o LibreOffice produziu
  três páginas sem pedir reparação e sem texto sobreposto ou cortado. A inspeção
  integral revelou, contudo, a coluna «Método» vazia e uma quebra pouco legível
  da última linha da tabela de avaliação entre as páginas 2 e 3.

### Defeitos/observações

- **VAL-01 — importante/não bloqueante:** numa validação de sessão vazia, a
  «Organização da sequência pedagógica» surgiu a verde como estrutura completa e
  alguns controlos de cobertura apresentaram `0 resultados` como sucesso. A
  conclusão continuou corretamente bloqueada por outros controlos e foram
  indicados os RA em falta, mas o detalhe contém sucessos enganadores.
  **Correção local concluída em 26-08-2026:** artefactos vazios deixaram de
  produzir controlos verdes; faltas bloqueantes são erros e verificações que não
  podem ser calculadas surgem como avisos. A sequência exige estratégia, RA e
  pelo menos uma linha. A correção foi publicada na VPS em `v0.3.37`, com a
  regressão automatizada aprovada. O reteste manual em produção foi aprovado em
  27-08-2026: nenhum controlo vazio surgiu como sucesso; os controlos
  indisponíveis foram apresentados como aviso e as estruturas obrigatórias
  vazias como erro.
- **VIS-03 — importante/recuperável:** o editor manual permite mais de quatro
  elementos num diagrama e não informa o limite de 2–4 aplicado pelo validador.
  Com cinco elementos nos slides 1 e 4, a validação mostrou apenas
  «Especificação visual incompleta», sem explicar a causa. Reduzir cada diagrama
  para quatro elementos permitiu concluir.
  **Correção local concluída em 26-08-2026:** o editor explicita o limite 2–4, o
  esquema estruturado impõe `minItems`/`maxItems` e a validação identifica, por
  slide, cada causa concreta. A correção foi publicada na VPS em `v0.3.37`, com
  a regressão automatizada aprovada. O reteste manual em produção foi aprovado
  em 27-08-2026: o editor indicou explicitamente 2–4 elementos e a validação de
  um diagrama com cinco elementos apresentou «slide 1: 5 elementos; o diagrama
  admite 2 a 4». Depois da reposição de quatro elementos, o controlo voltou a
  passar.
- **DOC-01 — importante:** o Word exportado apresenta a coluna «Método» vazia em
  todas as atividades de ensino-aprendizagem, embora «Prática» e
  «Acompanhamento» estejam preenchidos na aplicação. O diagnóstico confirmou a
  incompatibilidade: o editor manual grava `practice` e `support`, mas o
  exportador continua a ler apenas o campo legado `method`.
  **Correção local concluída em 26-08-2026:** Word e LaTeX exportam contexto,
  atividade, prática, acompanhamento, feedback e resultados; `method` é apenas
  fallback para sessões antigas. A sequência pedagógica passou também a integrar
  os dois programas. Regressão automatizada e renderização local aprovadas; a
  correção foi publicada na VPS em `v0.3.37`. O reteste manual da exportação em
  produção foi aprovado em 27-08-2026: a tabela de ensino-aprendizagem incluiu
  contexto, atividade, prática, acompanhamento e feedback, e o programa passou
  a incluir a organização da sequência pedagógica.
- **DOC-02 — menor/não bloqueante:** a linha TA4 é dividida entre as páginas 2 e
  3; a página 3 começa com uma linha quase vazia que contém apenas a última
  palavra do critério. Não existe corte de texto, mas a leitura e a apresentação
  formal do programa ficam prejudicadas.
  **Correção local concluída em 26-08-2026:** as linhas de dados recebem
  `w:cantSplit`. Um programa de stress com critério longo foi renderizado em
  quatro páginas sem dividir a linha TA4. A correção foi publicada na VPS em
  `v0.3.37`. O novo programa exportado em produção foi também renderizado em
  quatro páginas; a linha TA4 permaneceu inteira e não foram encontrados cortes,
  sobreposições ou tabelas quebradas.

### Reteste de encerramento — v0.3.37

- Data: 27-08-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA v0.3.37.
- Utilizador de teste: D12.
- Sessão principal: «Introdução à Literacia Digital»; sessão técnica adicional:
  «E2E-01R v0.3.37».
- Chamadas de IA efetuadas: nenhuma.
- `VAL-01`: **OK** — sessão vazia com erros/avisos coerentes, sem sucessos
  enganadores por igualdade de conjuntos vazios.
- `VIS-03`: **OK** — limite 2–4 visível no editor, causa detalhada com cinco
  elementos e recuperação confirmada depois de repor quatro.
- Validação global após a reposição: **OK** — todos os controlos aprovados e
  sessão concluída novamente.
- Persistência após atualização e retoma: **OK** — estado concluído, versão ativa
  aprovada e exportação disponível.
- Exportação Word: **OK** — ZIP
  `coeria_Introdução_à_Literacia_Digital_0rphnciz.zip`, com programa DOCX,
  apresentação PPTX, matriz, rastreabilidade, manifesto e estado JSON; os três
  recursos não selecionados permaneceram ausentes.
- Manifesto: **OK** — `quality.passed = true` e apenas «Apresentação PowerPoint»
  selecionada.
- `DOC-01`: **OK** — a tabela exporta contexto, atividade, prática,
  acompanhamento, feedback e resultados; a secção «Organização da sequência
  pedagógica» inclui estratégia e quatro linhas RA–AE–TA.
- `DOC-02`: **OK** — DOCX aberto pelo LibreOffice e renderizado integralmente em
  quatro páginas; TA4 não se dividiu, os cabeçalhos da matriz repetiram-se e não
  foram observados texto cortado, sobreposição, glifos em falta ou tabelas
  quebradas.

### Conclusão

O percurso integralmente manual foi concluído na VPS sem chamadas de IA. A
barreira obrigatória está na validação global, a persistência funciona antes e
depois da conclusão e o pacote Word foi produzido, aberto estruturalmente e
renderizado na íntegra. As correções de `VAL-01`, `VIS-03`, `DOC-01` e `DOC-02`
passaram a regressão automatizada local e na VPS e o reteste manual em produção.
O E2E-01 fica encerrado como **APROVADO** na versão `v0.3.37`. Este resultado é
histórico e não constitui aceitação da versão posterior ao descongelamento.

## E2E-02 — Fluxo Bloom com assistência e proposta completa da OpenAI

**Estado:** APROVADO COM OBSERVAÇÕES EM `v0.3.86`

**Objetivo:** validar a taxonomia alternativa e o controlo humano sobre propostas
produzidas por IA.

### Critérios

- criar uma sessão exclusivamente com Bloom;
- pedir uma proposta completa numa etapa vazia e confirmar que o artefacto ativo
  não muda antes da aplicação explícita;
- editar a proposta, aceitar apenas parte das alterações e rejeitar as restantes;
- confirmar IDs `RA1`, `RA2`, … e coerência entre nível Bloom e verbo;
- confirmar que SOLO não surge nos artefactos Bloom nem na síntese automática
  do alinhamento;
- pedir um parecer de IA com uma etapa incompleta e avançar apesar do parecer;
- gerar apenas os tipos de recurso selecionados e concluir após validação global.

### Execução

- Data: 03-09-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA v0.3.86;
  commit `80696ff1f2d9ac1ff5d9ae184b22097c0cd9e111`.
- Utilizador de teste: D12.
- Sessão: «Fundamentos de Ética da Inteligência Artificial — E2E-02 v0.3.86»;
  identificador `8bc7e0cd-8caa-41fb-a203-8fea5d84db56`.
- Fornecedor: OpenAI; taxonomia selecionada: Bloom.

### Resultado

- Criação de uma sessão exclusivamente com Bloom: **OK**.
- Primeira proposta completa numa etapa vazia: **OK** — a IA apresentou seis
  linhas pendentes e o artefacto ativo permaneceu vazio até à decisão explícita.
- Controlo humano da proposta: **OK** — o texto da primeira linha foi editado,
  cinco linhas foram aceites e a sexta foi rejeitada. O estado persistido da
  proposta P1 ficou `partially_accepted`, com 5 decisões de aceitação e 1 de
  rejeição.
- IDs e coerência taxonómica: **OK** — ficaram `RA1`–`RA5`; os pares observados
  foram Recordar/identificar, Compreender/descrever, Compreender/explicar,
  Analisar/analisar e Avaliar/avaliar.
- Exclusividade da taxonomia: **OK** — o estado persistido indica Bloom e contém
  zero ocorrências de `SOLO`; a validação e a síntese automática referem
  exclusivamente a Taxonomia Bloom.
- Parecer facultativo numa etapa incompleta: **OK** — em Conteúdos curriculares
  vazios, a IA apresentou um bloqueante relativo à ausência de associações a
  resultados; a interface manteve «Etapa seguinte» disponível e permitiu abrir
  as Atividades de ensino-aprendizagem.
- Propostas completas seguintes: **OK** — foram explicitamente aprovados cinco
  conteúdos, cinco AE, cinco TA e três aulas de 60 minutos, totalizando
  exatamente as 3 horas de contacto.
- Seleção de recursos: **OK** — foram selecionadas apenas «Ficha de aula» e
  «Grelha de avaliação». A interface anunciou uma geração textual por IA e um
  recurso preparado diretamente; foram produzidas cinco secções da ficha e uma
  grelha com cinco tarefas.
- Recursos não selecionados: **OK** — apresentação geral, apresentações das
  aulas, testes, atividade prática e plano de aulas permaneceram vazios, como
  confirmado pelos controlos determinísticos.
- Validação global: **OK** — 9 controlos estruturais e 19 controlos de qualidade
  aprovados, zero avisos e zero erros; a sessão ficou persistida como
  `completed` na etapa final.

### Observações encontradas

- **E2E02-OBS-01 — alinhamento demasiado abrangente:** a proposta de conteúdos
  associou cada um dos cinco temas a todos os cinco resultados de aprendizagem.
  A cobertura é formalmente completa, mas as ligações são pouco discriminativas
  para uma UC em que cada tema corresponde principalmente a um RA. Os controlos
  determinísticos verificam existência e validade das ligações, não a sua
  pertinência semântica; esta continua a exigir revisão humana.
- **E2E02-OBS-02 — cobertura do planeamento não controlada:** as três aulas
  geradas totalizam corretamente 180 minutos, mas referem apenas AE1/TA1,
  AE2/TA2 e AE3/TA3. AE4/TA4 e AE5/TA5 não surgem no plano, embora os controlos
  «Planeamento das aulas» e «Estrutura e alinhamento pedagógico» tenham ficado
  verdes. Não viola um critério específico deste E2E, mas deve ser decidido se a
  validação global deve exigir cobertura integral no planeamento das aulas.

### Conclusão

O E2E-02 fica **APROVADO COM OBSERVAÇÕES em `v0.3.86`**. A taxonomia Bloom, a
aprovação humana parcial, a navegação não bloqueada pelo parecer facultativo e a
seleção estrita de recursos foram confirmadas. As duas observações devem ser
avaliadas antes de declarar encerrada a campanha, por incidirem na qualidade do
alinhamento e não no controlo técnico da proposta.

## E2E-03 — Assistência localizada, versões e alterações a montante

**Estado:** APROVADO COM OBSERVAÇÕES EM `v0.3.86`

**Objetivo:** validar o fluxo manual-first e a rastreabilidade introduzidos após
a campanha anterior.

### Critérios

- pedir assistência sucessivamente para uma célula, uma linha e uma tabela;
- confirmar que os IDs técnicos não podem ser escolhidos como campos assistidos;
- apresentar cada sugestão por baixo do valor atual, sem expor JSON como interface;
- editar, aceitar e rejeitar células independentes e criar uma única versão com
  as alterações aceites;
- provocar uma proposta desatualizada e confirmar que já não pode ser aplicada;
- restaurar uma versão anterior sem motivo e sem criar uma versão adicional;
- regressar aos dados iniciais, alterar a caracterização e as fontes e confirmar
  que o trabalho posterior é preservado mas assinalado para revisão;
- numa sessão concluída, confirmar que a barra é apenas de leitura e que reabrir
  para edição exige ação e confirmação explícitas.

### Execução

- Data: 04-09-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA v0.3.86;
  commit `80696ff1f2d9ac1ff5d9ae184b22097c0cd9e111`.
- Utilizador de teste: D12.
- Sessão: «Introdução à Gestão de Projetos — E2E-03 v0.3.86»;
  identificador `efbeb86d-5706-4558-abd5-9aeeec05dea1`.
- Fornecedor: OpenAI; taxonomia selecionada: SOLO.

### Resultado

- Assistência para uma célula: **OK** — foi pedida uma reformulação apenas para
  o enunciado de RA1. A sugestão surgiu sob o texto atual, foi editada pelo
  docente e só depois aplicada, criando a versão 2.
- Assistência para uma linha: **OK** — na linha RA2, a proposta alterava o verbo
  e o enunciado. A alteração do verbo foi rejeitada e o enunciado foi editado e
  aceite. A proposta P3 ficou `partially_accepted`, com uma célula aceite e uma
  rejeitada, e criou apenas a versão 3.
- Assistência para uma tabela: **OK** — o âmbito explícito «Tabela completa:
  Aulas planeadas» apresentou as sugestões dentro da tabela, por baixo dos
  valores atuais, e não expôs JSON. A proposta foi integralmente rejeitada e
  não criou uma nova versão.
- Proteção dos identificadores: **OK** — os âmbitos de célula apresentaram os
  campos pedagógicos editáveis, mas nunca disponibilizaram o campo técnico ID.
- Proposta desatualizada: **OK** — a proposta P4 para RA3 ficou pendente; uma
  alteração posterior aos dados iniciais preservou os resultados e marcou-os
  para revisão. A proposta desapareceu da interface e ficou persistida como
  `superseded`, não podendo ser aplicada.
- Alteração a montante: **OK** — foram alterados o curso, o texto de referência
  e a bibliografia. Os sete resultados já produzidos foram preservados e a
  etapa ficou assinalada como «Rever após alterações anteriores».
- Restauro: **OK** — a versão 2 dos resultados foi restaurada sem pedir motivo.
  O histórico continuou com três versões e `active_versions.learning_outcomes`
  passou a 2; não foi criada uma quarta versão.
- Preparação da sessão: **OK** — ficaram persistidos 7 resultados, 7 conteúdos,
  7 atividades de ensino-aprendizagem e 7 tarefas de avaliação; o planeamento
  totalizou exatamente as 4 horas de contacto.
- Validação e conclusão: **OK** — a validação final apresentou 27 controlos
  verdes, zero avisos e zero erros, e a sessão ficou `completed`.
- Proteção da sessão concluída: **OK** — a barra deixou de expor botões para as
  etapas. A única ação de edição foi «Reabrir explicitamente para edição», que
  abriu um diálogo de confirmação e avisou que a exportação ficaria
  temporariamente indisponível.

### Observação encontrada

- **E2E03-OBS-01 — estado residual em Recursos:** depois de o planeamento ser
  atualizado, a etapa de recursos ficou corretamente marcada para revisão.
  Contudo, voltar à etapa e guardar novamente a seleção inalterada de «Grelha
  de avaliação» não limpou o estado. A validação determinística considerou o
  recurso atual, apresentou todos os controlos a verde e permitiu concluir, mas
  a barra da sessão concluída continua a mostrar «Sessão concluída · Rever após
  alterações anteriores» em Recursos. O estado persistido confirma
  `stage_statuses.resources = needs_review` e não contém uma versão de Recursos.

### Conclusão

O E2E-03 fica **APROVADO COM OBSERVAÇÕES em `v0.3.86`**. O controlo localizado
por célula, linha e tabela, as decisões independentes, a proteção contra
propostas desatualizadas, o restauro sem nova versão e a reabertura explícita
foram confirmados. A observação E2E03-OBS-01 não comprometeu a integridade dos
dados nem a validação, mas produz uma indicação visual contraditória numa
sessão concluída.

## E2E-04 — Fontes extensas, imagens documentais e privacidade

**Estado:** APROVADO COM OBSERVAÇÃO DE CUSTO; CORREÇÕES VISUAIS E DE
RASTREABILIDADE PUBLICADAS EM `v0.3.88`

**Objetivo:** repetir e ampliar os antigos E2E-02/E2E-03 para o comportamento
atual de ingestão e seleção visual.

### Critérios

- carregar fontes de áreas e dimensões diferentes, incluindo um ficheiro entre
  33 MB e 50 MB, sem ultrapassar 100 MB no total;
- confirmar que a redução extensa só ocorre quando uma operação de IA a exige;
- demonstrar cobertura específica das diferentes fontes no artefacto curricular;
- confirmar que as imagens candidatas aparecem apenas no seletor de imagem do
  slide e incluem miniatura, documento e página/slide quando disponível;
- confirmar que a criação dos slides só pode escolher automaticamente uma
  candidata com descrição semântica explícita e que, na ausência dessa
  descrição, preserva um diagrama ou uma imagem gerada por IA para posterior
  decisão humana;
- verificar por evidência técnica que o pedido textual contém apenas identificador,
  descrição, proveniência e dimensões, sem bytes, base64, miniaturas ou `input_image`;
- exportar uma apresentação com pelo menos uma imagem documental e confirmar
  proveniência e texto alternativo no PowerPoint.

### Repetição em produção

- Data: 05-09-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA v0.3.87;
  commit `b9543547a0bd5e97769ed54bd7942e7289ecef4b`.
- Utilizador de teste: D12.
- Sessão: «TinyML e Alinhamento Construtivo — E2E-04 v0.3.87»;
  identificador `6be916d4-bcb4-4ca7-96d2-3dfa78ea53a4`.
- Fontes: `Constructive-Alignment-in-the-Age-of-AI.pdf` (603 069 bytes) e
  uma cópia válida de 665 páginas do manual TinyML ampliada apenas com
  preenchimento no fim do PDF para 35 651 584 bytes. Total apresentado pela
  interface: 34,6 MB, abaixo do limite conjunto de 100 MB.
- Fornecedor: OpenAI; taxonomia: SOLO; recurso selecionado: apenas
  «Apresentação PowerPoint».

### Resultado da repetição

- Ingestão das duas fontes: **OK** — ambas chegaram a 100% e ficaram guardadas
  como anexos separados.
- Redução diferida: **OK** — antes do primeiro pedido à IA, o estado indicava
  `applied=false`, `deferred=true`, 1 027 078 caracteres efetivos e zero tokens.
  Só o primeiro pedido executou a redução para 29 853 caracteres em 15 blocos,
  preservando as fontes na proveniência.
- Cobertura específica: **OK** — os resultados e os conteúdos distinguiram
  TinyML, microcontroladores e implantação de alinhamento construtivo e dos
  modos AI-off, AI-on e on-AI.
- Catálogo visual: **OK** — as 30 candidatas ficaram confinadas ao popup
  «Imagem associada ao slide», com miniatura, documento e página. Não apareceu
  uma listagem redundante na etapa.
- Seleção automática segura: **OK** — como as 30 candidatas não tinham descrição
  semântica fiável, a proposta automática não escolheu qualquer imagem
  documental. Produziu seis diagramas editáveis e duas imagens geradas por IA;
  deixou assim a decisão documental ao docente.
- Seleção humana: **OK** — no popup do slide «Princípios de TinyML» foi escolhida
  a capa do manual, Página 1. O slide permaneceu aberto e o texto alternativo foi
  corrigido antes da aprovação para descrever a imagem real.
- Fronteira de privacidade: **OK** — o catálogo textual do pedido ficou vazio
  nesta sessão por não existirem descrições semânticas elegíveis. Os quatro
  testes dirigidos de seleção e o teste do agente confirmaram que miniaturas,
  `data_base64`, bytes originais e `input_image` não entram no pedido textual.
- Geração e validação: **OK** — a apresentação tem oito slides, incluindo dois
  slides de avaliação. Todos os controlos determinísticos ficaram verdes e a
  sessão passou a `completed`.
- Exportação: **OK** — a exportação Word foi registada na auditoria. O ZIP contém
  o programa da UC, a apresentação, dois CSV, o manifesto e o estado da sessão.
  O PowerPoint tem oito slides e duas partes de imagem. No slide 2, a relação
  aponta para a imagem documental incorporada; a fonte visível identifica o
  ficheiro e a Página 1 e o atributo `descr` contém o texto alternativo aprovado.
- Integridade do PowerPoint: **OK estrutural** — a inspeção do pacote encontrou
  oito slides, 22 partes de relações e zero inconformidades estruturais.
- `E2E04-F01`: **RESOLVIDO** — não ocorreu qualquer seleção documental automática
  sem descrição semântica nem foi criado texto alternativo enganador para essas
  candidatas.
- `E2E04-OBS-01`: **NÃO REPRODUZIDO** — todos os pedidos, propostas, decisões e
  mudanças de etapa concluíram sem o erro de contexto da notificação.

### Observações da repetição

- **E2E04-OBS-02 — custo da redução extensa:** a redução inicial usou 15 blocos,
  257 754 tokens de entrada e 7 715 de saída, totalizando 265 469 tokens em
  `gpt-4o-mini` e 104 247 ms. O comportamento é diferido, mas o custo continua
  relevante para documentos extensos.
- **E2E04-OBS-03 — excesso de conteúdo no slide de avaliação:** a renderização
  integral e o verificador externo detetaram conteúdo fora da área no slide 6.
  O texto das tarefas invade o rodapé e é cortado no limite inferior, apesar de
  o controlo determinístico «Elementos visuais da apresentação» ficar verde.
  A observação é independente da seleção segura de imagens, mas deve ser tratada
  antes de considerar a exportação visualmente robusta.
- **E2E04-OBS-04 — indicador de disponibilidade no manifesto:** o manifesto marca
  as 30 imagens como `available_to_llm=true`, embora nenhuma tenha descrição
  semântica elegível e nenhuma tenha entrado no catálogo textual do pedido. O
  campo é calculado pela origem da imagem e deixou de refletir a nova regra de
  filtragem. Não houve envio de bytes, mas a rastreabilidade fica enganadora.

### Correções posteriores em v0.3.88

- `E2E04-OBS-03`: **RESOLVIDA** — a canonicalização passou a criar um slide
  próprio por tarefa de avaliação, preservando integralmente finalidade, tarefa,
  resultados, evidência e critério. O PowerPoint reconstruído a partir do estado
  desta sessão tem dez slides, passou o teste automático de overflow, a inspeção
  visual de todas as páginas e a verificação estrutural do pacote com zero
  inconformidades. A validação final rejeita agora secções que agrupem tarefas,
  omitam campos aprovados ou apresentem texto truncado.
- `E2E04-OBS-04`: **RESOLVIDA** — o manifesto usa a mesma regra do catálogo
  textual: `available_to_llm=true` apenas quando existe descrição semântica
  explícita e a imagem não foi carregada isoladamente pelo docente.
- Evidência técnica: commit `ed0fad4`, tag `v0.3.88`; 323 testes e 7 subtestes
  aprovados localmente e na VPS; serviços ativos e respostas HTTP 200 após o
  deploy de 05-09-2026.

### Conclusão

O E2E-04 fica **APROVADO, com observação de custo, após as correções da
`v0.3.88`**. O defeito bloqueante
da seleção documental foi corrigido e a ingestão, redução diferida, privacidade,
seleção humana, validação e exportação ficaram demonstradas em produção. As
observações `E2E04-OBS-03` e `E2E04-OBS-04` foram encerradas tecnicamente; mantém-se
`E2E04-OBS-02` como medição explícita do custo de redução de fontes extensas.

## E2E-05 — Edição da apresentação e origens das imagens

**Estado:** APROVADO APÓS CORREÇÃO

**Execução:** 05-09-2026, VPS, utilizador D12, sessão
`51257160-7e7e-4bfb-9518-95ac7dc233f5`. O percurso funcional foi executado em
`v0.3.88`; a correção residual encontrada foi publicada e validada em
`v0.3.89`, commit `7fbccd5`.

**Objetivo:** validar a interface de recursos e as três origens visuais atualmente
suportadas durante a edição.

### Critérios

- selecionar apenas a apresentação e confirmar que propostas e edição não mostram
  ficha, teste ou atividade prática;
- consultar e editar a apresentação por slide e manter o slide corrente depois de
  selecionar ou remover uma imagem;
- associar uma imagem documental através do seletor com miniaturas;
- carregar uma imagem local, confirmar processamento local e associá-la a um slide;
- pedir uma instrução sugerida para o slide, editá-la e gerar até duas imagens
  adicionais por ação explícita;
- confirmar miniaturas, proveniência e texto alternativo antes da aprovação;
- provocar uma falha controlada de geração de imagem e confirmar fallback para
  diagrama com aviso, sem ativo inválido no estado ou manifesto;
- confirmar que a vista não repõe colunas técnicas, avisos visuais redundantes ou
  uma galeria separada de imagens selecionadas;
- abrir o PPTX final no PowerPoint sem reparação e inspecionar todos os slides.

### Resultado

- Foi selecionada apenas a **Apresentação geral da UC**. A proposta completa, a
  revisão e a edição mostraram exclusivamente esse recurso; os restantes
  recursos permaneceram vazios e foram reconhecidos como não selecionados na
  validação final.
- A apresentação passou a conter 21 slides. As tarefas `TA1`–`TA10` ocuparam dez
  slides independentes, um por tarefa, com finalidade, enunciado, resultados,
  evidência e critério completos. Não foi encontrado texto truncado.
- O editor manteve o slide corrente depois de selecionar, substituir ou remover
  imagens. Foram associados no ficheiro final: uma imagem carregada localmente
  no slide 2, uma imagem gerada pela OpenAI Image API no slide 3 e uma imagem
  extraída do PDF de apoio no slide 5, todas com miniatura, proveniência e texto
  alternativo.
- A instrução do slide 3 foi sugerida pela IA, editada pelo docente e usada para
  gerar a imagem. Foi gerada uma segunda imagem para o slide 4; depois disso, a
  interface apresentou `0 de 2` gerações disponíveis e desativou as duas ações
  de geração.
- A imagem carregada pelo docente foi processada localmente e ficou marcada no
  manifesto como `origin_type=user_uploaded` e `available_to_llm=false`. As
  imagens documentais sem descrição semântica explícita também não foram
  disponibilizadas ao LLM.
- A falha controlada foi provocada apenas no modelo de imagem, usando
  temporariamente `coeria-e2e-invalid-model`. A geração textual continuou, os
  slides afetados regressaram a diagrama com aviso e nenhum ativo inválido foi
  criado. A configuração foi imediatamente reposta; a VPS voltou a responder
  HTTP 200 com `gpt-image-2` como modelo efetivo.
- O docente voltou a associar uma imagem válida ao slide 3 e manteve o slide 4
  como fallback. O estado final contém 18 diagramas, duas imagens de origem
  documental/local e uma imagem gerada por IA. A validação final aprovou todos
  os controlos.
- O ZIP final foi exportado, o PPTX abriu no PowerPoint de secretária em modo de
  leitura com 21 slides e sem pedido de reparação. A renderização integral, a
  inspeção visual, `slides_test.py` e a verificação estrutural confirmaram zero
  overflow e zero anomalias de pacote.

### Defeito encontrado e correção

- **E2E05-OBS-01 — aviso de fallback obsoleto:** ao substituir um diagrama de
  fallback por uma imagem válida, o aviso técnico anterior permanecia no estado
  do slide. A `v0.3.89` limpa `visual_warning` em qualquer escolha explícita de
  imagem ou de diagrama. O teste de regressão foi acrescentado; a suíte passou
  com 323 testes e 7 subtestes, localmente e na VPS.

### Conclusão

O E2E-05 fica **APROVADO após a correção da `v0.3.89`**. Foram demonstrados em
produção o controlo humano das três origens visuais, o limite de custo, o
fallback recuperável, a rastreabilidade, a validação determinística e a
utilização do PowerPoint final sem truncagem nem reparação.

## E2E-06 — Recursos, validação final e exportações

**Estado:** APROVADO APÓS CORREÇÕES — v0.3.93

**Objetivo:** validar o conjunto completo de recursos e os formatos acrescentados
depois da campanha v0.2.x.

### Critérios

- selecionar todos os recursos disponíveis: apresentação geral, ficha de aula,
  atividade prática, apresentações por aula, testes por tarefa de avaliação,
  plano de aulas e grelha de avaliação;
- confirmar geração independente, âmbito correto e indicação de progresso por
  recurso;
- provocar a falha de um recurso posterior e confirmar que uma nova tentativa não
  repete os recursos já válidos;
- rever apresentação, ficha, teste e atividade prática em separadores próprios;
- confirmar na validação final o detalhe de todos os controlos dos recursos;
- testar um erro bloqueante real e impedir a conclusão até à correção;
- exportar separadamente Word, LaTeX/PDF e ambos;
- abrir DOCX, TEX, PDF e PPTX e verificar conteúdo, caracteres, listas, tabelas e
  ausência de pedidos de reparação;
- confirmar que o ZIP contém apenas os recursos selecionados, programa da UC,
  síntese automática do alinhamento, auditoria, manifesto e estado JSON coerentes.

### Primeira execução — v0.3.89, 06-09-2026

- Foram selecionados e gerados os sete tipos de recurso. A aplicação apresentou
  13 gerações independentes: apresentação geral, cinco apresentações de aula,
  ficha, cinco testes e atividade prática. O plano de aulas e a grelha de
  avaliação foram ainda derivados deterministicamente.
- Um reinício do serviço durante a revisão não perdeu a proposta pendente. A
  interface retomou a decisão humana e permitiu aplicar os recursos.
- A validação final apresentou 38 controlos. Foi provocado um erro real ao
  reduzir a ponderação da atividade prática para 90%; a conclusão foi bloqueada
  até a soma voltar a 100%, após o que ficaram 38 controlos aprovados, sem avisos
  nem erros.
- As exportações Word, LaTeX/PDF e combinada foram descarregadas. Os ZIP tinham,
  respetivamente, 20, 30 e 40 entradas. O pacote combinado continha o programa,
  uma apresentação geral, cinco apresentações de aula, ficha, cinco testes,
  atividade prática, plano de aulas e grelha nos formatos aplicáveis, dois CSV,
  manifesto, auditoria e estado JSON.
- Os dez ficheiros LaTeX compilaram para PDF. Foram renderizadas e inspecionadas
  as 24 páginas PDF e as 41 lâminas PowerPoint no Microsoft PowerPoint; nenhum
  PPTX pediu reparação e não foram encontrados cortes ou *overflow*.

### Defeitos encontrados e correções publicadas

- **E2E06-F01 — teste de escolha múltipla sem opções:** o teste de TA1 continha
  perguntas com tipo `Multiple Choice` e chaves por letras, mas o esquema, o
  editor, a pré-visualização e os exportadores não possuíam opções de resposta.
  A correção exige tipos em português, 3–5 opções distintas nas questões de
  escolha múltipla, validação da chave e apresentação/edição/exportação das
  opções em Word e LaTeX.
- **E2E06-F02 — programa LaTeX pouco legível:** as tabelas de resultados,
  ensino-aprendizagem e avaliação tinham cabeçalhos justapostos e colunas
  excessivamente estreitas. A correção combina campos relacionados e coloca as
  duas tabelas mais extensas em páginas horizontais; a evidência da avaliação,
  antes omitida desta tabela LaTeX, passa também a ser exportada.
- O PDF corrigido foi compilado e renderizado localmente. Os cabeçalhos deixaram
  de se sobrepor. As correções foram publicadas na `v0.3.90`, commit `4ffc7a9`;
  a suíte completa passou com **327 testes e 7 subtestes** localmente e na VPS.

### Segunda execução — v0.3.90, 06-09-2026

- A sessão anterior foi reaberta explicitamente na etapa «Geração de recursos
  educativos», preservando os sete tipos de recurso e as cinco instâncias de teste.
- Foi pedida à OpenAI uma proposta localizada para regenerar o teste `TA1`, com
  exigência explícita de uma questão de escolha múltipla, 3–5 opções distintas e
  chave correspondente a uma das opções.
- A resposta foi recebida e persistida como proposta pendente, mas a interface
  apresentou campos da ficha de aula, declarou que não existiam alterações
  pedagógicas editáveis e não mostrou os botões de aplicar ou rejeitar.
- Os registos da VPS confirmaram a exceção em `app.py`, na revisão da proposta:
  `KeyError: 'test'`. O revisor usa o esquema geral da etapa de recursos, cujo campo
  legado `test` não existe no artefacto agregado com a coleção `tests`.
- **E2E06-F03 — proposta localizada de teste bloqueia a interface:** é necessário
  rever o fragmento `tests[n].test` com o esquema próprio do teste e garantir que
  os controlos de decisão são sempre apresentados, mesmo quando não há diferenças.
  O reteste foi interrompido neste ponto; não se repetiram ainda as exportações.

### Terceira execução — v0.3.91 e v0.3.92, 06-09-2026

- O E2E06-F03 foi corrigido na `v0.3.91`, commit `108b2d7`. A proposta localizada
  do teste `TA1` passou a usar o esquema do fragmento `tests[n].test`; a interface
  apresentou as diferenças e permitiu aplicar ou rejeitar a decisão.
- Os testes `TA1` a `TA5` foram regenerados separadamente através da OpenAI. As
  questões de escolha múltipla passaram a conter entre três e cinco opções e
  chaves válidas. Os restantes recursos já concluídos não foram gerados novamente.
- A validação final terminou com **37 controlos aprovados**, sem avisos nem erros.
  O número é inferior ao da primeira execução porque a etapa autónoma de matriz
  de alinhamento foi entretanto removida da aplicação.
- A exportação LaTeX da `v0.3.91` detetou o defeito **E2E06-F04**: texto produzido
  pela IA com acentos em forma Unicode decomposta fazia o `pdflatex` falhar. A
  `v0.3.92`, commit `41b17de`, normaliza todo o texto para NFC antes de o escapar.
- Na `v0.3.92`, os pacotes Word, LaTeX/PDF e combinado voltaram a ter 20, 30 e
  40 ficheiros. Os 10 documentos LaTeX compilaram para 27 páginas PDF; os 10
  DOCX, 10 TEX, 10 PDF e 6 PPTX foram abertos ou analisados estruturalmente sem
  pedidos de reparação. As 41 lâminas PowerPoint foram renderizadas e
  inspecionadas sem cortes, sobreposições ou repetição indevida entre aulas.

### Verificação final — v0.3.93, 06-09-2026

- A inspeção visual da `v0.3.92` revelou o defeito **E2E06-F05**: quando a IA já
  incluía `A)`, `B)` ou equivalente no texto de uma opção, a pré-visualização e os
  exportadores acrescentavam um segundo rótulo, por exemplo `A. A) Transparência`.
- A `v0.3.93`, commit `e04b6db`, remove apenas o prefixo redundante no momento da
  apresentação, preservando no estado da sessão o texto e a chave aprovados pelo
  docente. A correção abrange a interface, Word e LaTeX.
- A suíte completa passou com **332 testes e 7 subtestes**, localmente e na VPS.
  O deploy criou o backup `prism-20260906T103939Z.db.gz`; aplicação, Nginx e
  temporizador de backups ficaram ativos e os controlos HTTP local e HTTPS
  devolveram `200`.
- Foi exportado novamente, em produção, o pacote combinado da sessão
  `10d080a2-fdd8-4bdd-9552-df0d859e51d8`. O ZIP contém **40 ficheiros**: 10 DOCX,
  10 TEX, 10 PDF, 6 PPTX, 2 CSV e 2 JSON. O manifesto declara os formatos Word e
  LaTeX/PDF e qualidade aprovada.
- A pesquisa nos 10 TEX e 10 DOCX não encontrou rótulos duplicados nem caracteres
  Unicode combinantes. O PDF real de `TA1` foi renderizado e inspecionado: as
  opções aparecem uma única vez (`A. Transparência`, `B. Justiça`, etc.), com
  acentuação correta e sem truncagem.

### Conclusão

O E2E-06 fica **APROVADO APÓS AS CORREÇÕES DA v0.3.93**. Foram validados o
âmbito e a persistência da geração independente, a correção de um bloqueio real,
os controlos finais, os três modos de exportação e a integridade dos documentos
Word, LaTeX/PDF e PowerPoint produzidos em ambiente de produção.

## E2E-07 — Autenticação, isolamento, retoma e VPS

**Estado:** APROVADO APÓS CORREÇÃO NA `v0.3.94`

### Execução e reteste — v0.3.93 → v0.3.94

- Data: 06-09-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`.
- Utilizadores de teste: D12 e D11.
- Sessões temporárias: D12 `3f65fe28-014b-4050-b21c-354e02da5cca`, D11
  `6fd63941-0ff3-49e5-aa2b-a8d7f16a5dba` e restauro D12
  `3138c7f0-0b1a-4da7-85a3-5a7674632e9c`.
- As três sessões temporárias foram eliminadas no fim do ensaio; as sessões
  anteriores dos utilizadores não foram alteradas.

**Objetivo:** validar o contexto real de utilização remota pelos docentes.

### Critérios

- confirmar que a VPS executa o commit/tag de referência e apresenta a versão correta;
- autenticar com dois utilizadores de teste e confirmar isolamento das sessões;
- retomar e eliminar apenas uma sessão pertencente ao utilizador autenticado;
- confirmar que notificações de erro podem ser fechadas e não se acumulam
  indefinidamente;
- confirmar persistência após refresh, nova autenticação e reinício controlado do serviço;
- descarregar uma cópia de segurança, confirmar o JSON legível e os anexos e
  restaurá-la como uma sessão nova do mesmo utilizador;
- confirmar que a descarga não altera a sessão de origem e que um backup de
  formato ou esquema anterior é rejeitado;
- verificar a página inicial, navegação responsiva e encerramento apenas da sessão autenticada.

### Resultado

- A interface e o checkout da VPS apresentaram `v0.3.94`; `coeria`, `nginx` e
  `coeria-backup.timer` ficaram `active`, e os endpoints local e HTTPS
  responderam HTTP 200.
- D12 e D11 autenticaram com as respetivas credenciais. Cada utilizador viu,
  retomou e eliminou apenas sessões próprias; os títulos criados pelo outro
  utilizador nunca surgiram na respetiva lista.
- A sessão D12 reapareceu depois de atualizar a página e depois de nova
  autenticação. O deploy/reinício controlado para `v0.3.94` preservou a sessão,
  o anexo e a autenticação corrente.
- A cópia D12 incluiu `sessao.json` legível, `estado_tecnico.json`, manifesto,
  instruções e o PDF de apoio real em `anexos/fontes`. O restauro criou outro
  identificador, manteve o proprietário D12 e preservou o anexo.
- Antes e depois do download, a sessão de origem manteve exatamente o mesmo
  `updated_at`, tamanho de estado, uma entrada de auditoria e um anexo. O
  download foi portanto uma operação sem escrita sobre a origem.
- Um backup com `format_version=2` foi rejeitado com a mensagem explícita «A
  versão do formato de backup não é suportada.» e não criou sessão.
- A página inicial e o menu responsivo foram validados também a 390 × 844 px;
  o menu lateral ficou oculto até à ação «Abrir navegação». O logout terminou
  apenas a autenticação corrente e conduziu ao ecrã de acesso.

### Defeito encontrado e correção

- **E2E07-F01 — notificações sucessivas:** na `v0.3.93`, depois de a primeira
  notificação expirar, o segundo erro tentou executar `dismiss/delete` sobre um
  elemento NiceGUI já eliminado. O servidor registou «An element has been
  deleted but is still being used» e a segunda mensagem não apareceu.
- A `v0.3.94`, commit `1608ec6`, passou a ignorar notificações já eliminadas e a
  usar `dismiss` como operação normal, reservando `delete` para recuperação de
  uma falha. Foram acrescentados três testes unitários de regressão.
- Em produção, três erros consecutivos voltaram a surgir corretamente, sem
  acumulação; a terceira notificação foi fechada pelo botão «Fechar» e o log da
  nova instância não repetiu o aviso.

### Conclusão

O E2E-07 fica **APROVADO APÓS A CORREÇÃO DA v0.3.94**. Autenticação,
isolamento, retoma, persistência, cópia/restauro, incompatibilidade de formato,
notificações, responsividade, logout e limpeza final ficaram validados no
ambiente de produção.

## E2E-08 — Fornecedor IAedu

**Estado:** APROVADO NA `v0.3.94`

**Aplicabilidade:** executar apenas se a IAedu continuar declarada como fornecedor
suportado na versão entregue ao estudo.

### Execução — v0.3.94

- Data: 06-09-2026.
- Ambiente: VPS pública `https://coeria.ivovargas.pt/`; CoerIA `v0.3.94`.
- Utilizador de teste: D12.
- Sessão temporária: «Fundamentos de Literacia de Dados — E2E-08 IAedu
  v0.3.94»; identificador `58e6a8bb-8a64-4bfb-a5f4-46a4ece555d9`.
- A existência da configuração IAedu foi confirmada sem ler nem apresentar o
  valor da chave. A sessão temporária foi eliminada no fim do ensaio.

### Critérios

- criar uma sessão com IAedu e confirmar persistência do fornecedor;
- pedir uma proposta localizada e uma verificação facultativa;
- confirmar aprovação/rejeição humana, auditoria e mensagens de erro sem dados sensíveis;
- confirmar falha explícita e recuperável quando a chave não está configurada;
- não exigir geração de imagens, que permanece associada ao fornecedor configurado
  para essa capacidade.

### Resultado

- A sessão foi criada manualmente com o fornecedor IAedu e Taxonomia SOLO. Após
  atualizar a página, a lista lateral manteve «IAedu · Formulação dos resultados
  de aprendizagem», confirmando a persistência do fornecedor.
- «Criar etapa completa com IA» devolveu sete resultados de aprendizagem. A
  proposta foi revista e aceite antes de criar a versão 1; a proveniência ficou
  visível como «IAedu Agent Chat API · Agente IAedu».
- Uma proposta limitada ao enunciado de RA1 foi recebida e rejeitada; o texto
  original permaneceu inalterado. Uma segunda proposta, limitada ao enunciado
  de RA2, foi editada pelo docente e aceite, criando a versão 2 sem modificar os
  restantes resultados.
- A verificação facultativa IAedu produziu dois avisos pedagógicos, relativos à
  exequibilidade de RA5 e à exigência cognitiva de RA7. A interface indicou
  explicitamente que o parecer não bloqueava e permitiu avançar para a etapa 3.
- A rastreabilidade continha oito entradas: criação manual, três propostas sem
  aplicação automática, aceitação da proposta integral, rejeição de RA1,
  aceitação editada de RA2 e verificação facultativa. Não foram apresentados
  códigos de acesso nem chaves de API.
- A ausência de `IAEDU_API_KEY` foi simulada num processo isolado que executou o
  código da versão instalada, sem mudar o ficheiro de configuração nem reiniciar
  o serviço. Foi devolvido `ValueError` com a mensagem explícita «IAEDU_API_KEY
  não está disponível. Configure-a como variável de ambiente do utilizador e
  reinicie a aplicação.» Uma nova verificação na sessão normal teve sucesso em
  seguida, confirmando recuperação e ausência de impacto no serviço.
- A etapa 7 abriu com seleção manual de recursos e sem exigir imagens. A
  assistência textual permanece associada à IAedu; uma eventual geração de
  imagem é uma ação separada da OpenAI Image API e não foi executada neste caso.
- Depois da eliminação, a sessão deixou de surgir na interface e na base de
  dados. O navegador ficou no ecrã de autenticação.

### Conclusão

O E2E-08 fica **APROVADO NA v0.3.94**. A integração IAedu respeitou a seleção do
fornecedor, o controlo humano, a assistência localizada, a verificação
facultativa, a auditoria e a separação entre geração textual e geração de
imagens. Com este resultado, os oito cenários da campanha manual atual ficaram
executados.

---

## Histórico de desenvolvimento — campanhas v0.2.x sem validade atual

## Versão de referência

- Congelamento inicial: CoerIA v0.2.11
- Suíte automatizada no congelamento: 120 testes + 4 subtestes aprovados
- Regra durante A5: apenas correções de defeitos encontrados nos testes manuais

## E2E-01 — Fluxo completo base

**Estado:** APROVADO COM OBSERVAÇÕES

**Caso:** Fundamentos de Redes de Computadores; OpenAI; SOLO; quatro recursos; geração de imagens por IA desativada.

### Resultado

- Proposta inicial: OK
- Conteúdos/objetivos: OK
- Resultados de aprendizagem: OK, após nova tentativa manual
- Estratégia pedagógica: OK
- Métodos/atividades: OK
- Avaliação: OK
- Matriz: OK
- Recursos: OK
- Edição manual: OK
- Exportação: OK
- Persistência: OK

### Evidência

- PowerPoint abriu o PPTX sem reparação.
- 11 slides exportados pelo PowerPoint de secretária para PNG.
- Síntese final com conteúdo.
- ZIP com programa, ficha, teste, atividade prática, manifesto, matriz e rastreabilidade.
- `quality.passed = true` no manifesto.
- Sessão reaberta como concluída após refresh.

### Defeitos/observações

- **RA-01 — bloqueante na etapa, recuperável:** guardrail de um verbo principal rejeitou repetidamente resultados com ações coordenadas. Um segundo clique permitiu continuar. Correção inicial: v0.2.12; correção final e reteste: v0.2.13.
- **VIS-01 — menor/não bloqueante:** quebra indevida de palavras em caixas PowerPoint, p.ex. “Comunicaç ão” e “Endereçam ento”.

## E2E-01R — Regressão do guardrail dos RA

### Execução 1 — v0.2.12

**Estado:** FALHOU

- Um clique → RA: FALHOU
- Começam pelo `action_verb`: não verificável em produção
- Sem duas ações principais coordenadas: não verificável
- “Explicar/Reconhecer como…” aceite: não verificável em produção
- Cobertura C1–C5 e objetivos: não verificável

#### Observação principal

A regra nova detetou corretamente coordenações inválidas, mas as três tentativas automáticas do `gpt-4o-mini` repetiram a estrutura dos objetivos gerais compostos. Exemplos observados:

- A4: `Definir endereços IP e explicar como interpretá-los.`
- A5: `Classificar e montar topologias simples de redes.`

Os objetivos gerais de origem já continham coordenações, p.ex. `Interpretar endereços IP e montar topologias simples de redes.`

#### Ação corretiva

Implementada em v0.2.13:

1. feedback de reparação promovido para instruções de alta prioridade do modelo;
2. instrução explícita para não repetir a resposta rejeitada e separar ações coordenadas em RAs diferentes;
3. fallback conservador após esgotar retentativas, apenas quando o único defeito remanescente é uma segunda ação principal coordenada e o enunciado já começa pelo verbo declarado;
4. registo das correções em `guardrail_corrections` e nos metadados da proposta.

### Execução 2 — v0.2.13

**Estado:** APROVADO

**Caso:** Fundamentos de Redes de Computadores; OpenAI; SOLO.

### Resultado

- Um clique → RA: OK
- Começam pelo `action_verb`: OK
- Sem duas ações principais coordenadas: OK
- “Explicar/Reconhecer como…” aceite: NÃO OCORREU nesta geração; comportamento coberto pelos testes automatizados
- Cobertura C1–C5: OK
- Cobertura dos objetivos gerais: OK
- Intervenção técnica/manual adicional: NÃO necessária
- Tentativas automáticas internas: 3

### RA observados

| ID | Verbo | Enunciado | Conteúdos | Objetivos |
|---|---|---|---|---|
| A1 | identificar | Identificar os principais modelos de comunicação em redes, como OSI e TCP/IP. | C1 | OG1 |
| A2 | identificar | Identificar endereçamento IPv4. | C2 | OG2 |
| A2.1 | aplicar | Aplicar conceitos de máscaras de sub-rede. | C2 | OG2 |
| A3 | classificar | Classificar os dispositivos de rede utilizados na comutação, como switches e routers. | C3 | OG3 |
| A4 | analisar | Analisar problemas de conectividade em redes locais utilizando ferramentas como ping e traceroute. | C4 | OG4 |
| A5 | aplicar | Aplicar medidas básicas de segurança em redes, nomeadamente autenticação e filtragem. | C5 | OG5 |

### Conclusão do reteste

- O docente avançou com um único clique em **Registar decisão e continuar**.
- Os objetivos gerais compostos não foram copiados literalmente para os RA.
- As três retentativas ocorreram internamente, sem erro vermelho nem repetição manual da ação.
- **RA-01: RESOLVIDO E RETESTADO em v0.2.13.**

### Observação adicional

- **RA-02 — menor/não bloqueante:** apareceu o identificador `A2.1`, que é invulgar mas não prejudica a cobertura, a rastreabilidade nem a progressão do fluxo. Monitorizar recorrência antes de considerar normalização automática dos IDs.

## E2E-02 — Fontes documentais extensas

**Estado:** FALHOU — ingestão/redução aprovadas; cobertura curricular por fonte não demonstrada

**Versão:** CoerIA v0.2.13

**Caso:** D04, UC «Currículo e Conteúdos Digitais»; OpenAI; SOLO; sessão nova.

**Fontes reais:** quatro PDFs, aproximadamente 1 338 739 caracteres extraídos:

- FUC Currículo e Conteúdos Digitais: ~11 mil caracteres;
- ADDIE: ~347 mil;
- Mayer: ~128 mil;
- Cognitive Load / Sweller: ~852 mil.

### Resultado

- Upload dos quatro PDFs: **OK**
- Antigo erro de 120 000 caracteres: **NÃO OCORREU**
- Redução automática: **OK**
- Intervenção manual para dividir/cortar fontes: **NÃO necessária**
- Blocos processados: **20**, numa passagem
- Tempo observado da redução: **~3 min 57 s**
- Avanço para Conteúdos e objetivos curriculares: **OK**
- Duplicações curriculares evidentes: **NÃO**
- Persistência após refresh: **OK**
- Nova redução após refresh: **NÃO**
- Cobertura aparente das quatro fontes no artefacto curricular: **FALHOU**
- Proveniência visível na etapa de Conteúdos e objetivos: **FALHOU**

### Mensagens observadas

A aplicação apresentou progressivamente:

- `A reduzir fontes extensas com IA (passagem 1, bloco 1/20)…`
- …
- `A reduzir fontes extensas com IA (passagem 1, bloco 20/20)…`
- `A gerar e validar «Conteúdos e objetivos curriculares»…`
- `Sessão iniciada e guardada.`

Após refresh:

- `Sessão retomada. As fontes incorporadas permanecem no estado guardado.`

### Qualidade observada

A proposta da etapa 1 ficou dominada pela FUC curta:

- C1: conceitos de currículo/tecnologia;
- C2: modelos de currículo;
- C3: inovação curricular;
- C4: métodos de ensino.

Os objetivos OG1–OG3 eram coerentes com essa ficha, mas não havia representação clara de:

- Mayer — princípios de aprendizagem multimédia;
- Sweller — carga cognitiva intrínseca, extrínseca/germânica;
- ADDIE — apenas uma possível referência indireta a design/avaliação.

Os 20 blocos foram processados, mas o artefacto curricular não permitiu demonstrar que as fontes longas influenciaram efetivamente a proposta.

### Proveniência observada

Na etapa de Conteúdos e objetivos não eram apresentados os nomes dos quatro PDFs nem as etiquetas internas `[Fonte reduzida: …]`. Os nomes permaneciam identificáveis apenas no passo de upload.

### Defeito identificado

- **SRC-01 — importante:** a redução automática percorre o conjunto documental, mas a análise curricular não garante nem demonstra representatividade por documento. Uma ficha curricular curta pode dominar semanticamente a proposta e as fontes de referência extensas podem não deixar rasto verificável.

### Ação corretiva prevista — v0.2.14

1. conservar no estado estatísticas de cada fonte reduzida (`source`, caracteres originais e número inicial de blocos);
2. preservar explicitamente conceitos distintivos, nomes de modelos, teorias, princípios, autores e frameworks durante a redução;
3. fornecer ao agente curricular a lista auditável de todas as fontes reduzidas e proibir prioridade automática à primeira/mais curta;
4. exigir no artefacto curricular `source_coverage`, com uma linha por fonte contendo contribuição específica, conceitos-chave e conteúdos `C*` associados;
5. validar deterministicamente que nenhuma fonte reduzida ficou sem uma linha de cobertura e que os IDs de conteúdo associados existem;
6. apresentar a tabela **Cobertura das fontes documentais** na própria etapa de Conteúdos e objetivos.

### Reteste necessário

Executar **E2E-02R** com os mesmos quatro PDFs após implantação da v0.2.14. O reteste só será aprovado se Mayer, Sweller, ADDIE e a FUC surgirem explicitamente na cobertura das fontes e a proposta curricular refletir contribuições distintas e plausíveis das referências.


## E2E-02R — Reteste da cobertura de fontes documentais

**Estado final:** APROVADO em v0.2.15

### Execução 1 — v0.2.14

**Estado:** FALHOU — reteste inválido por alteração não implantada

**Versão apresentada na UI:** CoerIA v0.2.14

**Sessão:** D05, «Currículo e Conteúdos Digitais — E2E-02R»; sessão nova; mesmos quatro PDFs do E2E-02.

### Resultado observado

- Redução automática: **OK** — 20/20 blocos, sem erro de 120 000 caracteres.
- Avanço para Conteúdos e objetivos: **OK**.
- Secção `Cobertura das fontes documentais`: **AUSENTE**.
- Quatro documentos explicitamente representados: **FALHOU**.
- FUC / âmbito curricular: **visível**.
- ADDIE / A-D-D-I-A: **não demonstrado**.
- Mayer / princípios multimédia: **não demonstrado**.
- Sweller / carga cognitiva: **não demonstrado**.

### Diagnóstico de release

A investigação posterior mostrou que a tag `v0.2.14` apontava para o mesmo commit da `v0.2.13` (`17fac7d`). No checkout do repositório `Aplicacao/prism/` não existiam `source_coverage` nem a secção `Cobertura das fontes documentais`.

O código da correção encontrava-se numa cópia fora do repositório (`Dissertacao_Mestrado/prism/`), pelo que não foi incluído no commit, na tag nem no deploy.

### Interpretação

Este reteste **não valida nem invalida tecnicamente a implementação prevista para SRC-01**, porque essa implementação não estava presente na versão efetivamente testada. O resultado demonstra antes uma falha no processo de publicação/empacotamento.

- **SRC-01:** mantém-se **ABERTO**, a aguardar reteste com a implementação efetivamente implantada.
- **REL-01 — importante:** uma release foi etiquetada sem incluir os ficheiros da correção pretendida. A versão exibida na UI não era suficiente para provar que o conteúdo da tag correspondia ao patch esperado.

### Ação corretiva — v0.2.15

1. copiar os ficheiros de `source_coverage` para dentro do repositório `C:\Dissertacao_Mestrado\Aplicacao`;
2. confirmar alterações reais com `git status`/`git diff`;
3. confirmar em `Aplicacao/prism/agents.py` a presença de `source_coverage` e em `Aplicacao/prism/presentation.py` a presença de `Cobertura das fontes documentais`;
4. executar a suíte automatizada completa;
5. criar **novo commit** e só depois a tag `v0.2.15`;
6. confirmar que o hash de `v0.2.15` é diferente do hash de `v0.2.13`/`v0.2.14`;
7. implantar a tag na VPS e confirmar no checkout de produção a presença do código antes de repetir E2E-02R.

### Reteste necessário

Repetir **E2E-02R** com os mesmos quatro PDFs depois da implantação válida da v0.2.15. O teste só será aprovado se a secção `Cobertura das fontes documentais` estiver presente e as quatro fontes tiverem contributos específicos e verificáveis.

### Execução 2 — v0.2.15

**Estado:** APROVADO

**Sessão:** D06, «Currículo e Conteúdos Digitais — E2E-02R2»; sessão nova; mesmos quatro PDFs reais do E2E-02.

### Resultado

- Redução automática: **OK** — 20/20 blocos.
- Antigo erro de 120 000 caracteres: **NÃO OCORREU**.
- Avanço para Conteúdos e objetivos: **OK**.
- Secção `Cobertura das fontes documentais`: **OK**.
- Quatro documentos explicitamente representados: **OK**.
- Contributo da FUC: **OK**.
- Contributo do documento ADDIE: **OK**.
- Contributo de Mayer: **OK**.
- Contributo de Sweller / Cognitive Load Theory: **OK**.

### Evidência de cobertura

| Fonte | Contributo verificável | Conteúdos associados |
|---|---|---|
| FUC ULisboa | objetivos/competências do mestrado; organização curricular; inovação pedagógica | C1–C3, com ligações adicionais a C4 e C6 |
| Cognitive Load | Teoria da Carga Cognitiva e implicações para o design instrucional | C4 |
| Mayer | princípios da aprendizagem multimédia; efeito de modalidade | C5 |
| ADDIE | modelo ADDIE; fases do processo; design instrucional | C6 |

A tabela curricular passou a refletir contribuições distintas das fontes extensas, incluindo:

- C4 — **Teoria da Carga Cognitiva**;
- C5 — **Aprendizagem Multimédia**;
- C6 — **Abordagem ADDIE**;
- C1–C3 — âmbito curricular e pedagógico da FUC.

Os OG1–OG3 mantiveram-se centrados na ficha da unidade curricular, o que é aceitável neste caso: as fontes complementares deixaram rasto específico nos conteúdos e na matriz de cobertura sem forçar artificialmente a criação de objetivos gerais por documento.

### Observações menores

- **SRC-02 — menor/não bloqueante:** alguns nomes de ficheiros aparecem com prefixos numéricos (`0001…`, `01…`, `02…`, `03…`). Permanecem identificáveis, mas a apresentação pode ser limpa numa revisão futura.
- **SRC-03 — menor/não bloqueante:** o contributo ADDIE é descrito por “fases” em vez de enumerar literalmente A/D/D/I/A. O modelo continua inequivocamente identificável.
- **SRC-04 — menor/não bloqueante:** a FUC ficou associada também a C4 e C6, o que é conceptualmente algo amplo, mas não prejudica a representatividade das quatro fontes nem a coerência global.

### Conclusão do reteste

O critério que falhou no E2E-02 e não chegou a ser testado validamente na primeira execução do E2E-02R **passou em v0.2.15**.

- **SRC-01: RESOLVIDO E RETESTADO em v0.2.15.**
- **REL-01: RESOLVIDO E RETESTADO** — a implementação correta foi incluída num commit distinto, etiquetada e implantada; a funcionalidade prevista ficou visível e operacional em produção.
- **E2E-02R: APROVADO.**

## E2E-03 — Imagens documentais selecionadas pelo docente

**Estado:** APROVADO

**Versão:** CoerIA v0.2.15

**Sessão:** nova — «Sistemas de IA com Human-in-the-Loop na Educação».

**Fonte:** `Human-In-the-loop.pdf`, com cerca de 65 mil caracteres e duas figuras reconhecíveis.

### Resultado

- Upload do PDF: **OK**.
- Miniaturas documentais apresentadas: **OK** — 2.
- Seleção explícita `Usar na apresentação`: **OK** — 2/2.
- Pré-visualização em Recursos educativos: **OK**.
- Aprovação e exportação: **OK**.
- PPTX aberto no PowerPoint de secretária: **OK**, sem reparação.
- Imagens documentais efetivamente usadas: **OK** — slides 2 e 3.
- Proveniência visual: **OK**.
- Texto alternativo: **OK**.
- Segundo clique/intervenção técnica: **NÃO necessária**.

### Evidência na matriz

Foram apresentadas duas miniaturas com ficheiro, página e dimensões:

- página 4 — nuvem de palavras / gráfico HITL — 1895 × 2189;
- página 10 — diagrama Environment / System / AI — 1658 × 986.

Ambas foram marcadas pelo docente em **Usar na apresentação**.

### Evidência em Recursos educativos

A área **IMAGENS SELECIONADAS** apresentou:

- slide 2 — `Introdução à IA com HITL` — imagem documental — página 4;
- slide 3 — `Avaliação de Riscos em Sistemas de IA` — imagem documental — página 10.

Cada imagem selecionada foi usada exatamente uma vez. Os restantes slides utilizaram diagrama nativo.

### Evidência no PowerPoint

O PowerPoint abriu o ficheiro com 6 slides, aproximadamente 1,6 MB, e exportou os slides para PNG sem solicitar reparação.

Nos slides 2 e 3, as figuras surgiram no painel direito com indicação da origem documental:

- `00_Human-In-the-loop.pdf · Página 4`;
- `00_Human-In-the-loop.pdf · Página 10`.

O rodapé visual apresentou, respetivamente, proveniência equivalente a:

- `Fonte visual: Imagem extraída de 00_Human-In-the-loop.pdf, Página 4.`
- `Fonte visual: Imagem extraída de 00_Human-In-the-loop.pdf, Página 10.`

### Texto alternativo observado

- slide 2: `Imagem relacionada à definição e importância do Human-in-the-loop em IA.`
- slide 3: `Gráfico representando a avaliação de risco no uso de IA.`

### Observações menores

- **SRC-02 — já registado, menor/não bloqueante:** o nome do PDF permanece prefixado (`00_Human-In-the-loop.pdf`).
- **VIS-02 — menor/não bloqueante:** o texto alternativo do slide 3 classifica a figura como “gráfico”, embora visualmente seja mais próximo de um diagrama de entidades. A descrição continua funcional, mas pode ser semanticamente refinada numa revisão futura.

### Conclusão

O percurso completo **seleção humana → pré-visualização → aprovação → exportação → PowerPoint real** foi validado. As imagens documentais escolhidas pelo docente foram efetivamente incorporadas nos slides com proveniência e texto alternativo.

- **E2E-03: APROVADO.**
- O requisito do A3 relativo ao uso de imagens documentais escolhidas pelo docente fica validado manualmente em produção.

## E2E-04 — Imagens geradas por IA

**Estado:** APROVADO

**Versão:** CoerIA v0.2.15

**Sessão:** nova — «Feedback Formativo com IA»; OpenAI; SOLO; apenas apresentação PowerPoint; sem ficheiros documentais.

### Resultado

- Consentimento explícito para geração de imagens por IA: **OK**.
- Imagens documentais selecionadas: **NENHUMA**.
- Imagens IA geradas: **OK — 2**.
- Pré-visualização antes da aprovação: **OK**.
- Incorporação no PPTX: **OK**.
- PowerPoint abriu sem reparação: **OK**.
- Indicação visual de imagem gerada por IA: **OK**.
- Fornecedor e modelo: **OK — OpenAI Image API · gpt-image-2**.
- `manifesto.json` com prompt/instrução utilizada: **OK**.
- Texto alternativo: **OK**.
- Restantes slides com diagrama nativo: **OK**.
- Fallback por limite configurado de imagens: **OK**, com aviso explícito.

### Evidência em Recursos educativos

Na primeira proposta de recursos e novamente após reformulação, os slides 2 e 3 foram apresentados como **Imagem gerada por IA**, com pré-visualização das ilustrações e metadados visíveis:

- `Gerada por IA · OpenAI Image API · gpt-image-2`;
- `1536×864 · qualidade low`;
- campo **Instrução utilizada** com o prompt completo.

A aplicação atingiu o limite configurado de duas imagens por apresentação e apresentou aviso explícito equivalente a:

- `foi atingido o limite configurado de imagens geradas por IA`.

Os restantes slides continuaram a utilizar diagramas nativos, conforme previsto.

### Evidência no manifesto

Em `visual_assets.ai_generated_images`, o `manifesto.json` contém duas entradas aprovadas. Para cada imagem foram confirmados:

- `provider`;
- `model`;
- `prompt`;
- `alt_text`;
- `size`;
- `quality`;
- estado de aprovação.

### Evidência no PowerPoint

O ficheiro PowerPoint abriu no PowerPoint de secretária com 8 slides, aproximadamente 2,3 MB, sem solicitar reparação.

Nos slides 2 e 3, as imagens geradas foram efetivamente incorporadas e apresentaram identificação equivalente a:

- `Gerada por IA · OpenAI Image API · gpt-image-2`;
- `Fonte visual: Imagem gerada por IA — OpenAI Image API, modelo gpt-image-2.`

Texto alternativo observado via COM:

- slide 2: `Ciclo que representa a interação entre IA e feedback formativo.`
- slide 3: `Visualização sobre critérios claros e comentários para feedback.`

Os restantes slides — capa, A3–A6 e síntese — utilizaram **diagrama nativo**.

### Ressalva do fluxo

A primeira proposta de recursos já cumpria os critérios visuais deste E2E, mas a validação automática impediu a aprovação porque a apresentação não cobria o resultado de aprendizagem **A3**. O docente solicitou reformulação com essa indicação; a versão 2 corrigiu a cobertura e foi exportada com sucesso.

Este bloqueio não foi causado pela geração visual e demonstra o funcionamento do mecanismo de validação/reformulação dos recursos.

- **RES-01 — menor/não bloqueante:** uma proposta inicial de recursos falhou a cobertura de um RA e exigiu reformulação humana. O comportamento de bloqueio foi correto; monitorizar recorrência para avaliar se o prompt dos recursos deve ser reforçado.

### Conclusão

O percurso **consentimento → geração → pré-visualização → aprovação → rastreabilidade → exportação → PowerPoint real** foi validado em produção.

- **E2E-04: APROVADO.**
- O requisito do A3 relativo à geração opcional e rastreável de imagens por IA fica validado manualmente em produção.
- O limite máximo de duas imagens e o respetivo fallback para diagrama também foram observados com aviso explícito.

## Registo histórico do ensaio de fallback visual

**Estado:** incorporado e aprovado no E2E-05 da campanha atual.

**Objetivo histórico:** validar que uma falha real na geração de imagem por IA
não bloqueia a geração/exportação dos recursos e produz um diagrama nativo com
aviso explícito ao docente.

### Critérios previstos

- sessão com geração de imagens por IA autorizada;
- provocar de forma controlada uma falha técnica da Image API;
- etapa de recursos continua disponível em vez de terminar com erro fatal;
- slide afetado regressa a `diagrama`;
- aviso explícito informa o docente sobre o fallback e a respetiva causa;
- nenhuma imagem inválida/corrompida é persistida como aprovada;
- apresentação exporta normalmente;
- PPTX abre no PowerPoint real sem reparação;
- manifesto/estado não apresentam uma imagem IA inexistente como se tivesse sido gerada com sucesso.

### Método recomendado

Efetuar este cenário de forma controlada, preferencialmente fora de horário de utilização, alterando temporariamente apenas o modelo de imagem na configuração da VPS para um identificador inválido, reiniciando o serviço, executando uma única sessão de teste e restaurando imediatamente `gpt-image-2`. Não alterar a `OPENAI_API_KEY`, porque isso também afetaria as chamadas textuais.
