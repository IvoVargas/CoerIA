# Matriz de rastreabilidade da versão v0.3.109

Este documento relaciona os requisitos consolidados do CoerIA com os módulos,
os testes automatizados e a evidência manual da versão congelada.

## Evidência de referência

- versão congelada: `v0.3.109`;
- código retestado: `066aee1` (`v0.3.109-rc2`);
- esquema de sessão: 34;
- formato de cópia de segurança: 3;
- suíte local: 351 testes e 7 subtestes aprovados em 12-09-2026;
- suíte na VPS: 351 testes e 7 subtestes aprovados durante o deploy da candidata;
- campanha integral: E2E-01–E2E-08 concluídos na VPS entre `v0.3.83` e
  `v0.3.96`, com as correções incorporadas cumulativamente;
- reteste dirigido `v0.3.109`: fluxo `RA → TA → AE`, planeamento com 120 minutos,
  seleção automática de um único teste, geração, revisão humana, validação final
  e exportação combinada para Word, LaTeX e PDF;
- pacote dirigido: 197 303 bytes, com 2 DOCX, 2 TEX e 2 PDF.

O procedimento de deploy executa a suíte integral numa base SQLite temporária
antes de reiniciar o serviço. O detalhe cronológico e as limitações aceites
constam de `A5_REGISTO_TESTES_MANUAIS.md`.

## Requisitos funcionais

| Requisito | Módulos principais | Testes automatizados | Evidência manual |
|---|---|---|---|
| RF01 — Dados iniciais e fontes | `app.py`, `application_service.py`, `ingestion.py`, `cnaef.py`, `isced.py`, `source_reduction.py` | `test_app.py`, `test_ingestion.py`, `test_cnaef.py`, `test_isced.py`, `test_source_reduction.py` | E2E-01, E2E-04, E2E-08; reteste v0.3.109 |
| RF02 — Fluxo pedagógico e taxonomias | `workflow.py`, `curriculum.py`, `ai_modes.py`, `manual_editing.py` | `test_workflow.py`, `test_manual_first_flow.py`, `test_manual_editing.py` | E2E-01, E2E-02, E2E-03; reteste `RA → TA → AE` |
| RF03 — Human-in-the-loop | `workflow.py`, `assistance.py`, `application_service.py`, `app.py` | `test_assistance.py`, `test_manual_first_flow.py`, `test_app.py` | E2E-02, E2E-03, E2E-08; aceitação da proposta v0.3.109 |
| RF04 — Validação automática | `quality.py`, `workflow.py`, `presentation.py` | `test_workflow.py`, `test_resources.py`, `test_app.py` | E2E-01, E2E-02, E2E-06; validação final v0.3.109 |
| RF05 — Avaliação, atividades e recursos | `agents.py`, `resource_catalog.py`, `quality.py`, `manual_editing.py`, `presentation.py` | `test_resources.py`, `test_workflow.py`, `test_manual_editing.py`, `test_image_generation.py` | E2E-04, E2E-05, E2E-06; teste TA1 v0.3.109 |
| RF06 — Persistência, versões e rastreabilidade | `persistence.py`, `workflow.py`, `session_backup.py` | `test_persistence.py`, `test_history.py`, `test_session_backup.py`, `test_manual_first_flow.py` | E2E-03, E2E-07; seleção e exportação persistidas |
| RF07 — Exportação | `exporter.py`, `resource_catalog.py`, `application_service.py` | `test_resources.py`, `test_session_backup.py` | E2E-01, E2E-04, E2E-05, E2E-06; 2 DOCX + 2 TEX + 2 PDF |
| RF08 — Tratamento de erros | `app.py`, `application_service.py`, `providers.py`, `agents.py` | `test_app.py`, `test_providers.py`, `test_image_generation.py`, `test_resources.py` | E2E-05, E2E-07, E2E-08; recuperação da chave não canónica |
| RF09 — Colaboração agentic controlada | `agents.py`, `workflow.py`, `assistance.py` | `test_workflow.py`, `test_assistance.py`, `test_providers.py` | E2E-02, E2E-06, E2E-08; proposta revista na v0.3.109 |

## Requisitos não funcionais

| Requisito | Módulos ou artefactos principais | Testes automatizados | Evidência manual |
|---|---|---|---|
| RNF01 — Segurança e privacidade | `auth.py`, `persistence.py`, `session_backup.py`, Nginx/systemd | `test_auth.py`, `test_persistence.py`, `test_session_backup.py`, `test_source_image_selection.py` | E2E-04, E2E-07, E2E-08 |
| RNF02 — Reprodutibilidade | `requirements*.txt`, `.env.example`, `deploy/` e tags Git | suíte integral sem chaves; compilação LaTeX real | E2E-01, E2E-06, E2E-07; deploy rc2 |
| RNF03 — Usabilidade e acessibilidade | `app.py`, `presentation.py`, `manual_editing.py` | `test_app.py`, `test_manual_editing.py`, `test_resources.py` | E2E-01, E2E-03, E2E-05, E2E-07; tabela multilinha v0.3.109 |
| RNF04 — Desempenho e observabilidade | `source_reduction.py`, `agents.py`, `application_service.py`, `deploy/` | `test_source_reduction.py`, `test_providers.py`, `test_workflow.py` | E2E-04, E2E-06, E2E-07 |
| RNF05 — Manutenibilidade | separação `app.py`/`prism/`, testes, documentação e runbook | suíte integral e importação dos módulos | todos os cenários; encerramento v0.3.109 |

## Alterações da série v0.3.98–v0.3.109

- CITE-F de quatro dígitos e CNAEF de três dígitos, sem cruzamento obrigatório;
- tipos de resultados do QNQ e tema opcional;
- barra contextual e decisão explícita de propostas de IA;
- *backward design* com ligações diretas RA–TA e TA–AE e RA derivado nas AE;
- seleção de recursos por instância, seleção global e gravação automática;
- geração de testes tolerante a variantes de chaves de escolha múltipla;
- tabelas Markdown estáveis quando uma célula contém várias linhas.

## Observações aceites

- A pertinência semântica das ligações propostas por IA continua sujeita à
  decisão humana; os controlos determinísticos certificam estrutura e cobertura.
- As referências AE/TA no planeamento das aulas são opcionais; a duração total
  de contacto é exata e o alinhamento é validado na cadeia `RA → TA → AE`.
- A redução de documentos extensos tem custo variável e mensurável.
- Algumas tabelas Word muito largas podem quebrar visualmente palavras, sem
  perda de conteúdo, ficheiro inválido ou divisão das linhas de dados.

Estas observações não bloqueiam o âmbito definido para o estudo e são tratadas
como limitações da solução.
