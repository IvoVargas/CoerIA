"""Modelos de domínio independentes da interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .curriculum import TAXONOMY_SOLO, validate_taxonomy_choice


RESOURCE_PRESENTATION = "Apresentação PowerPoint"
RESOURCE_WORKSHEET = "Ficha de aula"
RESOURCE_TEST = "Teste"
RESOURCE_PRACTICAL = "Atividade prática"
SUPPORTED_RESOURCE_TYPES = (
    RESOURCE_PRESENTATION,
    RESOURCE_WORKSHEET,
    RESOURCE_TEST,
    RESOURCE_PRACTICAL,
)

SEMESTER_OPTIONS = ("1.º semestre", "2.º semestre")


def validate_semester(value: str | None) -> str:
    """Aceita um semestre vazio ou uma das duas opções institucionais."""

    semester = (value or "").strip()
    if semester and semester not in SEMESTER_OPTIONS:
        raise ValueError(
            "O semestre deve ser «1.º semestre» ou «2.º semestre»."
        )
    return semester


@dataclass(frozen=True)
class CourseInput:
    """Dados iniciais fornecidos pelo docente para uma unidade curricular."""

    unit_name: str
    source_text: str
    audience: str
    duration_hours: int
    taxonomy_type: str = TAXONOMY_SOLO
    program_name: str = ""
    program_type: str = ""
    academic_year: str = ""
    semester: str = ""
    cnaef_code: str = ""
    cnaef_name: str = ""
    ects_credits: float = 0.0
    contact_hours: float = 0.0
    autonomous_hours: float = 0.0
    general_aims: str = ""
    bibliography: str = ""

    @classmethod
    def create(
        cls,
        unit_name: str,
        source_text: str,
        audience: str = "Ensino superior",
        duration_hours: int | float | str = 12,
        taxonomy_type: str = TAXONOMY_SOLO,
        program_name: str = "",
        program_type: str = "",
        academic_year: str = "",
        semester: str = "",
        cnaef_code: str = "",
        cnaef_name: str = "",
        ects_credits: int | float | str = 0,
        contact_hours: int | float | str = 0,
        autonomous_hours: int | float | str = 0,
        general_aims: str = "",
        bibliography: str = "",
    ) -> "CourseInput":
        title = (unit_name or "").strip()
        text = (source_text or "").strip()
        target_audience = (audience or "").strip() or "Ensino superior"

        if not title:
            raise ValueError("Indique o nome da unidade curricular.")
        if len(text) < 40:
            raise ValueError(
                "Introduza pelo menos uma breve descrição ou conteúdos programáticos "
                "(40 caracteres)."
            )

        try:
            hours = int(float(duration_hours))
        except (TypeError, ValueError) as error:
            raise ValueError("A duração deve ser um número inteiro de horas.") from error

        if hours <= 0:
            raise ValueError("A duração deve ser superior a zero.")

        def non_negative_number(value: int | float | str, label: str) -> float:
            try:
                result = float(value or 0)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{label} deve ser um número.") from error
            if result < 0:
                raise ValueError(f"{label} não pode ser negativo.")
            return result

        return cls(
            unit_name=title,
            source_text=text,
            audience=target_audience,
            duration_hours=hours,
            taxonomy_type=validate_taxonomy_choice(taxonomy_type),
            program_name=(program_name or "").strip(),
            program_type=(program_type or "").strip(),
            academic_year=(academic_year or "").strip(),
            semester=validate_semester(semester),
            cnaef_code=(cnaef_code or "").strip(),
            cnaef_name=(cnaef_name or "").strip(),
            ects_credits=non_negative_number(ects_credits, "Os créditos ECTS"),
            contact_hours=non_negative_number(contact_hours, "As horas de contacto"),
            autonomous_hours=non_negative_number(
                autonomous_hours, "As horas de trabalho autónomo"
            ),
            general_aims=(general_aims or "").strip(),
            bibliography=(bibliography or "").strip(),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_resource_types(resource_types: list[str] | None) -> list[str]:
    """Valida e normaliza os tipos de recurso pedidos pelo docente."""

    selected = list(
        dict.fromkeys([RESOURCE_PRESENTATION] if resource_types is None else resource_types)
    )
    unknown = [item for item in selected if item not in SUPPORTED_RESOURCE_TYPES]
    if unknown:
        raise ValueError(f"Tipo de recurso não suportado: {', '.join(unknown)}.")
    if not selected:
        raise ValueError("Selecione pelo menos um tipo de recurso educativo.")
    return selected
