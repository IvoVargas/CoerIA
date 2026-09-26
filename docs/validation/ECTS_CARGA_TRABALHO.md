# ECTS e carga de trabalho

Alteração de 26-09-2026, incluída na versão v0.3.113.

- Horas por ECTS: 25 por defeito. Revisão da interface na v0.3.114:
  dropdown entre 25 e 28 (incluindo meios valores), sem botão ou diálogo adicional.
  Valores fracionários já gravados são preservados. O valor deve corresponder
  ao adotado pela instituição. Total calculado internamente, sem campo visível.
- ECTS positivos em múltiplos de 0,5; total = ECTS × horas por crédito.
- Trabalho autónomo = total − contacto; contacto superior ao total é inválido.
- ECTS = 0 identifica formação sem créditos: contacto e trabalho autónomo
  permanecem editáveis; total calculado por soma.
- Gravação calcula novamente no domínio, independentemente dos valores da UI.
- IA não escolhe o fator institucional; zero explicitamente indicado como ECTS
  é preservado. Horas autónomas são derivadas quando há créditos.
- Fator persistido, reaberto e incluído no programa Word/LaTeX e no backup legível.
- Validação final deteta horas incompatíveis em sessões existentes sem as alterar.

Exemplo correto: 6 × 25 = 150 horas; 40 contacto + 110 autónomas.
Os materiais do estudo serão revistos separadamente, após estabilizar esta alteração.

Verificação local: 382 testes e 7 subtestes aprovados na suíte; o teste de
compilação real inicialmente bloqueado pelo acesso ao MiKTeX passou em repetição
com permissões adequadas. Após acrescentar a regressão de sessões inconsistentes,
os 13 casos de carga de trabalho e o teste LaTeX passaram (14 testes).
Incluído teste de interface para cálculo, campos só de leitura, cancelamento do
diálogo, retorno ao modo sem ECTS e contacto acima do total. Sem chamadas pagas à IA.

Fonte: artigo 5.º, alíneas c), d) e g), DL 42/2005:
https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2005-182019766
