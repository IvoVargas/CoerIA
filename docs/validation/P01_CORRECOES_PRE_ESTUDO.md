# Correções após o ensaio técnico P01

Versão: v0.3.112, commit f6c9388. Publicada e instalada na VPS.

O ensaio P01 foi uma simulação automatizada, não uma participação de docente.
Os tempos e as respostas simuladas não integram os resultados da avaliação humana.

## Alterações

- Removido o redimensionamento proporcional automático das aulas. Um total incorreto
  é rejeitado e comunicado à geração seguinte, dentro do limite de tentativas existente.
  Não se inventam novas aulas nem se alteram silenciosamente durações para fechar o total.
- Mantida a obrigação de corresponder exatamente às horas de contacto.
- Aulas acima de 240 minutos recebem um aviso não bloqueante. Trata-se de um limiar
  operacional de revisão, não de uma regra pedagógica universal ou de um limite de Biggs.
- Modalidade de realização das TA limitada a «Trabalho individual» ou «Trabalho de grupo»,
  no editor, no esquema de geração e na validação. Não representa presencial/distância.
  Valores antigos incompatíveis requerem escolha explícita do docente; não são adivinhados.
- Aviso não bloqueante para TA sem referência direta no planeamento. Uma tarefa pode
  decorrer fora das aulas, pelo que as associações continuam opcionais.
- A mensagem de conclusão distingue verificação estrutural de revisão pedagógica.

## Verificação

Execução local em 23–24/09/2026: 369 testes e 7 subtestes passaram na suíte;
o teste restante de compilação real LaTeX passou numa repetição com acesso à pasta
de dados do MiKTeX (a primeira execução falhou por acesso negado do Windows).
Após a alteração da mensagem final, repetidos os testes de workflow e P01:
59 testes e 4 subtestes passaram. `git diff --check` sem erros de whitespace.
Nesta verificação automatizada não foram usados pedidos pagos à IA nem alteradas
sessões de produção. O reteste dirigido descrito abaixo utilizou IA real.

`tests/test_pilot_regressions.py` cobre modalidade, quatro aulas de 600 minutos,
dez aulas de 240 minutos, agendamento das TA e rejeição de totais incorretos.
O teste da proposta completa em `tests/test_workflow.py` verifica a nova tentativa
com resposta corrigida pelo fornecedor simulado, sem alteração automática de durações.

Publicação, reteste dirigido e alinhamento do manual concluídos. Continua pendente
o piloto humano. As instruções específicas do mini-cenário
(número de aulas e tarefas) devem ser efetivamente introduzidas na aplicação.

## Reteste dirigido na VPS — 24/09/2026

- Deploy: backup criado; 370 testes e 7 subtestes aprovados; HTTP local e HTTPS 200.
- Sessão separada em D12: «Reteste P01 — v0.3.112». Sessões anteriores preservadas.
- Contexto introduzido explicitamente: 40 horas de contacto, 80 autónomas,
  10 aulas de 240 minutos, 4 RA, 4 temas, duas TA individuais (uma formativa e
  outra sumativa). A geração das aulas pela OpenAI foi expressamente autorizada.
- Fluxo RA → conteúdos → TA → AE → aulas percorrido no navegador. Duas TA geradas
  com a modalidade «Trabalho individual» no seletor; finalidades Formativa/Sumativa.
- Planeamento gerado com dez durações de 240 minutos, total 2400 minutos.
  Não foi necessário corrigir manualmente as durações.
- Seleção automática persistiu apenas Plano de aulas e Grelha de avaliação.
  Confirmação mostrou zero gerações de texto e dois recursos derivados.
- Após expirar a autenticação, a proposta pendente foi recuperada, revista e
  aplicada normalmente, sem repetir a geração.
- Validação final estrutural aprovada; modalidade controlada apresentada entre os
  controlos. Mensagem distingue estrutura válida de adequação pedagógica.
- Sessão concluída. Exportação solicitada em Word e LaTeX/PDF; interface confirmou
  «Pacote preparado e evento registado na rastreabilidade».
  O ZIP foi posteriormente fornecido pelo investigador e inspecionado, conforme abaixo.

### Inspeção independente do pacote exportado

- Ficheiro: `coeria_Reteste_P01_v0_3_112_jrbt8z2y.zip`.
- SHA-256: `3b4baf1a7a91f5b463d04cd77834b52fb06f83e3a2491715d32a185f3a1f63a4`.
- Integridade ZIP/CRC: sem erros.
- Conteúdo: programa da UC, Plano de aulas e Grelha de avaliação, cada um em
  DOCX, TEX e PDF; síntese de alinhamento, rastreabilidade, manifesto e estado.
- PDFs: 8 páginas do programa, 1 do plano e 1 da grelha; as dez páginas foram
  renderizadas e inspecionadas, sem cortes de conteúdo. Subsistem espaços em
  branco e um título de secção no fim de página, sem perda de informação.
- Estado exportado: dez aulas de 240 minutos, total 2400; duas TA individuais,
  uma Formativa e outra Sumativa; 20 controlos aprovados, sem avisos ou erros.
- Apenas os dois recursos derivados selecionados foram incluídos, além do
  programa e ficheiros de rastreabilidade comuns ao pacote.
- Não foi efetuada nesta inspeção uma revisão visual independente dos DOCX
  no Word. A inspeção dos PDFs não é uma aprovação semântica dos conteúdos.

**Resultado do reteste técnico dirigido: aprovado no âmbito descrito.**
Não equivale a repetir toda a campanha E2E nem a validar pedagogicamente o sistema.

### Limites e observações

Não constitui piloto humano nem aprovação pedagógica do conteúdo. Mantiveram-se as
propostas para documentar o comportamento do sistema, incluindo: todos os temas ligados
a todos os RA, contextos de AE pouco adequados (p. ex., Trabalho de campo), referência
a encerramento na aula 8 antes das aulas 9 e 10, e avaliações referenciadas em mais de
uma aula. Estes pontos requerem revisão humana, não foram certificados pelos verdes.
O texto explicativo dos formatos de exportação ainda não enumera Plano/Grelha.
Os avisos de aulas longas e TA não agendadas foram verificados por regressões automáticas;
não foram provocados artificialmente neste percurso de dez aulas.

## Instrumentos e preparação do estudo

- Manual revisto para v0.3.112, com 12 páginas, disponibilizado em PDF;
  originais do investigador preservados. Capturas históricas identificadas,
  não integralmente substituídas.
- Questionário revisto em 24/09/2026: itens sobre controlos, recursos consultados
  e esforço clarificados; oito itens de opinião e escala mantidos.
- Cópias locais Markdown/PDF sincronizadas com o Forms. Resposta simulada P01
  identificada; o investigador informou ter apagado as respostas de teste.
- Não distribuir os ficheiros internos de tarefa/cenário: o manual integra o exemplo.

Próximos passos: confirmar condições éticas/consentimento e realizar piloto humano.
O código de referência permanece
v0.3.112; este registo documental não cria uma nova versão de código nem autoriza
o início da recolha. Ver `MATRIZ_RASTREABILIDADE_V0.3.112.md`.
