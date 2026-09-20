"""Ajuda editorial em português, sem IA nem dados da sessão.

A associação é explícita por etapa, tabela e campo, nunca apenas pelo rótulo.
Os ícones abrem um resumo local; as fontes externas são aprofundamento opcional.
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


@dataclass(frozen=True)
class FieldHelp:
    title: str
    meaning: str
    guidance: str
    example: str
    source: str


HELP = {
    "resultados-aprendizagem": FieldHelp(
        "Resultado de aprendizagem",
        "Descreve o desempenho que o estudante deverá conseguir demonstrar no fim da aprendizagem. Não é uma lista de temas nem uma ação do docente.",
        "Escreva uma frase com um verbo observável e aquilo sobre que incide a ação. Faça corresponder a exigência da avaliação ao desempenho descrito.",
        "Analisar duas soluções de um problema, justificando as vantagens e limitações de cada uma.",
        "resultados-aprendizagem"),
    "tipos-qnq": FieldHelp(
        "Tipo de resultado",
        "O QNQ distingue conhecimentos (saber), aptidões (aplicar conhecimentos e resolver problemas) e atitudes (autonomia e responsabilidade).",
        "Escolha o domínio predominante do resultado. Esta escolha não corresponde ao nível SOLO/Bloom nem atribui um nível de qualificação à unidade curricular.",
        "Conhecimentos: descrever princípios. Aptidões: aplicar um procedimento. Atitudes: assumir responsabilidade por uma decisão.",
        "tipos-qnq"),
    "solo": FieldHelp(
        "Nível SOLO",
        "SOLO descreve a complexidade da resposta: um aspeto (uni-estrutural), vários aspetos separados (multi-estrutural), aspetos relacionados (relacional) ou generalização para além do caso (abstrato expandido).",
        "Selecione a complexidade que espera observar no desempenho do estudante. O pré-estrutural descreve uma resposta inadequada, não uma meta desejável.",
        "Enumerar fatores sem os relacionar difere de explicar como esses fatores se influenciam: a segunda resposta exige integração.",
        "solo"),
    "solo-verbo": FieldHelp(
        "Verbo de ação — SOLO",
        "O verbo torna observável a ação pretendida. O nível SOLO depende da complexidade da resposta exigida, não apenas da palavra escolhida.",
        "Escolha um verbo compatível com o nível selecionado e use-o como ação principal do resultado. Evite formulações vagas como «conhecer» ou «saber».",
        "Para exigir integração, pode pedir «analisar as relações entre os fatores», em vez de apenas «enumerar os fatores».",
        "solo"),
    "bloom": FieldHelp(
        "Nível de Bloom",
        "A taxonomia revista distingue recordar, compreender, aplicar, analisar, avaliar e criar. Estes níveis descrevem processos cognitivos.",
        "Escolha o processo que o estudante deverá mobilizar. Verifique se a tarefa exige esse processo; um verbo, por si só, não garante o nível.",
        "Aplicar uma regra num caso difere de avaliar uma solução com base em critérios.",
        "bloom"),
    "bloom-verbo": FieldHelp(
        "Verbo de ação — Bloom",
        "O verbo explicita uma ação observável associada ao processo cognitivo pretendido.",
        "Escolha um verbo compatível com o nível de Bloom e complete a frase com o objeto da ação. Considere a tarefa e o contexto, não apenas o verbo.",
        "«Avaliar a adequação de uma solução segundo critérios de segurança» explicita o que será observado.",
        "bloom"),
    "alinhamento": FieldHelp(
        "Resultados associados",
        "O alinhamento construtivo articula os desempenhos pretendidos, as oportunidades de os praticar e as evidências usadas para os avaliar.",
        "Selecione apenas os resultados efetivamente trabalhados neste conteúdo ou recurso. A presença do identificador não prova que o desempenho esteja coberto.",
        "Se RA1 exige analisar um caso, o recurso deve apoiar essa análise e não apenas apresentar definições.",
        "alinhamento"),
    "ra-avaliados": FieldHelp(
        "Resultados avaliados",
        "Uma tarefa deve recolher evidência do desempenho definido nos resultados de aprendizagem a que está associada.",
        "Selecione os RA cuja aprendizagem será efetivamente demonstrada e apreciada nesta tarefa. Não associe um RA apenas por partilhar o mesmo tema.",
        "Para avaliar um RA que exige justificar decisões, peça uma justificação e inclua critérios para a apreciar.",
        "alinhamento"),
    "ta-preparadas": FieldHelp(
        "Tarefas de avaliação preparadas",
        "As atividades de ensino-aprendizagem devem proporcionar prática dos desempenhos que serão avaliados.",
        "Selecione as TA que esta atividade prepara. O CoerIA deriva os RA dessas tarefas; confirme se a atividade permite praticar todos os desempenhos associados.",
        "Antes de uma tarefa de análise de casos, proponha analisar um caso em pares e discutir a fundamentação.",
        "alinhamento"),
    "ra-derivados": FieldHelp(
        "Resultados derivados",
        "No CoerIA, os RA desta atividade são obtidos através das tarefas de avaliação associadas. A ligação técnica não substitui a apreciação pedagógica.",
        "Confirme se a atividade trabalha os RA apresentados. Para corrigir a associação, reveja as TA ligadas à atividade e os RA dessas tarefas.",
        "Se a atividade prepara TA1 e TA1 avalia RA1, RA1 aparece aqui; a prática deve corresponder ao desempenho de RA1.",
        "alinhamento"),
    "ae-associadas": FieldHelp(
        "Atividades de ensino-aprendizagem associadas",
        "A grelha relaciona a avaliação com as oportunidades que o estudante teve para desenvolver o desempenho pretendido.",
        "Confirme as AE que preparam a tarefa apresentada nesta linha. Para rever as ligações curriculares, edite as tarefas associadas às AE na etapa de ensino-aprendizagem.",
        "Uma tarefa de argumentação pode ser preparada por uma atividade de debate com análise dos argumentos.",
        "alinhamento"),
    "componentes-aula": FieldHelp(
        "Atividades e tarefas da aula",
        "O planeamento distribui no tempo as oportunidades de aprendizagem e de recolha de evidências.",
        "Selecione as AE e/ou TA que ocorrerão nesta aula. A associação é opcional; use o texto da aula para explicar outros momentos previstos.",
        "Uma aula pode incluir AE1 para praticar a análise e TA1 para recolher evidência desse desempenho.",
        "tarefas-e-evidencias"),
    "tarefas-e-evidencias": FieldHelp(
        "Tarefa de avaliação",
        "No backward design, define-se a evidência aceitável antes de planear as experiências de aprendizagem. A tarefa solicita o desempenho que será avaliado.",
        "Descreva o que o estudante fará, sobre que matéria e em que condições. Não escreva apenas o nome de um instrumento, como «teste».",
        "Comparar duas soluções para um caso e apresentar uma recomendação fundamentada.",
        "tarefas-e-evidencias"),
    "evidencia": FieldHelp(
        "Evidência de aprendizagem",
        "É o produto, a resposta ou o desempenho observável que permite apreciar se o resultado foi alcançado.",
        "Indique o que será recolhido ou observado. Distinga a ação pedida na tarefa da evidência que ficará disponível para avaliação.",
        "Relatório comparativo com argumentos, limitações e uma recomendação justificada.",
        "tarefas-e-evidencias"),
    "criterios": FieldHelp(
        "Critério de avaliação",
        "Um critério explicita uma característica usada para apreciar a qualidade da evidência. A cotação ou o peso não substituem o critério.",
        "Indique o que será apreciado e o que caracteriza um desempenho adequado, em relação ao RA e à tarefa.",
        "Justifica a decisão com argumentos pertinentes e reconhece pelo menos uma limitação.",
        "criterios"),
    "finalidade-avaliacao": FieldHelp(
        "Finalidade da avaliação",
        "A avaliação formativa apoia a melhoria durante a aprendizagem; a sumativa aprecia o desempenho alcançado num momento de balanço.",
        "Escolha de acordo com o uso da evidência, não apenas com o formato. Se for formativa, preveja feedback que o estudante possa utilizar.",
        "Um rascunho comentado antes da entrega é formativo; a apreciação do produto final pode ser sumativa.",
        "finalidade-avaliacao"),
    "atividades": FieldHelp(
        "Atividade de ensino-aprendizagem",
        "É uma experiência em que o estudante desenvolve e pratica o desempenho pretendido, com apoio adequado.",
        "Descreva o que o estudante faz para aprender. Articule a atividade com a tarefa de avaliação que prepara, em vez de indicar apenas uma ferramenta.",
        "Analisar um caso em pares, discutir alternativas e rever uma solução após a discussão.",
        "atividades"),
    "pratica": FieldHelp(
        "Prática do estudante",
        "A prática dá ao estudante oportunidade de executar o desempenho que deverá demonstrar.",
        "Explique o exercício ou a ação concreta que será praticada e como se relaciona com o resultado pretendido.",
        "Resolver dois casos progressivamente mais complexos e justificar as opções tomadas.",
        "atividades"),
    "acompanhamento": FieldHelp(
        "Acompanhamento",
        "É o apoio disponibilizado durante a aprendizagem para orientar o estudante na realização da atividade.",
        "Indique como o docente ou os pares apoiam o trabalho, sem substituir a ação que cabe ao estudante.",
        "O docente disponibiliza perguntas orientadoras e esclarece dificuldades durante a resolução.",
        "atividades"),
    "feedback": FieldHelp(
        "Feedback",
        "O feedback informa o estudante sobre o seu desempenho e ajuda-o a identificar o que pode melhorar. Não se reduz a uma classificação.",
        "Indique quem comenta, quando e como o estudante utilizará os comentários para rever o trabalho.",
        "Após a primeira tentativa, os pares comentam a fundamentação segundo os critérios e o estudante revê a resposta.",
        "feedback"),
    "modos-ia": FieldHelp(
        "Modo de utilização da IA na aprendizagem",
        "AI-off significa aprender sem IA; AI-on, aprender com IA como meio; on-AI, aprender sobre a própria IA.",
        "Nos RA, escolha as condições em que o estudante deverá demonstrar a aprendizagem. Nas TA e AE, o modo é herdado dos RA associados. Não se refere ao uso de IA pelo docente no CoerIA.",
        "AI-off: resolver autonomamente. AI-on: produzir e validar uma solução com IA. on-AI: analisar erros e limites da IA.",
        "modos-ia"),
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
    ("assessment_activities", (), "outcome_ids"): "ra-avaliados",
    ("assessment_activities", (), "ai_mode"): "modos-ia",
    ("assessment_activities", (), "assessment_purpose"): "finalidade-avaliacao",
    ("assessment_activities", (), "activity"): "tarefas-e-evidencias",
    ("assessment_activities", (), "evidence"): "evidencia",
    ("assessment_activities", (), "criterion"): "criterios",
    ("teaching_activities", (), "assessment_ids"): "ta-preparadas",
    ("teaching_activities", (), "outcome_ids"): "ra-derivados",
    ("teaching_activities", (), "ai_mode"): "modos-ia",
    ("teaching_activities", (), "activity"): "atividades",
    ("teaching_activities", (), "practice"): "pratica",
    ("teaching_activities", (), "support"): "acompanhamento",
    ("teaching_activities", (), "feedback_strategy"): "feedback",
    ("pedagogical_design", ("lessons",), "component_ids"): "componentes-aula",
    ("resources", ("presentation_outline",), "outcome_ids"): "alinhamento",
    ("resources", ("lesson_worksheet", "sections"), "outcome_ids"): "alinhamento",
    ("resources", ("lesson_worksheet", "sections"), "activity"): "atividades",
    ("resources", ("test", "questions"), "outcome_id"): "alinhamento",
    ("resources", ("practical_activity", "steps"), "outcome_ids"): "alinhamento",
    ("resources", ("practical_activity", "criteria"), "criterion"): "criterios",
    ("resources", ("practical_activity", "criteria"), "description"): "criterios",
    ("resources", ("lesson_plan", "lessons"), "component_ids"): "componentes-aula",
    ("resources", ("assessment_grid", "rows"), "outcome_ids"): "ra-avaliados",
    ("resources", ("assessment_grid", "rows"), "teaching_activity_ids"): "ae-associadas",
    ("resources", ("assessment_grid", "rows"), "assessment_purpose"): "finalidade-avaliacao",
    ("resources", ("assessment_grid", "rows"), "activity"): "tarefas-e-evidencias",
    ("resources", ("assessment_grid", "rows"), "evidence"): "evidencia",
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
        result = {"SOLO": "solo", "BLOOM": "bloom"}.get(str(taxonomy).strip().upper())
        return f"{result}-verbo" if result and field == "action_verb" else result
    return topic


def theory_description(label: str, topic: str) -> str:
    return f"Ajuda: {label} — {HELP[topic].title} (abre uma explicação)"


def theory_header_html(label: str, topic: str | None) -> str:
    """Acionador de ajuda sem navegação externa nem dados da sessão."""
    text = escape(label)
    if topic not in HELP:
        return text
    description = escape(theory_description(label, topic), quote=True)
    return (
        f'{text} <a class="theory-help-link" href="#coeria-help-{topic}" role="button" '
        f'aria-haspopup="dialog" '
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
    """Diálogo nativo partilhado por cabeçalhos Markdown e NiceGUI.

    Conteúdo editorial inserido com textContent; não interpreta HTML da sessão.
    A delegação cobre também tabelas e histórico reconstruídos pela interface.
    """
    catalog = {
        key: {
            "title": item.title, "meaning": item.meaning,
            "guidance": item.guidance, "example": item.example,
            "source": TOPICS[item.source].title, "url": TOPICS[item.source].url,
        }
        for key, item in HELP.items()
    }
    payload = json.dumps(catalog, ensure_ascii=True).replace("<", "\\u003c")
    return """<script>
(() => {
    if (window.coeriaTheoryHelpInstalled) return;
    window.coeriaTheoryHelpInstalled = true;
    const catalog = __CATALOG__;
    let dialog;
    let opener;
    function element(tag, text, parent) {
        const node = document.createElement(tag);
        if (text) node.textContent = text;
        parent.appendChild(node);
        return node;
    }
    function openHelp(key, trigger) {
        const item = catalog[key];
        if (!item) return;
        if (!dialog) {
            dialog = element('dialog', '', document.body);
            dialog.className = 'coeria-theory-dialog';
            dialog.setAttribute('aria-labelledby', 'coeria-theory-title');
            dialog.addEventListener('close', () => {
                if (opener?.isConnected) opener.focus({preventScroll: true});
            });
            dialog.addEventListener('click', event => {
                const rect = dialog.getBoundingClientRect();
                if (event.target === dialog && (event.clientX < rect.left ||
                    event.clientX > rect.right || event.clientY < rect.top ||
                    event.clientY > rect.bottom)) dialog.close();
            });
        }
        opener = trigger;
        dialog.replaceChildren();
        const title = element('h2', item.title, dialog);
        title.id = 'coeria-theory-title';
        title.tabIndex = -1;
        for (const [heading, text] of [
            ['O que significa', item.meaning],
            ['O que preencher', item.guidance],
            ['Exemplo ilustrativo', item.example],
        ]) {
            element('h3', heading, dialog);
            element('p', text, dialog);
        }
        element('h3', 'Fonte / Saber mais', dialog);
        const source = element('a', item.source + ' (nova aba)', dialog);
        source.href = item.url;
        source.target = '_blank';
        source.rel = 'noopener noreferrer';
        source.referrerPolicy = 'no-referrer';
        element('p', 'Resumo editorial em português. O exemplo é ilustrativo; a fonte pode estar noutra língua ou ter acesso integral condicionado.', dialog).className = 'theory-source-note';
        const close = element('button', 'Fechar', dialog);
        close.type = 'button';
        close.addEventListener('click', () => dialog.close());
        if (!dialog.open) dialog.showModal();
        title.focus();
    }
    function handle(event) {
        const trigger = event.target.closest?.('th a.theory-help-link');
        if (!trigger) return;
        const href = trigger.getAttribute('href') || '';
        const prefix = '#coeria-help-';
        if (!href.startsWith(prefix)) return;
        const key = href.slice(prefix.length);
        if (!Object.prototype.hasOwnProperty.call(catalog, key)) return;
        if (event.type === 'keydown' && event.key !== ' ' && event.key !== 'Enter') return;
        event.preventDefault();
        event.stopPropagation();
        openHelp(key, trigger);
    }
    document.addEventListener('click', handle, true);
    document.addEventListener('keydown', handle, true);
})();
</script>""".replace("__CATALOG__", payload)
