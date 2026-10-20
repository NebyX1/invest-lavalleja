from gianna.services.evidence_guard import attribution_issues,remove_misattributed_paragraphs,supported_sources


def test_declared_sources_that_share_nothing_with_the_answer_are_dropped():
    selected=[{'citation':'C1','record':{'title':'Villa Serrana turismo serrano',
                'text':'Hospitalidad serrana con gastronomía, alojamiento y experiencias para visitantes en Villa Serrana.'}},
              {'citation':'C2','record':{'title':'Cuidados y envejecimiento','text':'Dato demográfico sobre cuidados, envejecimiento y estudio de mercado local.'}}]
    answer='Villa Serrana ofrece hospitalidad serrana, gastronomía y alojamiento con experiencias para visitantes.'
    assert supported_sources(answer,selected,('C1','C2'))==('C1',)


def test_the_answer_is_never_left_without_a_source():
    selected=[{'citation':'C3','record':{'title':'Tema','text':'Texto ajeno por completo'}}]
    assert supported_sources('Una respuesta sin palabras en común.',selected,('C3',))==('C3',)


def test_stale_citation_cannot_support_property_inventory_or_fire_claim():
    selected=[{'citation':'C7','record':{'text':'Verificar uso del suelo y condiciones de obra por padrón.'}},
              {'citation':'C2','record':{'text':'Incendios y seguridad: consultar a Bomberos y técnicos habilitados.'}}]
    answer='No hay inventario certificado de locales disponibles. [C7]\n\nConsultar Bomberos. [C2]'
    issues=attribution_issues(answer,selected)
    assert len(issues)==1 and issues[0]['missing_concepts']==['property_inventory']
    assert remove_misattributed_paragraphs(answer,issues)=='Consultar Bomberos. [C2]'


def test_valid_citation_to_actual_inventory_record_is_preserved():
    selected=[{'citation':'C1','record':{'text':'La guía no contiene inventario certificado de locales disponibles.'}}]
    assert attribution_issues('La guía no trae inventario certificado. [C1]',selected)==[]


def test_villa_serrana_name_is_not_a_protected_land_claim():
    selected=[{'citation':'C1','record':{'title':'Villa Serrana y Penitente',
        'text':'Hipótesis de hospitalidad, gastronomía y experiencias.'}}]
    assert attribution_issues('En Villa Serrana estudiaría una experiencia gastronómica como hipótesis [C1].',selected)==[]
    issues=attribution_issues('Villa Serrana es un área protegida SNAP [C1].',selected)
    assert issues[0]['missing_concepts']==['protected_land']
