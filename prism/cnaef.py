"""Catálogo oficial da Classificação Nacional das Áreas de Educação e Formação."""

from __future__ import annotations

import re


# Quadro sinóptico da CNAEF aprovada pela Portaria n.º 256/2005, de 16 de março.
# A classificação nacional usa códigos de três dígitos.
_CNAEF_DATA = """
010|Programas de base
080|Alfabetização
090|Desenvolvimento pessoal
140|Formação de professores/formadores e ciências da educação
142|Ciências da educação
143|Formação de educadores de infância
144|Formação de professores do ensino básico (1.º e 2.º ciclos)
145|Formação de professores de áreas disciplinares específicas
146|Formação de professores e formadores de áreas tecnológicas
149|Formação de professores/formadores e ciências da educação — programas não classificados noutra área de formação
210|Artes
211|Belas-artes
212|Artes do espetáculo
213|Áudio-visuais e produção dos media
214|Design
215|Artesanato
219|Artes — programas não classificados noutra área de formação
220|Humanidades
221|Religião e teologia
222|Línguas e literaturas estrangeiras
223|Língua e literatura materna
225|História e arqueologia
226|Filosofia e ética
229|Humanidades — programas não classificados noutra área de formação
310|Ciências sociais e do comportamento
311|Psicologia
312|Sociologia e outros estudos
313|Ciência política e cidadania
314|Economia
319|Ciências sociais e do comportamento — programas não classificados noutra área de formação
320|Informação e jornalismo
321|Jornalismo e reportagem
322|Biblioteconomia, arquivo e documentação (BAD)
329|Informação e jornalismo — programas não classificados noutra área de formação
340|Ciências empresariais
341|Comércio
342|Marketing e publicidade
343|Finanças, banca e seguros
344|Contabilidade e fiscalidade
345|Gestão e administração
346|Secretariado e trabalho administrativo
347|Enquadramento na organização/empresa
349|Ciências empresariais — programas não classificados noutra área de formação
380|Direito
420|Ciências da vida
421|Biologia e bioquímica
422|Ciências do ambiente
429|Ciências da vida — programas não classificados noutra área de formação
440|Ciências físicas
441|Física
442|Química
443|Ciências da terra
449|Ciências físicas — programas não classificados noutra área de formação
460|Matemática e estatística
461|Matemática
462|Estatística
469|Matemática e estatística — programas não classificados noutra área de formação
480|Informática
481|Ciências informáticas
482|Informática na ótica do utilizador
489|Informática — programas não classificados noutra área de formação
520|Engenharia e técnicas afins
521|Metalurgia e metalomecânica
522|Eletricidade e energia
523|Eletrónica e automação
524|Tecnologia dos processos químicos
525|Construção e reparação de veículos a motor
529|Engenharia e técnicas afins — programas não classificados noutra área de formação
540|Indústrias transformadoras
541|Indústrias alimentares
542|Indústrias do têxtil, vestuário, calçado e couro
543|Materiais (indústrias da madeira, cortiça, papel, plástico, vidro e outros)
544|Indústrias extrativas
549|Indústrias transformadoras — programas não classificados noutra área de formação
580|Arquitetura e construção
581|Arquitetura e urbanismo
582|Construção civil e engenharia civil
589|Arquitetura e construção — programas não classificados noutra área de formação
620|Agricultura, silvicultura e pescas
621|Produção agrícola e animal
622|Floricultura e jardinagem
623|Silvicultura e caça
624|Pescas
629|Agricultura, silvicultura e pescas — programas não classificados noutra área de formação
640|Ciências veterinárias
720|Saúde
721|Medicina
723|Enfermagem
724|Ciências dentárias
725|Tecnologias de diagnóstico e terapêutica
726|Terapia e reabilitação
727|Ciências farmacêuticas
729|Saúde — programas não classificados noutra área de formação
760|Serviços sociais
761|Serviços de apoio a crianças e jovens
762|Trabalho social e orientação
769|Serviços sociais — programas não classificados noutra área de formação
810|Serviços pessoais
811|Hotelaria e restauração
812|Turismo e lazer
813|Desporto
814|Serviços domésticos
815|Cuidados de beleza
819|Serviços pessoais — programas não classificados noutra área de formação
840|Serviços de transporte
850|Proteção do ambiente
851|Tecnologia de proteção do ambiente
852|Ambientes naturais e vida selvagem
853|Serviços de saúde pública
859|Proteção do ambiente — programas não classificados noutra área de formação
860|Serviços de segurança
861|Proteção de pessoas e bens
862|Segurança e higiene no trabalho
863|Segurança militar
869|Serviços de segurança — programas não classificados noutra área de formação
999|Desconhecido ou não especificado
"""


CNAEF_CATALOG = {
    code: name
    for code, name in (
        line.split("|", 1)
        for line in _CNAEF_DATA.strip().splitlines()
        if line.strip()
    )
}


def cnaef_options() -> dict[str, str]:
    """Opções pesquisáveis com código e designação canónica."""

    return {
        code: f"{code} — {CNAEF_CATALOG[code]}"
        for code in sorted(CNAEF_CATALOG)
    }


def canonicalize_cnaef(code: str | None, name: str | None = "") -> tuple[str, str]:
    """Valida o código e deriva sempre a designação oficial do catálogo."""

    normalized_code = str(code or "").strip()
    supplied_name = str(name or "").strip()
    if not normalized_code:
        if supplied_name:
            raise ValueError("Selecione um código CNAEF para definir a respetiva área.")
        return "", ""
    if not re.fullmatch(r"\d{3}", normalized_code):
        raise ValueError("O código CNAEF deve ter exatamente 3 dígitos.")
    canonical_name = CNAEF_CATALOG.get(normalized_code)
    if canonical_name is None:
        raise ValueError("Selecione um código existente no catálogo oficial CNAEF.")
    return normalized_code, canonical_name
