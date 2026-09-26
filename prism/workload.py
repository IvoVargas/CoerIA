"""Carga de trabalho: DL 42/2005, artigo 5.º."""

from math import isfinite


def calculate_workload(ects=0, contact=0, autonomous=0, hours_per_ects=25):
    def number(value):
        try:
            result = float(value or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("ECTS e horas devem ser números válidos.") from exc
        if not isfinite(result) or result < 0:
            raise ValueError("ECTS e horas devem ser números finitos não negativos.")
        return result

    credits, contact, factor = map(number, (ects, contact, hours_per_ects))
    if not 25 <= factor <= 28:
        raise ValueError("As horas por ECTS devem estar entre 25 e 28.")
    if credits and not (credits * 2).is_integer():
        raise ValueError("Os créditos ECTS devem ser múltiplos de 0,5.")
    if credits:
        total = round(credits * factor, 6)
        if contact > total:
            raise ValueError("As horas de contacto não podem exceder as horas totais calculadas pelos ECTS.")
        autonomous = round(total - contact, 6)
    else:
        autonomous = number(autonomous)
        total = round(contact + autonomous, 6)
    return total, autonomous


def workload_issue(course):
    """Check stored ECTS sessions without silently rewriting historical data."""
    if not course.get("ects_credits"):
        return ""
    try:
        total, autonomous = calculate_workload(
            course.get("ects_credits"), course.get("contact_hours", 0),
            course.get("autonomous_hours", 0), course.get("hours_per_ects", 25),
        )
        if (abs(float(course.get("duration_hours", 0)) - total) > 1e-6
                or abs(float(course.get("autonomous_hours", 0)) - autonomous) > 1e-6):
            return "Reveja os Dados iniciais: as horas totais e autónomas não correspondem aos ECTS."
    except (ValueError, TypeError) as error:
        return str(error)
    return ""
