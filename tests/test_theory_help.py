from copy import deepcopy
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from nicegui import ui
from nicegui.testing import User

import app
from prism.manual_editing import editor_layout
from prism.models import CourseInput
from prism.presentation import _table
from prism.theory_help import (
    FIELD_TOPICS, HELP, TOPICS, theory_header_html, theory_headers, theory_topic_for,
    theory_links_script,
)
from prism.workflow import create_session, create_test_agent


class Anchors(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def test_catalog_only_links_to_fixed_external_sources():
    for topic in TOPICS.values():
        assert urlsplit(topic.url).scheme == "https"
        assert urlsplit(topic.url).netloc
    for key, help_text in HELP.items():
        assert help_text.source in TOPICS
        assert all((help_text.title, help_text.meaning, help_text.guidance, help_text.example))
        link, = Anchors(theory_header_html("Campo", key)).links
        assert link["href"] == f"#coeria-help-{key}"
        assert link["role"] == "button"
        assert link["aria-haspopup"] == "dialog"
        assert "target" not in link
        assert "explicação" in link["aria-label"]
        assert "help_outline" in theory_header_html("Campo", "solo")
    assert set(FIELD_TOPICS.values()) <= set(HELP) | {"taxonomia"}


@pytest.mark.parametrize(("taxonomy", "topic"), [
    ("SOLO", "solo"), ("BLOOM", "bloom"), (" bloom ", "bloom"), ("unknown", None),
])
def test_taxonomy_source_matches_the_session(taxonomy, topic):
    assert theory_topic_for("learning_outcomes", (), "taxonomy_level", taxonomy) == topic
    assert theory_topic_for("learning_outcomes", (), "action_verb", taxonomy) == (
        f"{topic}-verbo" if topic else None
    )


def test_no_links_for_operational_fields_or_homonymous_labels():
    assert theory_topic_for("learning_outcomes", (), "id") is None
    assert theory_topic_for("learning_outcomes", (), "theme") is None
    assert theory_topic_for("resources", ("test", "questions"), "question_type") is None
    assert theory_topic_for("learning_outcomes", (), "outcome_type") == "tipos-qnq"
    assert theory_topic_for("pedagogical_design", ("lessons",), "duration_minutes") is None
    assert theory_topic_for("resources", ("presentation_outline",), "visual_mode") is None


def test_scoped_resources_use_the_same_sources():
    assert theory_topic_for("resources", ("tests", 2, "test", "questions"), "outcome_id") == "alinhamento"
    assert theory_topic_for("resources", ("lesson_presentations", 1, "presentation_outline"), "outcome_ids") == "alinhamento"


def test_headers_escape_text_and_unknown_topics_are_not_links():
    label = '<script>alert("x")</script>'
    assert "<script>" not in theory_header_html(label, "solo")
    assert not Anchors(theory_header_html(label, "invalid")).links
    with pytest.raises(ValueError):
        theory_headers(["ID"], "learning_outcomes", (), ["id", "statement"])


def test_markdown_table_preserves_cells_and_semantic_headers():
    rendered = _table(
        ["ID", "Tipo", "Resultado"], [["RA1", "Aptidões", "Texto | adicional"]],
        stage="learning_outcomes", fields=["id", "outcome_type", "statement"],
    )
    assert rendered.startswith("| ID | Tipo ")
    assert len(Anchors(rendered).links) == 2
    assert "Texto \\| adicional" in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("taxonomy", ["SOLO", "BLOOM"])
async def test_manual_headers_are_local_help_triggers_without_changing_state(user: User, taxonomy):
    state = create_session(
        CourseInput.create("Teste", "Algoritmos, funções, estruturas de dados e testes de software."),
        agent=create_test_agent(),
    )
    state["course"]["taxonomy_type"] = taxonomy
    original = deepcopy(state)

    @ui.page("/_test_theory_manual")
    def page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface._render_manual_table(
            state["learning_outcomes"],
            editor_layout("learning_outcomes").tables[0],
            stage="learning_outcomes",
        )

    await user.open("/_test_theory_manual")
    links = list(user.find(ui.link).elements)
    urls = [link.props.get("href") for link in links]
    assert f"#coeria-help-{taxonomy.lower()}" in urls
    assert f"#coeria-help-{taxonomy.lower()}-verbo" in urls
    assert "#coeria-help-tipos-qnq" in urls
    for link in links:
        assert link.props.get("target") != "_blank"
        assert link.props.get("aria-haspopup") == "dialog"
    assert state == original


def test_help_script_is_restricted_to_catalog_header_icons():
    script = theory_links_script()
    assert "th a.theory-help-link" in script
    assert "Object.prototype.hasOwnProperty.call(catalog, key)" in script
    assert "dialog.showModal()" in script
    assert "node.textContent = text" in script
    assert "opener.focus" in script
    assert "source.target = '_blank'" in script
    assert "source.rel = 'noopener noreferrer'" in script
    assert "innerHTML =" not in script
    assert "window.open" not in script


@pytest.mark.asyncio
async def test_proposal_headers_keep_the_same_sources_without_accepting_changes(user: User):
    state = create_session(
        CourseInput.create("Teste", "Algoritmos, funções, estruturas de dados e testes de software."),
        agent=create_test_agent(),
    )
    proposal = {
        "id": "P1", "stage": "learning_outcomes", "scope_path": [0],
        "before": deepcopy(state["learning_outcomes"][0]),
        "after": {**state["learning_outcomes"][0], "statement": "Identificar algoritmos simples."},
        "status": "pending",
    }
    original = deepcopy(state)

    @ui.page("/_test_theory_proposal")
    def page():
        interface = app.AGIRSoloInterface()
        interface.state = state
        interface._render_ai_proposal_review(state, "learning_outcomes", proposal)

    await user.open("/_test_theory_proposal")
    links = list(user.find(ui.link).elements)
    assert "#coeria-help-solo" in [link.props.get("href") for link in links]
    assert "#coeria-help-tipos-qnq" in [link.props.get("href") for link in links]
    assert all(link.props.get("target") != "_blank" for link in links)
    assert state == original
    assert proposal["status"] == "pending"


def test_distinct_fields_receive_actionable_guidance():
    for first, second in [
        ("solo", "solo-verbo"), ("bloom", "bloom-verbo"),
        ("tarefas-e-evidencias", "evidencia"), ("pratica", "acompanhamento"),
        ("ra-avaliados", "ra-derivados"),
    ]:
        assert HELP[first].guidance != HELP[second].guidance
