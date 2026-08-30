import pytest

from prism.assistance import validate_initial_fields
from prism.cnaef import CNAEF_CATALOG, canonicalize_cnaef, cnaef_options
from prism.models import CourseInput


@pytest.mark.parametrize(
    ("code", "expected_name"),
    [
        ("010", "Programas de base"),
        ("481", "Ciências informáticas"),
        ("624", "Pescas"),
        ("999", "Desconhecido ou não especificado"),
    ],
)
def test_catalog_accepts_official_cnaef_codes(
    code: str,
    expected_name: str,
) -> None:
    assert canonicalize_cnaef(code) == (code, expected_name)
    assert cnaef_options()[code] == f"{code} — {expected_name}"


@pytest.mark.parametrize("code", ["48", "0481", "48A", "a confirmar", "9999"])
def test_catalog_rejects_invalid_or_unknown_cnaef_codes(code: str) -> None:
    with pytest.raises(ValueError, match="CNAEF"):
        canonicalize_cnaef(code)


def test_catalog_is_complete_and_canonicalizes_the_name() -> None:
    assert len(CNAEF_CATALOG) == 116
    assert {len(code) for code in CNAEF_CATALOG} == {3}
    assert canonicalize_cnaef("311", "Texto inventado") == (
        "311",
        "Psicologia",
    )


def test_course_keeps_cnaef_and_isced_independent_and_canonical() -> None:
    course = CourseInput.create(
        "Introdução à Programação",
        "Algoritmos, variáveis, estruturas de controlo, funções e testes.",
        cnaef_code="481",
        cnaef_name="Texto inventado",
        isced_f_code="0831",
        isced_f_name="Texto também inventado",
    )

    assert course.cnaef_code == "481"
    assert course.cnaef_name == "Ciências informáticas"
    assert course.isced_f_code == "0831"
    assert course.isced_f_name == "Pescas"


def test_initial_validation_reports_an_invalid_cnaef_code() -> None:
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
            "cnaef_code": "a confirmar",
            "cnaef_name": "Informática",
        }
    )

    assert result["valid"] is False
    assert any(item["target"] == "cnaef_code" for item in result["results"])
