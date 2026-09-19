# Reabertura — ajuda teórica nos cabeçalhos (v0.3.110)

Data: 19-09-2026. Alteração solicitada após a congelação da v0.3.109.
Não modifica a tag congelada nem reclassifica a campanha A5 anterior.
Release preparada para publicação e deploy a pedido do utilizador.
Os resultados abaixo referem-se à verificação local; o procedimento de deploy
repete a suite na VPS antes de reiniciar o serviço.

## Âmbito

Ícone `help_outline` (interrogação num círculo) apenas nos cabeçalhos com
fundamentação relevante. Ligação direta ao recurso externo original, em nova
aba, sem página intermédia do CoerIA. O tooltip identifica o assunto, a fonte
e a abertura noutra aba. Os links têm nome acessível, foco visível, proteção
`noopener noreferrer` e política `no-referrer`.

O catálogo associa etapa/tabela/campo, não rótulos: «Tipo» dos RA remete para o
QNQ, mas «Tipo» das questões não. SOLO/Bloom depende da taxonomia da sessão.
As associações repetem-se na consulta, edição e revisão da proposta, incluindo
recursos por aula/tarefa e consulta do histórico. Não são inseridas nos ficheiros
exportados. Não altera modelos, prompts, validação, dados ou esquema de sessão.

## Fontes e critério editorial

| Campos / conceito | Recurso original |
| --- | --- |
| Tipo dos RA | [DGERT — QNQ](https://www.dgert.gov.pt/quadro-nacional-de-qualificacoes) |
| Nível e verbo SOLO | [University of Queensland — Structuring learning](https://itali.uq.edu.au/node/6593) |
| Nível e verbo Bloom | [Iowa State University — Bloom's Taxonomy](https://celt.iastate.edu/prepare-and-teach/design-your-course/blooms-taxonomy/) |
| Resultados e ligações de alinhamento | [Biggs (1996)](https://link.springer.com/article/10.1007/BF00138871) |
| Tarefas e evidências | [McTighe / ASCD — Backward Planning](https://ascd.org/el/articles/the-fundamentals-of-backward-planning) |
| Critérios | [Carnegie Mellon — Rubrics](https://www.cmu.edu/teaching/designteach/teach/rubrics.html) |
| Finalidade formativa/sumativa | [Carnegie Mellon — Formative and Summative Assessment](https://www.cmu.edu/teaching/assessment/basics/formative-summative.html) |
| Atividades, prática, acompanhamento e feedback | [Northern Illinois — Gagné's Nine Events](https://www.niu.edu/citl/resources/guides/instructional-guide/gagnes-nine-events-of-instruction.shtml) |
| Modos AI-off, AI-on, on-AI | [Brabrand e Denny (2026), versão 1](https://doi.org/10.35542/osf.io/m9yfk_v1) |

Os guias institucionais explicam os conceitos já usados no enquadramento da
dissertação; não são apresentados como novas teorias nem como certificação das
decisões do docente. Acesso integral a artigos e disponibilidade dos sites
dependem dos respetivos fornecedores. A consulta automatizada ao OSF devolveu
403; mantém-se o DOI bibliográfico já adotado na dissertação, sem o apresentar
como disponibilidade externa confirmada nesta verificação.

Sem ícone: identificadores de linha, tema/objeto, títulos, durações, modalidade,
contexto operacional, cotações/pesos, configuração visual e controlos técnicos.
As colunas de associação RA/TA/AE recebem ajuda sobre alinhamento, não sobre a
sintaxe dos identificadores.

## Verificação

- Testes automatizados: catálogo HTTPS fechado, escape HTML, exclusões,
  escolha SOLO/Bloom, normalização de caminhos de recursos por instância,
  cabeçalhos Markdown, links nativos, preservação do estado e propostas pendentes.
- No navegador local: inspeção visual do ícone em consulta e edição;
  confirmação de `target="_blank"` nos dez links da página de ensaio;
  clique no ícone QNQ abriu uma nova aba na DGERT, mantendo o formulário.
- Detetado e corrigido: a sanitização NiceGUI retirava `target` do Markdown.
  Um observador repõe apenas os atributos seguros dos ícones em cabeçalhos com
  URL exata do catálogo. A sanitização do conteúdo permanece ativa.
- Suite final: **364 testes e 7 subtestes passaram**, incluindo compilação
  LaTeX com o MiKTeX instalado. Os 13 testes em `test_theory_help.py` cobrem
  especificamente esta alteração. Um aviso de permissões impediu apenas a
  escrita do cache do pytest; não afetou os resultados.

Antes de voltar a congelar: publicar a versão e repetir na VPS o clique num
ícone em consulta/edição, bem como a mudança SOLO/Bloom. Não houve chamadas
pagas a fornecedores de IA neste trabalho.
