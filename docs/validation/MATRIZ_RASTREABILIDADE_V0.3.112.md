# Rastreabilidade incremental da versão v0.3.112

Data: 24-09-2026. Código: `f6c93885cb8f56bfd6b813449a81e835ec22d266`.
Tag de referência: `v0.3.112`, publicada e instalada no reteste.

Esta matriz complementa `MATRIZ_RASTREABILIDADE_V0.3.109.md`; não substitui
evidência histórica por alegações de testes novos. A campanha integral permanece
histórica. O reteste P01 é técnico e automatizado, não avaliação com docentes.

| Âmbito | Evidência | Resultado e limite |
|---|---|---|
| RF02/RF04 — Duração do planeamento | `tests/test_pilot_regressions.py`, `tests/test_workflow.py`; P01 na VPS | Dez aulas de 240 minutos; total exato de 2400. Sem redimensionamento silencioso. |
| RF04/RF05 — Modalidade das TA | `tests/test_pilot_regressions.py`; seletor e estado exportado P01 | Trabalho individual/de grupo; duas TA individuais, Formativa e Sumativa. Não corresponde ao regime presencial/distância. |
| RF04 — Avisos de duração e agendamento | Regressões automáticas P01 | Aulas acima de 240 minutos e TA não agendadas produzem avisos; não provocados no reteste do navegador. |
| RF03/RF06 — Decisão e persistência | P01 na VPS | Proposta recuperada após expirar a autenticação, revista e aplicada sem nova geração. |
| RF05/RF06 — Seleção de recursos | P01 e pacote exportado | Apenas Plano de aulas e Grelha selecionados e produzidos; recursos derivados, sem chamadas de geração de texto. |
| RF07 — Exportação | ZIP com CRC válido; inspeção dos três PDF | 3 DOCX, 3 TEX e 3 PDF; dez páginas PDF sem cortes. Sem revisão visual independente dos DOCX nesta execução. |
| RF04 — Limites da validação | Mensagem final e observações P01 | Verdes confirmam controlos estruturais; pertinência dos contextos, ligações e progressão continua sujeita a revisão humana. |
| RNF02 — Regressões e deploy | Registo do deploy v0.3.112 | 370 testes e 7 subtestes aprovados; HTTP local/HTTPS 200 no deploy, não monitorização contínua. |

As ajudas contextuais introduzidas após v0.3.109 têm registos próprios em
`AJUDA_TEORICA_V0.3.110.md` e `AJUDA_CONTEXTUAL_V0.3.111.md`.

## Evidência e instrumentos

- Detalhes, checksum do pacote e limitações: `P01_CORRECOES_PRE_ESTUDO.md`.
- Registo agregado: `A5_REGISTO_TESTES_MANUAIS.md`.
- Manual de referência do estudo: `MANUAL_UTILIZADOR_V0_3_112.pdf`, 12 páginas.
- Questionário: revisão de 24-09-2026, sincronizada entre Forms e cópia local.
- Instrumentos guardados na pasta de trabalho `Testes_Utilizadores`, fora deste
  repositório da aplicação; não se presume que sejam publicados com esta matriz.

## Condições ainda pendentes

Confirmar consentimento e condições institucionais,
definir procedimentos de dados/apoio e realizar piloto humano. Não existem aqui
resultados de docentes. Não foram introduzidas alterações de código para fechar
este registo; a criação de outra tag ou deploy exige uma ação separada.
