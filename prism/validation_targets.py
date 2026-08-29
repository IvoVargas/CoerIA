"""Destinos estruturais usados para localizar observações na interface."""

from __future__ import annotations

import re
from typing import Any


STAGE_ROOT_TARGET = "__stage__"


def _clean_identifier(value: Any) -> str:
    return str(value or "").strip()


def available_validation_targets(stage: str, artifact: Any) -> list[dict[str, str]]:
    """Lista apenas destinos que existem efetivamente no artefacto da etapa."""

    targets: list[dict[str, str]] = [
        {"key": STAGE_ROOT_TARGET, "label": "Toda a etapa"}
    ]

    def add(key: Any, label: str) -> None:
        clean_key = _clean_identifier(key)
        if clean_key and all(item["key"].casefold() != clean_key.casefold() for item in targets):
            targets.append({"key": clean_key, "label": label})

    if stage == "curriculum_analysis" and isinstance(artifact, dict):
        add("__summary__", "Síntese curricular")
        add("__objectives__", "Objetivos gerais")
        for item in artifact.get("contents", []):
            if isinstance(item, dict):
                identifier = _clean_identifier(item.get("id"))
                add(identifier, f"Tema {identifier}")
        add("__assumptions__", "Pressupostos")
    elif stage in {
        "learning_outcomes",
        "teaching_activities",
        "assessment_activities",
    } and isinstance(artifact, list):
        for item in artifact:
            if isinstance(item, dict):
                identifier = _clean_identifier(item.get("id"))
                add(identifier, identifier)
    elif stage == "pedagogical_design" and isinstance(artifact, dict):
        for index, item in enumerate(artifact.get("lessons", []), start=1):
            if isinstance(item, dict):
                add(f"LESSON:{index}", f"Aula {index}")
    elif stage == "resources" and isinstance(artifact, dict):
        selected = set(artifact.get("selected_types", []))
        resource_targets = (
            ("Apresentação PowerPoint", "RESOURCE:presentation", "Apresentação"),
            ("Ficha de aula", "RESOURCE:worksheet", "Ficha de aula"),
            ("Teste", "RESOURCE:test", "Teste"),
            ("Atividade prática", "RESOURCE:practical", "Atividade prática"),
        )
        for resource_type, key, label in resource_targets:
            if resource_type in selected:
                add(key, label)
        for index, _slide in enumerate(
            artifact.get("presentation_outline", []), start=1
        ):
            add(f"SLIDE:{index}", f"Slide {index}")
        worksheet = artifact.get("lesson_worksheet", {})
        for index, _section in enumerate(worksheet.get("sections", []), start=1):
            add(f"WORKSHEET:{index}", f"Secção {index} da ficha de aula")
        test = artifact.get("test", {})
        for index, question in enumerate(test.get("questions", []), start=1):
            identifier = _clean_identifier(question.get("id")) or f"Q{index}"
            add(identifier, f"Questão {identifier}")
        practical = artifact.get("practical_activity", {})
        for index, _step in enumerate(practical.get("steps", []), start=1):
            add(f"PRACTICAL:{index}", f"Etapa prática {index}")
        for index, _criterion in enumerate(practical.get("criteria", []), start=1):
            add(
                f"PRACTICAL_CRITERION:{index}",
                f"Critério da atividade prática {index}",
            )
    return targets


def resolve_validation_target(stage: str, artifact: Any, finding: dict[str, Any]) -> str:
    """Normaliza o destino devolvido pela IA e migra pareceres textuais antigos."""

    targets = available_validation_targets(stage, artifact)
    canonical = {item["key"].casefold(): item["key"] for item in targets}
    requested = _clean_identifier(finding.get("target"))
    if requested.casefold() in canonical:
        return canonical[requested.casefold()]

    text = f"{finding.get('criterion', '')} {finding.get('message', '')}"
    candidates = re.findall(
        r"\b(?:RA|AE|TA|Q|C)\d+\b", text, flags=re.IGNORECASE
    )
    candidates.extend(
        f"SLIDE:{number}"
        for number in re.findall(r"\bslide\s+(\d+)\b", text, flags=re.IGNORECASE)
    )
    candidates.extend(
        f"LESSON:{number}"
        for number in re.findall(r"\baula\s+(\d+)\b", text, flags=re.IGNORECASE)
    )
    for candidate in candidates:
        if candidate.casefold() in canonical:
            return canonical[candidate.casefold()]
    return STAGE_ROOT_TARGET
