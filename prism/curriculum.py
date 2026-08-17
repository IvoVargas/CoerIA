"""Vocabulários e regras curriculares partilhados pelo fluxo CoerIA.

As listas são inspiradas na minuta de programas de UC fornecida como referência,
mas foram normalizadas para o protótipo e não constituem uma norma institucional.
"""

from __future__ import annotations

import re
import unicodedata


TAXONOMY_SOLO = "SOLO"
TAXONOMY_BLOOM = "Bloom"
TAXONOMY_CHOICES = (TAXONOMY_SOLO, TAXONOMY_BLOOM)

SOLO_LEVELS = (
    "Uni-estrutural",
    "Multi-estrutural",
    "Relacional",
    "Abstrato expandido",
)

# O nível pré-estrutural não é usado para formular resultados de aprendizagem.
SOLO_VERBS: dict[str, tuple[str, ...]] = {
    "Uni-estrutural": (
        "identificar",
        "nomear",
        "reconhecer",
        "definir",
        "recordar",
        "seguir",
    ),
    "Multi-estrutural": (
        "descrever",
        "enumerar",
        "classificar",
        "combinar",
        "selecionar",
        "resumir",
    ),
    "Relacional": (
        "analisar",
        "comparar",
        "relacionar",
        "explicar",
        "aplicar",
        "integrar",
        "argumentar",
    ),
    "Abstrato expandido": (
        "conceber",
        "criar",
        "formular",
        "generalizar",
        "teorizar",
        "avaliar",
        "refletir",
    ),
}

BLOOM_LEVELS = (
    "Recordar",
    "Compreender",
    "Aplicar",
    "Analisar",
    "Avaliar",
    "Criar",
)

BLOOM_VERBS: dict[str, tuple[str, ...]] = {
    "Recordar": (
        "identificar",
        "listar",
        "definir",
        "reconhecer",
        "recordar",
    ),
    "Compreender": (
        "descrever",
        "explicar",
        "resumir",
        "classificar",
        "comparar",
    ),
    "Aplicar": (
        "aplicar",
        "executar",
        "demonstrar",
        "usar",
        "resolver",
    ),
    "Analisar": (
        "analisar",
        "diferenciar",
        "organizar",
        "relacionar",
        "decompor",
    ),
    "Avaliar": (
        "avaliar",
        "argumentar",
        "justificar",
        "criticar",
        "validar",
    ),
    "Criar": (
        "criar",
        "conceber",
        "formular",
        "desenvolver",
        "planear",
    ),
}

TAXONOMY_LEVELS = {
    TAXONOMY_SOLO: SOLO_LEVELS,
    TAXONOMY_BLOOM: BLOOM_LEVELS,
}

# A numeração SOLO conserva o nível pré-estrutural como SOLO 1, embora esse
# nível não seja utilizado para formular resultados de aprendizagem no CoerIA.
TAXONOMY_LEVEL_NUMBERS = {
    TAXONOMY_SOLO: {
        level: number for number, level in enumerate(SOLO_LEVELS, start=2)
    },
    TAXONOMY_BLOOM: {
        level: number for number, level in enumerate(BLOOM_LEVELS, start=1)
    },
}

TAXONOMY_VERBS = {
    TAXONOMY_SOLO: SOLO_VERBS,
    TAXONOMY_BLOOM: BLOOM_VERBS,
}

OUTCOME_TYPES = (
    "Conhecimento teórico",
    "Aptidão prática ou técnica",
    "Competência social",
)

CONTENT_IMPORTANCE = ("Principal", "Secundária")
ASSESSMENT_PURPOSES = ("Formativa", "Sumativa")

LEARNING_CONTEXTS = (
    "Fora da sala de aula",
    "Apresentação externa",
    "Turma numerosa",
    "Pequeno grupo",
    "Laboratório",
    "Laboratório de informática",
    "Trabalho de campo",
    "Visita de estudo",
)

MIN_OUTCOMES = 4
RECOMMENDED_OUTCOMES = (5, 7)
MAX_OUTCOMES = 10


def normalise_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).casefold().strip()


def verb_allowed(level: str, verb: str) -> bool:
    """Indica se o verbo pertence ao vocabulário controlado do nível SOLO."""

    candidate = normalise_text(verb)
    return candidate in {normalise_text(item) for item in SOLO_VERBS.get(level, ())}


def validate_taxonomy_choice(value: str) -> str:
    """Normaliza a escolha exclusiva entre SOLO e Bloom."""

    candidate = normalise_text(value)
    for choice in TAXONOMY_CHOICES:
        if candidate == normalise_text(choice):
            return choice
    raise ValueError("A taxonomia deve ser SOLO ou Bloom.")


def taxonomy_level_label(taxonomy: str, level: str) -> str:
    """Acrescenta a posição numérica ao nome canónico de um nível."""

    selected = validate_taxonomy_choice(taxonomy)
    number = TAXONOMY_LEVEL_NUMBERS[selected].get(level)
    return f"{level} — {selected} {number}" if number is not None else str(level)


def taxonomy_level_options(taxonomy: str) -> dict[str, str]:
    """Devolve níveis canónicos como valores e rótulos numerados para a UI."""

    selected = validate_taxonomy_choice(taxonomy)
    return {
        level: taxonomy_level_label(selected, level)
        for level in TAXONOMY_LEVELS[selected]
    }


def taxonomy_verb_allowed(taxonomy: str, level: str, verb: str) -> bool:
    """Valida um verbo apenas contra a taxonomia escolhida para a sessão."""

    try:
        selected = validate_taxonomy_choice(taxonomy)
    except ValueError:
        return False
    candidate = normalise_text(verb)
    return candidate in {
        normalise_text(item) for item in TAXONOMY_VERBS[selected].get(level, ())
    }


def taxonomy_level_for_verb(taxonomy: str, verb: str) -> str | None:
    """Obtém o nível canónico associado a um verbo do catálogo selecionado."""

    selected = validate_taxonomy_choice(taxonomy)
    candidate = normalise_text(verb)
    return next(
        (
            level
            for level, verbs in TAXONOMY_VERBS[selected].items()
            if candidate in {normalise_text(item) for item in verbs}
        ),
        None,
    )


def taxonomy_catalogue_for_prompt(taxonomy: str) -> dict[str, list[str]]:
    selected = validate_taxonomy_choice(taxonomy)
    return {
        level: list(verbs) for level, verbs in TAXONOMY_VERBS[selected].items()
    }


def has_single_action_verb(
    statement: str,
    declared_verb: str,
    taxonomy: str,
) -> bool:
    """Confirma um único verbo de ação principal no resultado.

    Os agentes usam infinitivos de um catálogo controlado. A regra rejeita um
    segundo verbo desse catálogo e construções coordenadas como «analisar e
    comparar», mesmo que o segundo verbo não pertença ao nível selecionado.
    """

    selected = validate_taxonomy_choice(taxonomy)
    clean_statement = normalise_text(statement)
    clean_verb = normalise_text(declared_verb)
    if not clean_verb or not clean_statement.startswith(clean_verb + " "):
        return False

    all_verbs = {
        normalise_text(verb)
        for verbs in TAXONOMY_VERBS[selected].values()
        for verb in verbs
    }
    words = re.findall(r"[a-zà-öø-ÿ]+", clean_statement)
    controlled_occurrences = [word for word in words if word in all_verbs]
    if controlled_occurrences != [clean_verb]:
        return False

    coordinated_infinitive = re.search(
        r"\b(?:e|ou)\s+[a-zà-öø-ÿ]+(?:ar|er|ir)\b",
        clean_statement,
    )
    return coordinated_infinitive is None


def solo_catalogue_for_prompt() -> dict[str, list[str]]:
    """Representação serializável a incluir nas instruções dos agentes."""

    return {level: list(verbs) for level, verbs in SOLO_VERBS.items()}
