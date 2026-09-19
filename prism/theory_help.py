"""Ligações editoriais a fontes teóricas, sem IA nem dados da sessão.

A associação é explícita por etapa, tabela e campo, nunca apenas pelo rótulo.
O catálogo contém exclusivamente recursos externos: não há página intermédia.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json


@dataclass(frozen=True)
class TheoryTopic:
    title: str
    url: str


TOPICS = {
    "resultados-aprendizagem": TheoryTopic(
        "Resultados e alinhamento construtivo — Biggs (1996)",
        "https://link.springer.com/article/10.1007/BF00138871",
    ),
    "tipos-qnq": TheoryTopic(
        "Conhecimentos, aptidões e atitudes — DGERT",
        "https://www.dgert.gov.pt/quadro-nacional-de-qualificacoes",
    ),
    "solo": TheoryTopic(
        "Taxonomia SOLO — University of Queensland",
        "https://itali.uq.edu.au/node/6593",
    ),
    "bloom": TheoryTopic(
        "Taxonomia de Bloom revista — Iowa State University",
        "https://celt.iastate.edu/prepare-and-teach/design-your-course/blooms-taxonomy/",
    ),
    "alinhamento": TheoryTopic(
        "Alinhamento construtivo — Biggs (1996)",
        "https://link.springer.com/article/10.1007/BF00138871",
    ),
    "tarefas-e-evidencias": TheoryTopic(
        "Backward design: evidências de aprendizagem — Jay McTighe / ASCD",
        "https://ascd.org/el/articles/the-fundamentals-of-backward-planning",
    ),
    "criterios": TheoryTopic(
        "Critérios e rubricas — Carnegie Mellon University",
        "https://www.cmu.edu/teaching/designteach/teach/rubrics.html",
    ),
    "finalidade-avaliacao": TheoryTopic(
        "Avaliação formativa e sumativa — Carnegie Mellon University",
        "https://www.cmu.edu/teaching/assessment/basics/formative-summative.html",
    ),
    "atividades": TheoryTopic(
        "Prática e acompanhamento: eventos de Gagné — Northern Illinois University",
        "https://www.niu.edu/citl/resources/guides/instructional-guide/gagnes-nine-events-of-instruction.shtml",
    ),
    "feedback": TheoryTopic(
        "Feedback: eventos de Gagné — Northern Illinois University",
        "https://www.niu.edu/citl/resources/guides/instructional-guide/gagnes-nine-events-of-instruction.shtml",
    ),
    "modos-ia": TheoryTopic(
        "AI-off, AI-on e on-AI — Brabrand e Denny (2026)",
        "https://doi.org/10.35542/osf.io/m9yfk_v1",
    ),
}


# Não acrescentar ajuda por aproximação de rótulos: «Tipo» no teste, por
# exemplo, não é o domínio do QNQ. Campos operacionais ficam sem associação.
FIELD_TOPICS = {
    ("learning_outcomes", (), "outcome_type"): "tipos-qnq",
    ("learning_outcomes", (), "taxonomy_level"): "taxonomia",
    ("learning_outcomes", (), "action_verb"): "taxonomia",
    ("learning_outcomes", (), "statement"): "resultados-aprendizagem",
    ("learning_outcomes", (), "ai_mode"): "modos-ia",
    ("curriculum_analysis", ("contents",), "outcome_ids"): "alinhamento",
    ("assessment_activities", (), "outcome_ids"): "alinhamento",
    ("assessment_activities", (), "ai_mode"): "modos-ia",
    ("assessment_activities", (), "assessment_purpose"): "finalidade-avaliacao",
    ("assessment_activities", (), "activity"): "tarefas-e-evidencias",
    ("assessment_activities", (), "evidence"): "tarefas-e-evidencias",
    ("assessment_activities", (), "criterion"): "criterios",
    ("teaching_activities", (), "assessment_ids"): "alinhamento",
    ("teaching_activities", (), "outcome_ids"): "alinhamento",
    ("teaching_activities", (), "ai_mode"): "modos-ia",
    ("teaching_activities", (), "activity"): "atividades",
    ("teaching_activities", (), "practice"): "atividades",
    ("teaching_activities", (), "support"): "atividades",
    ("teaching_activities", (), "feedback_strategy"): "feedback",
    ("pedagogical_design", ("lessons",), "component_ids"): "alinhamento",
    ("resources", ("presentation_outline",), "outcome_ids"): "alinhamento",
    ("resources", ("lesson_worksheet", "sections"), "outcome_ids"): "alinhamento",
    ("resources", ("lesson_worksheet", "sections"), "activity"): "atividades",
    ("resources", ("test", "questions"), "outcome_id"): "alinhamento",
    ("resources", ("practical_activity", "steps"), "outcome_ids"): "alinhamento",
    ("resources", ("practical_activity", "criteria"), "criterion"): "criterios",
    ("resources", ("practical_activity", "criteria"), "description"): "criterios",
    ("resources", ("lesson_plan", "lessons"), "component_ids"): "alinhamento",
    ("resources", ("assessment_grid", "rows"), "outcome_ids"): "alinhamento",
    ("resources", ("assessment_grid", "rows"), "teaching_activity_ids"): "alinhamento",
    ("resources", ("assessment_grid", "rows"), "assessment_purpose"): "finalidade-avaliacao",
    ("resources", ("assessment_grid", "rows"), "activity"): "tarefas-e-evidencias",
    ("resources", ("assessment_grid", "rows"), "evidence"): "tarefas-e-evidencias",
    ("resources", ("assessment_grid", "rows"), "criterion"): "criterios",
}


def theory_topic_for(
    stage: str,
    table_path: tuple[str | int, ...],
    field: str,
    taxonomy: str = "SOLO",
) -> str | None:
    path = tuple(table_path)
    if stage == "resources":
        if len(path) >= 3 and path[0] == "tests" and isinstance(path[1], int):
            path = path[2:]
        elif (
            len(path) >= 3 and path[0] == "lesson_presentations"
            and isinstance(path[1], int)
        ):
            path = path[2:]
    topic = FIELD_TOPICS.get((stage, path, field))
    if topic == "taxonomia":
        return {"SOLO": "solo", "BLOOM": "bloom"}.get(str(taxonomy).strip().upper())
    return topic


def theory_description(label: str, topic: str) -> str:
    return f"Fundamentação teórica: {label} — {TOPICS[topic].title} (abre numa nova aba)"


def theory_header_html(label: str, topic: str | None) -> str:
    """Cabeçalho acessível com ligação direta a uma fonte do catálogo fechado."""
    text = escape(label)
    if topic not in TOPICS:
        return text
    description = escape(theory_description(label, topic), quote=True)
    url = escape(TOPICS[topic].url, quote=True)
    return (
        f'{text} <a class="theory-help-link" href="{url}" '
        f'target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" '
        f'aria-label="{description}" title="{description}">'
        '<span class="material-icons" aria-hidden="true">help_outline</span></a>'
    )


def theory_headers(
    labels: list[str], stage: str, table_path: tuple[str | int, ...],
    fields: list[str], taxonomy: str = "SOLO",
) -> list[str]:
    if len(labels) != len(fields):
        raise ValueError("Cada cabeçalho deve corresponder a um campo.")
    return [
        theory_header_html(label, theory_topic_for(stage, table_path, field, taxonomy))
        for label, field in zip(labels, fields, strict=True)
    ]


def theory_links_script() -> str:
    """Reaplica atributos seguros após a sanitização do Markdown pelo NiceGUI.

    Não desativa a sanitização: só aceita ícones de ajuda em cabeçalhos, com URLs
    exatas do catálogo editorial. Também cobre o histórico atualizado em direto.
    """
    urls = json.dumps(sorted({topic.url for topic in TOPICS.values()}))
    return """<script>
(() => {
    if (window.coeriaTheoryLinksInstalled) return;
    window.coeriaTheoryLinksInstalled = true;
    const allowed = new Set(__URLS__);
    const selector = 'th a.theory-help-link';
    function decorate(root) {
        const links = root.matches?.(selector) ? [root] : [];
        links.push(...(root.querySelectorAll?.(selector) || []));
        for (const link of links) {
            if (link.textContent.trim() !== 'help_outline' ||
                !allowed.has(link.getAttribute('href'))) continue;
            link.setAttribute('target', '_blank');
            link.setAttribute('rel', 'noopener noreferrer');
            link.setAttribute('referrerpolicy', 'no-referrer');
        }
    }
    decorate(document);
    new MutationObserver(records => {
        for (const record of records)
            for (const node of record.addedNodes)
                if (node.nodeType === Node.ELEMENT_NODE) decorate(node);
    }).observe(document.documentElement, {childList: true, subtree: true});
})();
</script>""".replace("__URLS__", urls)
