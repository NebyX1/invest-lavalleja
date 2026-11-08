"""Protocol tests, not evidence of real model answer quality."""
import json

import pytest

from gianna.services.answer_contract import (
    AnswerPlan, Intent, Review, InvalidContract, parse, validate_plan, accepted, render,
)


def intent(kind='description'):
    return Intent(asks=[{'text':'Describir el lugar', 'kind':kind}], query='perfil del lugar')


def plan(**changes):
    statement = {'ask':0, 'paragraph':0, 'kind':'fact', 'text':'Un dato del lugar.',
                 'support':[{'source':1, 'quote':'Un dato literal de la fuente.'}]}
    return AnswerPlan(statements=[statement | changes])


def test_source_binding_requires_a_read_source_and_a_literal_contiguous_quote():
    good = plan()
    assert validate_plan(good, intent(), {1:'Un dato literal de la fuente.'}) is good
    with pytest.raises(InvalidContract, match='Invalid answer') as exc:
        validate_plan(good, intent(), {2:'Un dato literal de la fuente.'})
    assert exc.value.code == 'unread_source'
    with pytest.raises(InvalidContract) as exc:
        validate_plan(good, intent(), {1:'Un dato diferente.'})
    assert exc.value.code == 'quote_not_in_source' and exc.value.location == {'statement':0,'source':1}


def test_whitespace_normalization_does_not_authorize_changed_figures_or_merged_sentences():
    p = plan(support=[{'source':1,'quote':'Capacidad de 42 MW.'}])
    validate_plan(p, intent(), {1:'Capacidad de\n42 MW.'})
    for source in ['Capacidad de 66 MW.', 'Capacidad de generación. Otra frase. 42 MW.']:
        with pytest.raises(InvalidContract): validate_plan(p, intent(), {1:source})


@pytest.mark.parametrize('kind', ['description','possibilities','comparison'])
def test_absence_cannot_replace_a_descriptive_or_comparative_request(kind):
    with pytest.raises(InvalidContract) as exc:
        validate_plan(plan(kind='missing_data', support=[]), intent(kind), {})
    assert exc.value.code == 'unrequested_absence'


def test_requested_missing_datum_and_requested_procedure_are_not_sentence_filtered():
    p = plan(kind='missing_data', support=[], text='El precio solicitado no figura en los datos consultados.')
    validate_plan(p, intent('fact'), {})
    assert render(p) == p.statements[0].text
    p = plan(text='Para este trámite se exige inscripción previa.')
    assert render(p) == 'Para este trámite se exige inscripción previa. [1]'


def test_extra_keys_duplicate_keys_and_incomplete_review_are_rejected():
    raw = '{"asks":[],"asks":[],"query":"un lugar"}'
    with pytest.raises(InvalidContract) as exc:
        parse({'tool_calls':[{'function':{'name':'interpretar_pedido','arguments':raw}}]}, 'interpretar_pedido', Intent)
    assert exc.value.code == 'duplicate_key'
    good = {'checks':[{'statement':0,'function':'information','supported':True,'answers_ask':True,'informative':True,
                       'material_conditions_preserved':True}], 'missing_asks':[]}
    assert accepted(Review.model_validate(good), plan(), intent())
    duplicate = good | {'checks':good['checks'] * 2}
    with pytest.raises(InvalidContract): accepted(Review.model_validate(duplicate), plan(), intent())
    for field in ['supported','answers_ask','informative','material_conditions_preserved']:
        review = json.loads(json.dumps(good)); review['checks'][0][field] = False
        assert not accepted(Review.model_validate(review), plan(), intent())


def test_render_preserves_all_accepted_text_without_adding_stock_advice():
    p = plan(text='Una condición sustantiva: este uso exige inscripción.')
    assert render(p) == p.statements[0].text + ' [1]'
