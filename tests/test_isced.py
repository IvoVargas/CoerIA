import pytest

from prism.assistance import validate_initial_fields
from prism.isced import ISCED_F_CATALOG, canonicalize_isced_f, isced_f_options
from prism.models import CourseInput


@pytest.mark.parametrize(
    ("code", "expected_name"),
    [
        ("06", "Tecnologias da informação e comunicação (TICs)"),
        ("061", "Tecnologias da informação e comunicação (TICs)"),
        ("0613", "Desenvolvimento e análise de software e aplicações informáticas"),
    ],
)
def test_catalog_accepts_the_three_official_hierarchy_levels(
    code: str,
    expected_name: str,
) -> None:
    assert canonicalize_isced_f(code) == (code, expected_name)
    assert isced_f_options()[code] == f"{code} — {expected_name}"


@pytest.mark.parametrize("code", ["6", "06134", "06A", "613", "a confirmar"])
def test_catalog_rejects_invalid_or_unknown_codes(code: str) -> None:
    with pytest.raises(ValueError, match="ISCED-F"):
        canonicalize_isced_f(code)


def test_catalog_contains_all_three_levels_and_canonicalizes_the_name() -> None:
    assert {len(code) for code in ISCED_F_CATALOG} == {2, 3, 4}
    assert canonicalize_isced_f("0313", "Texto inventado") == (
        "0313",
        "Psicologia",
    )


def test_course_keeps_cnaef_and_isced_independent() -> None:
    course = CourseInput.create(
        "Introdução à Programação",
        "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        cnaef_code="624",
        cnaef_name="Pescas",
        isced_f_code="0613",
        isced_f_name="Nome livre que deve ser substituído",
    )

    assert course.cnaef_code == "624"
    assert course.cnaef_name == "Pescas"
    assert course.isced_f_code == "0613"
    assert course.isced_f_name == (
        "Desenvolvimento e análise de software e aplicações informáticas"
    )


def test_initial_validation_reports_an_invalid_isced_code() -> None:
    result = validate_initial_fields(
        {
            "unit_name": "Introdução à Programação",
            "source_text": (
                "Algoritmos, variáveis, estruturas de controlo, funções e testes."
            ),
            "program_type": "Licenciatura",
            "duration_hours": 18,
            "taxonomy_type": "SOLO",
            "semester": "1.º semestre",
            "isced_f_code": "a confirmar",
            "isced_f_name": "Informática",
        }
    )

    assert result["valid"] is False
    assert any(item["target"] == "isced_f_code" for item in result["results"])
