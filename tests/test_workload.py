import pytest

from prism.workload import calculate_workload
from prism.models import CourseInput
from prism.workload import workload_issue


@pytest.mark.parametrize("factor,total,autonomous", [(25,150,110),(28,168,128),(27.5,165,125)])
def test_ects(factor,total,autonomous):
    assert calculate_workload(6,40,999,factor) == (total,autonomous)


def test_no_ects():
    assert calculate_workload(0,40,80) == (120,80)


def test_stored_inconsistent_session_is_not_silently_changed():
    course = dict(ects_credits=6, contact_hours=40, autonomous_hours=80, duration_hours=120)
    assert workload_issue(course)
    assert course['duration_hours'] == 120


@pytest.mark.parametrize("values", [(6,151,0,25),(6,40,0,24),(6,40,0,29),
                                    (4.8,40,0,25),(float('nan'),40,0,25),
                                    (6,float('inf'),0,25),(0,40,-1,25)])
def test_invalid(values):
    with pytest.raises(ValueError):
        calculate_workload(*values)


def test_domain_recalculates_untrusted_autonomous_hours():
    course = CourseInput.create('Teste', 'Informação de referência suficientemente extensa para esta unidade.',
                                ects_credits=6, contact_hours=40, autonomous_hours=80,
                                hours_per_ects=25)
    assert course.duration_hours == 150
    assert course.autonomous_hours == 110
    assert course.to_dict()['hours_per_ects'] == 25
