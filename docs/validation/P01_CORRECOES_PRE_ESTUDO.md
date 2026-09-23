# Correções após o ensaio técnico P01

Versão: v0.3.112. Publicação preparada; reteste manual dirigido na VPS pendente.

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
Não foram usados pedidos pagos à IA nem alteradas sessões de produção.

`tests/test_pilot_regressions.py` cobre modalidade, quatro aulas de 600 minutos,
dez aulas de 240 minutos, agendamento das TA e rejeição de totais incorretos.
O teste da proposta completa em `tests/test_workflow.py` verifica a nova tentativa
com resposta corrigida pelo fornecedor simulado, sem alteração automática de durações.

Antes do estudo: publicar mediante autorização, repetir o percurso dirigido na VPS,
alinhar o manual e executar um piloto humano. As instruções específicas do mini-cenário
(número de aulas e tarefas) devem ser efetivamente introduzidas na aplicação.
