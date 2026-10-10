import shutil
from unittest.mock import patch

import pytest

from prism.exporter import _latex_document, _latex_escape, compile_latex_pdf


def test_unicode_text_is_preserved():
    text = "Educação: α β μ σ; методologias; investigação."
    source = _latex_document("Teste", "Unicode", [_latex_escape(text)])
    assert text in source
    assert r"\usepackage{fontspec}" in source
    assert "DejaVu Serif" in source


@pytest.mark.skipif(not shutil.which("xelatex"), reason="XeLaTeX indisponível")
def test_xelatex_compiles_unicode(tmp_path):
    source = tmp_path / "unicode.tex"
    source.write_text(_latex_document("Teste", "Unicode", [
        _latex_escape("Educação: α β μ σ; методologias; investigação.")
    ]), encoding="utf-8")
    with patch.dict("os.environ", {
        "COERIA_LATEX_PDF_ENABLED": "true",
        "COERIA_LATEX_COMPILER": "xelatex",
        "COERIA_LATEX_TIMEOUT_SECONDS": "120",
    }):
        assert compile_latex_pdf(source)
    assert source.with_suffix(".pdf").is_file()
    assert "Missing character" not in source.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
