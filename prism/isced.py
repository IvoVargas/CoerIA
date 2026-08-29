"""Catálogo oficial português CITE-F/ISCED-F 2013."""

from __future__ import annotations

import re


# Versão portuguesa adotada pela 51.ª Deliberação do CSE. A lista inclui os
# três níveis oficiais: área geral (2 dígitos), específica (3) e detalhada (4).
_ISCED_F_DATA = """
00|Programas e qualificações genéricos
000|Programas e qualificações genéricos sem definição precisa
0000|Programas e qualificações genéricos sem definição precisa
001|Programas e qualificações de base
0011|Programas e qualificações de base
002|Literacia e numeracia
0021|Literacia e numeracia
003|Competências pessoais e desenvolvimento pessoal
0031|Competências pessoais e desenvolvimento pessoal
009|Programas e qualificações genéricos não classificados noutras áreas
0099|Programas e qualificações genéricos não classificados noutras áreas
01|Educação
011|Educação
0110|Programas de Educação sem definição precisa
0111|Ciências da educação
0112|Formação de educadores de infância
0113|Formação de professores de áreas disciplinares não específicas
0114|Formação de professores de áreas disciplinares específicas
0119|Programas de Educação não classificados noutras áreas
018|Programas e qualificações interdisciplinares que envolvem a Educação
0188|Programas e qualificações interdisciplinares que envolvem a Educação
02|Artes e humanidades
020|Artes e humanidades sem definição precisa
0200|Artes e humanidades sem definição precisa
021|Artes
0210|Artes sem definição precisa
0211|Técnicas audiovisuais e produção dos media
0212|Design de moda, de interiores e industrial
0213|Belas-artes
0214|Artesanato
0215|Música e artes do espetáculo
0219|Programas de Artes não classificados noutras áreas
022|Humanidades (exceto línguas)
0220|Humanidades (exceto línguas) sem definição precisa
0221|Religião e teologia
0222|História e arqueologia
0223|Filosofia e ética
0229|Programas de Humanidades (exceto línguas) não classificados noutras áreas
023|Línguas
0230|Línguas sem definição precisa
0231|Aprendizagem de línguas
0232|Literatura e linguística
0239|Programas de Línguas não classificados noutras áreas
028|Programas e qualificações interdisciplinares que envolvem as Artes e humanidades
0288|Programas e qualificações interdisciplinares que envolvem as Artes e humanidades
029|Programas de Artes e humanidades não classificados noutras áreas
0299|Programas de Artes e humanidades não classificados noutras áreas
03|Ciências sociais, jornalismo e informação
030|Ciências sociais, jornalismo e informação sem definição precisa
0300|Ciências sociais, jornalismo e informação sem definição precisa
031|Ciências sociais e comportamentais
0310|Ciências sociais e comportamentais sem definição precisa
0311|Economia
0312|Ciências políticas e cidadania
0313|Psicologia
0314|Sociologia e estudos culturais
0319|Programas de Ciências sociais e comportamentais não classificados noutras áreas
032|Jornalismo e informação
0320|Jornalismo e informação sem definição precisa
0321|Jornalismo e reportagem
0322|Biblioteconomia, arquivística e ciências da informação
0329|Programas de Jornalismo e informação não classificados noutras áreas
038|Programas e qualificações interdisciplinares que envolvem as Ciências sociais, jornalismo e informação
0388|Programas e qualificações interdisciplinares que envolvem as Ciências sociais, jornalismo e informação
039|Programas de Ciências sociais, jornalismo e informação não classificados noutras áreas
0399|Programas de Ciências sociais, jornalismo e informação não classificados noutras áreas
04|Ciências empresariais, administração e direito
040|Ciências empresariais, administração e direito sem definição precisa
0400|Ciências empresariais, administração e direito sem definição precisa
041|Ciências empresariais e administração
0410|Ciências empresariais e administração sem definição precisa
0411|Contabilidade e fiscalidade
0412|Finanças, banca e seguros
0413|Gestão e administração
0414|Marketing e publicidade
0415|Secretariado e trabalho administrativo
0416|Comércio (por grosso e a retalho)
0417|Competências laborais
0419|Programas de Ciências empresariais e administração não classificados noutras áreas
042|Direito
0421|Direito
048|Programas e qualificações interdisciplinares que envolvem as Ciências empresariais, administração e direito
0488|Programas e qualificações interdisciplinares que envolvem as Ciências empresariais, administração e direito
049|Programas de Ciências empresariais, administração e direito não classificados noutras áreas
0499|Programas de Ciências empresariais, administração e direito não classificados noutras áreas
05|Ciências naturais, matemática e estatística
050|Ciências naturais, matemática e estatística sem definição precisa
0500|Ciências naturais, matemática e estatística sem definição precisa
051|Ciências biológicas e ciências afins
0510|Ciências biológicas e ciências afins sem definição precisa
0511|Biologia
0512|Bioquímica
0519|Programas de Ciências biológicas e ciências afins não classificados noutras áreas
052|Ambiente
0520|Ambiente sem definição precisa
0521|Ciências do ambiente
0522|Ambientes naturais e vida selvagem
0529|Programas de Ambiente não classificados noutras áreas
053|Ciências físicas
0530|Ciências físicas sem definição precisa
0531|Química
0532|Ciências da terra
0533|Física
0539|Programas de Ciências físicas não classificados noutras áreas
054|Matemática e estatística
0540|Matemática e estatística sem definição precisa
0541|Matemática
0542|Estatística
058|Programas e qualificações interdisciplinares que envolvem as Ciências naturais, matemática e estatística
0588|Programas e qualificações interdisciplinares que envolvem as Ciências naturais, matemática e estatística
059|Programas de Ciências naturais, matemática e estatística não classificados noutras áreas
0599|Programas de Ciências naturais, matemática e estatística não classificados noutras áreas
06|Tecnologias da informação e comunicação (TICs)
061|Tecnologias da informação e comunicação (TICs)
0610|Tecnologias da informação e comunicação (TICs) sem definição precisa
0611|Informática na ótica do utilizador
0612|Design e administração de bases de dados e de redes informáticas
0613|Desenvolvimento e análise de software e aplicações informáticas
0619|Programas de Tecnologias da informação e comunicação (TICs) não classificados noutras áreas
068|Programas e qualificações interdisciplinares que envolvem as Tecnologias da informação e comunicação (TICs)
0688|Programas e qualificações interdisciplinares que envolvem as Tecnologias da informação e comunicação (TICs)
07|Engenharia, indústrias transformadoras e construção
070|Engenharia, indústrias transformadoras e construção sem definição precisa
0700|Engenharia, indústrias transformadoras e construção sem definição precisa
071|Engenharia e tecnologias afins
0710|Engenharia e tecnologias afins sem definição precisa
0711|Engenharia química e de processos
0712|Tecnologia de proteção do ambiente
0713|Eletricidade e energia
0714|Eletrónica e automação
0715|Metalurgia e metalomecânica
0716|Veículos a motor, navios e aviões
0719|Programas de Engenharia e tecnologias afins não classificados noutras áreas
072|Indústrias transformadoras
0720|Indústrias transformadoras sem definição precisa
0721|Indústrias alimentares
0722|Materiais (vidro, papel, plástico e madeira)
0723|Têxteis (vestuário, calçado e couro)
0724|Indústrias extrativas
0729|Programas de Indústrias transformadoras não classificados noutras áreas
073|Arquitetura e construção
0730|Arquitetura e construção sem definição precisa
0731|Arquitetura e urbanismo
0732|Construção civil e engenharia civil
078|Programas e qualificações interdisciplinares que envolvem a Engenharia, indústrias transformadoras e construção
0788|Programas e qualificações interdisciplinares que envolvem a Engenharia, indústrias transformadoras e construção
079|Programas de Engenharia, indústrias transformadoras e construção não classificados noutras áreas
0799|Programas de Engenharia, indústrias transformadoras e construção não classificados noutras áreas
08|Agricultura, silvicultura, pescas e ciências veterinárias
080|Agricultura, silvicultura, pescas e ciências veterinárias sem definição precisa
0800|Agricultura, silvicultura, pescas e ciências veterinárias sem definição precisa
081|Agricultura
0810|Agricultura sem definição precisa
0811|Produção agrícola e animal
0812|Horticultura
0819|Programas de Agricultura não classificados noutras áreas
082|Silvicultura
0821|Silvicultura
083|Pescas
0831|Pescas
084|Ciências veterinárias
0841|Ciências veterinárias
088|Programas e qualificações interdisciplinares que envolvem a Agricultura, silvicultura, pescas e ciências veterinárias
0888|Programas e qualificações interdisciplinares que envolvem a Agricultura, silvicultura, pescas e ciências veterinárias
089|Programas de Agricultura, silvicultura, pescas e ciências veterinárias não classificados noutras áreas
0899|Programas de Agricultura, silvicultura, pescas e ciências veterinárias não classificados noutras áreas
09|Saúde e proteção social
090|Saúde e proteção social sem definição precisa
0900|Saúde e proteção social sem definição precisa
091|Saúde
0910|Saúde sem definição precisa
0911|Ciências dentárias
0912|Medicina
0913|Enfermagem geral e enfermagem obstétrica
0914|Tecnologias de diagnóstico e terapêutica
0915|Terapia e reabilitação
0916|Ciências farmacêuticas
0917|Medicina tradicional e complementar e terapia
0919|Programas de Saúde não classificados noutras áreas
092|Proteção social
0920|Proteção social sem definição precisa
0921|Assistência a idosos e a adultos deficientes
0922|Serviços de apoio a crianças e jovens
0923|Trabalho social e aconselhamento
0929|Programas de Proteção social não classificados noutras áreas
098|Programas e qualificações interdisciplinares que envolvem a Saúde e proteção social
0988|Programas e qualificações interdisciplinares que envolvem a Saúde e proteção social
099|Programas de Saúde e proteção social não classificados noutras áreas
0999|Programas de Saúde e proteção social não classificados noutras áreas
10|Serviços
100|Serviços sem definição precisa
1000|Serviços sem definição precisa
101|Serviços pessoais
1010|Serviços pessoais sem definição precisa
1011|Serviços domésticos
1012|Serviços de cabeleireiro e estética
1013|Hotelaria, restauração e catering
1014|Desporto
1015|Viagens, turismo e lazer
1019|Programas de Serviços pessoais não classificados noutras áreas
102|Serviços de higiene e de saúde ocupacional
1020|Serviços de higiene e de saúde ocupacional sem definição precisa
1021|Saúde pública
1022|Saúde e segurança no trabalho
1029|Programas de Serviços de higiene e de saúde ocupacional não classificados noutras áreas
103|Serviços de segurança
1030|Serviços de segurança sem definição precisa
1031|Segurança militar e defesa
1032|Proteção de pessoas e bens
1039|Programas de Serviços de segurança não classificados noutras áreas
104|Serviços de transporte
1041|Serviços de transporte
108|Programas e qualificações interdisciplinares que envolvem os Serviços
1088|Programas e qualificações interdisciplinares que envolvem os Serviços
109|Programas de Serviços não classificados noutras áreas
1099|Programas de Serviços não classificados noutras áreas
99|Área desconhecida
999|Área desconhecida
9999|Área desconhecida
"""

ISCED_F_CATALOG = {
    code: name
    for code, name in (
        line.split("|", 1)
        for line in _ISCED_F_DATA.strip().splitlines()
        if line.strip()
    )
}


def isced_f_options() -> dict[str, str]:
    """Opções pesquisáveis com código e designação canónica."""

    return {
        code: f"{code} — {ISCED_F_CATALOG[code]}"
        for code in sorted(ISCED_F_CATALOG)
    }


def canonicalize_isced_f(code: str | None, name: str | None = "") -> tuple[str, str]:
    """Valida o código e deriva sempre a designação oficial do catálogo."""

    normalized_code = str(code or "").strip()
    supplied_name = str(name or "").strip()
    if not normalized_code:
        if supplied_name:
            raise ValueError("Selecione um código ISCED-F para definir a respetiva área.")
        return "", ""
    if not re.fullmatch(r"\d{2,4}", normalized_code):
        raise ValueError("O código ISCED-F deve ter 2, 3 ou 4 dígitos.")
    canonical_name = ISCED_F_CATALOG.get(normalized_code)
    if canonical_name is None:
        raise ValueError("Selecione um código existente no catálogo oficial ISCED-F 2013.")
    return normalized_code, canonical_name
