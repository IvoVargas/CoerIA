# Matriz de rastreabilidade da versão v0.3.95

Este documento relaciona os requisitos consolidados do CoerIA com os módulos
implementados, os testes automatizados e os cenários manuais que constituem
evidência da versão candidata final.

## Evidência de referência

- versão candidata: `v0.3.95`;
- esquema de sessão: 33;
- formato de cópia de segurança: 3;
- suíte local: 334 testes e 7 subtestes aprovados em 07-09-2026, sem chamadas
  a fornecedores de IA;
- campanha manual: E2E-01 a E2E-08 concluídos na VPS entre `v0.3.83` e
  `v0.3.94`, com as correções encontradas incorporadas cumulativamente;
- reteste dirigido da `v0.3.95`: guardar uma seleção de recursos já revista
  retira o estado residual `needs_review`; a versão apresentada sem
  configuração externa é `0.3.95`.

O procedimento de deploy volta a executar a suíte integral numa base SQLite
temporária antes de reiniciar o serviço. O commit e os resultados efetivos da
VPS ficam registados no relatório de encerramento da campanha e na tag Git.

## Requisitos funcionais

| Requisito | Módulos principais | Testes automatizados | Evidência manual |
|---|---|---|---|
| RF01 — Dados iniciais e fontes | `app.py`, `application_service.py`, `ingestion.py`, `cnaef.py`, `isced.py`, `source_reduction.py` | `test_app.py`, `test_ingestion.py`, `test_cnaef.py`, `test_isced.py`, `test_source_reduction.py` | E2E-01, E2E-04, E2E-08 |
| RF02 — Fluxo pedagógico e taxonomias | `workflow.py`, `curriculum.py`, `ai_modes.py`, `manual_editing.py` | `test_workflow.py`, `test_manual_first_flow.py`, `test_manual_editing.py` | E2E-01, E2E-02, E2E-03 |
| RF03 — Human-in-the-loop | `workflow.py`, `assistance.py`, `application_service.py`, `app.py` | `test_assistance.py`, `test_manual_first_flow.py`, `test_app.py` | E2E-02, E2E-03, E2E-08 |
| RF04 — Validação automática | `quality.py`, `workflow.py`, `presentation.py` | `test_workflow.py`, `test_resources.py`, `test_app.py` | E2E-01, E2E-02, E2E-06 |
| RF05 — Avaliação, atividades e recursos | `agents.py`, `resource_catalog.py`, `quality.py`, `manual_editing.py` | `test_resources.py`, `test_workflow.py`, `test_manual_editing.py`, `test_image_generation.py` | E2E-04, E2E-05, E2E-06 |
| RF06 — Persistência, versões e rastreabilidade | `persistence.py`, `workflow.py`, `session_backup.py` | `test_persistence.py`, `test_history.py`, `test_session_backup.py`, `test_manual_first_flow.py` | E2E-03, E2E-07 |
| RF07 — Exportação | `exporter.py`, `resource_catalog.py` | `test_resources.py`, `test_session_backup.py` | E2E-01, E2E-04, E2E-05, E2E-06 |
| RF08 — Tratamento de erros | `app.py`, `application_service.py`, `providers.py` | `test_app.py`, `test_providers.py`, `test_image_generation.py` | E2E-05, E2E-07, E2E-08 |
| RF09 — Colaboração agentic controlada | `agents.py`, `workflow.py`, `assistance.py` | `test_workflow.py`, `test_assistance.py`, `test_providers.py` | E2E-02, E2E-06, E2E-08 |

## Requisitos não funcionais

| Requisito | Módulos ou artefactos principais | Testes automatizados | Evidência manual |
|---|---|---|---|
| RNF01 — Segurança e privacidade | `auth.py`, `persistence.py`, `session_backup.py`, configuração Nginx/systemd | `test_auth.py`, `test_persistence.py`, `test_session_backup.py`, `test_source_image_selection.py` | E2E-04, E2E-07, E2E-08 |
| RNF02 — Reprodutibilidade | ficheiros `requirements*.txt`, `.env.example`, `deploy/` e tag Git | suíte integral sem chaves; compilação LaTeX real | E2E-01, E2E-06, E2E-07 |
| RNF03 — Usabilidade e acessibilidade | `app.py`, `presentation.py`, `manual_editing.py` | `test_app.py`, `test_manual_editing.py` | E2E-01, E2E-03, E2E-05, E2E-07 |
| RNF04 — Desempenho e observabilidade | `source_reduction.py`, `agents.py`, `application_service.py`, `deploy/` | `test_source_reduction.py`, `test_providers.py`, `test_workflow.py` | E2E-04, E2E-06, E2E-07 |
| RNF05 — Manutenibilidade | separação `app.py`/`prism/`, testes, documentação e runbook | suíte integral e importação dos módulos | todos os cenários |

## Observações aceites

- A pertinência semântica de ligações propostas por IA não pode ser certificada
  apenas por igualdade de identificadores; permanece sujeita à decisão humana.
- As referências AE/TA no planeamento das aulas são opcionais por requisito.
  A aplicação exige a duração total exata e valida o alinhamento nas relações
  RA–AE e TA–AE/RA.
- A redução de documentos muito extensos tem custo variável e mensurável; os
  limites de ingestão e redução são configuráveis.
- Algumas tabelas Word muito largas podem quebrar visualmente palavras, sem
  perda de conteúdo, ficheiro inválido ou divisão de linhas de dados.

Estas observações não bloqueiam a utilização definida para o estudo e devem ser
apresentadas como limitações, não como funcionalidades não implementadas.
