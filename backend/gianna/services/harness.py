"""Server-owned decision harness: model interpretation, safety gates and RAG authority.

The model reads each turn and proposes an act, a kind of request, searches and memory. It cannot call
the vector store, publish knowledge, choose source IDs or change the server's safety decisions.
"""
from dataclasses import dataclass, field, replace
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .agents import Agents,AgentFailure,InvestorMemory,TurnPlan
from ..errors import DomainError
from .conversation import QUICK_SOCIAL, fold
from .catalog import (DOMAIN_WORDS,EXPLORE_WORDS,FOLLOWUP_WORDS,REQUIREMENT_WORDS,VALID_OPPORTUNITY,
                      ZONE_BY_ID,correct_typos,is_domain_query,resolve_opportunities,resolve_zones)
from .planning import activity_plan,FACETS,requests_next_step
from .information import requests_information


Action = Literal['rag', 'chat', 'deescalate', 'allegation', 'refuse', 'out_of_scope', 'clarify']
# The model's kind of request selects the task guidance; it never selects which documents are allowed.
KIND_INTENT = {'places':'locations','opportunities':'explore','requirements':'requirements','facts':'fact',
               'compare':'recommend','next_steps':'develop','followup':'develop'}


class ProposedDecision(BaseModel):
    model_config = ConfigDict(extra='ignore')
    action: Action
    reply: str = Field(default='', max_length=700)
    standalone_query: str = Field(default='', max_length=1200)
    searches: list[str] = Field(default_factory=list, max_length=3)
    zones: list[str] = Field(default_factory=list, max_length=7)
    opportunity_ids: list[str] = Field(default_factory=list, max_length=16)
    intent: Literal['explore','recommend','develop','locations','requirements','fact','conversation'] | None = None


def parse_proposed(raw: str) -> ProposedDecision:
    candidate=raw.strip()
    if candidate.startswith('```'):
        candidate=re.sub(r'^```(?:json)?\s*|\s*```$', '', candidate, flags=re.I).strip()
    try:
        return ProposedDecision.model_validate_json(candidate)
    except ValueError:
        # Some Cloud models wrap the one small JSON object in prose. Only the
        # typed action is accepted; surrounding text and reply are discarded.
        match=re.search(r'\{[^{}]{1,1000}\}', candidate, re.S)
        if not match:
            raise
        return ProposedDecision.model_validate_json(match.group())


@dataclass(frozen=True)
class RetrievalPlan:
    intent: Literal['explore','recommend','develop','locations','requirements','fact']
    standalone_query: str
    searches: tuple[str, ...]
    zones: tuple[str, ...] = ()
    opportunity_ids: tuple[str, ...] = ()
    inherited_context: bool = False
    activity: str = ''
    facets: tuple[str, ...] = ()
    clarification: str = ''
    project_brief: str = ''
    focus_opportunities: tuple[str, ...] = ()
    offered_options: tuple[dict, ...] = ()
    next_step: bool = False
    question: str = ''
    need: str = ''
    memory: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    action: Action
    reply: str = ''
    usage: dict = field(default_factory=dict)
    plan: RetrievalPlan | None = None
    turn: TurnPlan | None = None


MESSAGES = {
    'allegation': ('No puedo verificar ni divulgar afirmaciones sobre la vida privada o la conducta de una persona identificable. Si te preocupa un posible delito, recurrí a los canales oficiales o a las autoridades competentes; evitá compartir datos personales aquí. Puedo ayudarte con consultas sobre inversiones en Lavalleja.'),
    'refuse': ('Esa actividad es ilegal y constituye un delito grave. No asisto, asesoro ni brindo orientación bajo ningún concepto sobre explotación de menores, narcotráfico, tráfico de armas, trata de personas, lavado de activos ni ninguna otra actividad ilícita. Este canal está destinado exclusivamente a proyectos de inversión legítimos en Lavalleja.'),
    'clarify': ('No pude interpretar tu consulta con suficiente seguridad. ¿Podés reformularla o contarme qué necesitás saber? Si es sobre un proyecto en Lavalleja, buscaré la información en mi base de conocimiento y te mostraré las fuentes.'),
}

DIRECT_ALLEGATION = re.compile(r'\b(?:funcionari[ao]s?|emplead[ao]s?|intendente|intendenta|alcalde|alcaldesa|director[ao]?|edil(?:es)?|persona|vecin[ao]s?|senor[ao]s?|mujer|hombre)\s+(?:(?:que|de|la|el|un|una)\s+){0,2}(?:(?:es|era|esta|fue)\s+(?:(?:un|una)\s+)?(?:prostitut\w*|corrup\w*|acusad\w*|violador\w*|delincu\w*|narcotrafic\w*)|(?:rob\w*|estaf\w*|abus\w*))\b')
INSULT = re.compile(
    r'\b(?:estupid\w*|idiota\w*|imbecil\w*|inutil\w*|basura|mierda|pelotud\w*|bolud\w*|tarad\w*|mogolic\w*|'
    r'put[oa]s?|hdp|hijo de puta|hija de puta|la concha|forr[oa]s?|gil\w*|cornud\w*|pajer\w*|chupala|andate a cagar|no serv\w*)\b'
)
ILLICIT = re.compile(r'\b(?:evadir|falsificar|sobornar|coimear|hackear|robar|estafar|amenazar|agredir|matar|asesinar|secuestrar|extorsionar|acosar|atacar|golpear|lastimar)\b')
SEXUAL_EXPLOIT = re.compile(r'\b(?:explotar|traficar|coaccionar|trata)\b.{0,35}\b(?:sexual\w*|persona\w*|mujer\w*|menor\w*|nin\w*|infantil\w*|adolescent\w*)\b')
MINOR_EXPLOIT = re.compile(
    r'(?:\b(?:prostitu\w*|prostibul\w*|burdel\w*|escort\w*|acompanant\w*|trabaj\w* sexual\w*|'
    r'servicio\w* sexual\w*|explotac\w* sexual\w*|sexo|sexual\w*|pornograf\w*|erotic\w*|chicas?|chicos?|pibas?|pibes?|jovenes)\b.{0,80}'
    r'\b(?:infantil\w*|menor\w*|nin[oa]s?|adolescent\w*|liceal\w*|escolar\w*|chiquilin\w*|gurises|guris\w*|'
    r'menos de 1[0-8]|(?:1[0-7]|[1-9])\s*anos)\b)|'
    r'(?:\b(?:infantil\w*|menor\w*|nin[oa]s?|adolescent\w*|menos de 1[0-8]|(?:1[0-7]|[1-9])\s*anos)\b.{0,80}'
    r'\b(?:prostitu\w*|prostibul\w*|burdel\w*|escort\w*|trabaj\w* sexual\w*|servicio\w* sexual\w*|explotac\w* sexual\w*|pornograf\w*|negocio\w*|emprendimient\w*)\b)|'
    r'\b(?:pedofil\w*|pederast\w*|abuso infantil|trabajo infantil)\b'
)
SEVERE_ILLICIT_TRADE = re.compile(
    r'\b(?:narcotrafic\w*|narco\w*|trafic\w* de (?:drogas?|armas?|personas?|organos?|menores|estupefacientes)|'
    r'trata de (?:personas?|blancas|mujeres|menores)|lavado de (?:activos|dinero)|blanqueo de capitales|testaferr\w*|'
    r'contraband\w*|sicari\w*|clandestin\w* de (?:drogas?|armas?|juegos?|apuestas?))\b|'
    r'\b(?:vender|venta|comercializar|producir|fabricar|distribuir|traficar|invertir|negocio|emprendimiento|instalar|poner|abrir|montar)\b'
    r'.{0,60}\b(?:cocaina|pasta base|marihuana ilegal|heroina|metanfetamina\w*|fentanilo|extasis|lsd|drogas?(?:\s+ilegales?|s?\s+ilicitas?)?|'
    r'estupefacientes|narco\w*|armas?(?:\s+ilegales?|\s+de\s+fuego\s+sin|\s+clandestin\w*|\s+de\s+guerra)?|municion\w*\s+ilegal\w*|explosivos?)\b|'
    r'\b(?:cocaina|pasta base|heroina|metanfetamina\w*|fentanilo|drogas?\s+ilegales?|armas?\s+ilegales?|armas?\s+clandestin\w*)\b'
)
WANT_ACTION = re.compile(r'\b(?:como|quiero|necesito|ayudame|ensen\w*|explica\w*|pasos|puedo|voy a|estoy por|invertir|poner|abrir|montar|crear|instalar|emprend\w*|negocio|proyecto)\b')


class AgentHarness:
    def __init__(self, ollama):
        self.ollama = ollama
        self.agents = Agents(ollama)

    @staticmethod
    def hard_gate(question: str) -> Action | None:
        text = fold(question)
        # Do not let a model mistake an allegation about an identifiable person
        # for a search query, as happened in the reported human test.
        if DIRECT_ALLEGATION.search(text):
            return 'allegation'
        if not re.search(r'\bdenunci\w*\b', text):
            if MINOR_EXPLOIT.search(text) or SEVERE_ILLICIT_TRADE.search(text):
                return 'refuse'
            if (ILLICIT.search(text) or SEXUAL_EXPLOIT.search(text)) and WANT_ACTION.search(text):
                return 'refuse'
        if INSULT.search(text) and (
            re.search(r'\b(?:sos|eres|vos|tu|gianna|chatbot|bot|asistente|no serv\w*)\b', text)
            or len(text.split()) <= 5
        ):
            return 'deescalate'
        return None

    @staticmethod
    def retrieval_plan(question: str, history: list[dict], proposed: ProposedDecision | None = None,
                       project_state: dict | None = None) -> RetrievalPlan:
        from .project_memory import clean_state,latest_state
        question=correct_typos(question);normalized=fold(question)
        information_request=requests_information(question)
        state=clean_state(project_state) if project_state else latest_state(history)
        current_zones=resolve_zones(question);current_opportunities=resolve_opportunities(question)
        activity,facets,clarification=activity_plan(question)
        explicit_reset=bool(re.search(r'\b(?:otro proyecto|otra idea|cambio de (?:idea|rubro|proyecto)|olvida\w*|empezar de nuevo)\b',normalized))
        sector_topic=bool(re.search(
            r'\b(?:parador\w*|restaur\w*|bar|bares|cafe|cafeteria\w*|panader\w*|cervecer\w*|bodega\w*|vined\w*|'
            r'hotel\w*|hostel\w*|posada\w*|caban\w*|alojamient\w*|camping\w*|glamping\w*|estancia\w*|chacra\w*|'
            r'mader\w*|arroz\w*|grano\w*|poscosecha|acopio\w*|ganad\w*|software|energi\w*|taller\w*|planta\w*)\b',normalized))
        new_activity=bool(activity and state.get('activity') and activity!=state['activity']
                          and (sector_topic or explicit_reset))
        followup=bool(FOLLOWUP_WORDS.search(normalized) or requests_next_step(question)
            or re.search(r'\b(?:ponerlo|instalarlo|ubicarlo|hacerlo|abrirlo|ese (?:negocio|proyecto)|esa actividad|'
                         r'lugares|localidades|ubicacion|me refiero|en cuanto|pero que|permis\w*|habilit\w*|'
                         r'requisit\w*|antes de alquilar|comprobar|verificar|profundiz\w*|mas detalle\w*|'
                         r'experiencia|presupuesto|eso|esto|primera|segunda|anterior|'
                         r'(?:la|lo|las|los) (?:menciona|indica|ubica|describe))\b',normalized)
            or current_zones or current_opportunities)
        inherited=bool(state and not explicit_reset and not new_activity and (followup or (activity and activity==state.get('activity'))))
        if sector_topic and not activity:inherited=False
        if information_request and current_zones:inherited=False
        if not inherited:state={}
        prior=state.get('brief','')
        if inherited and not prior:
            prior=next((m.get('content','')[:1000] for m in reversed(history)
                        if m.get('role')=='user' and isinstance(m.get('content'),str)
                        and is_domain_query(m['content'])), '')
        if inherited and not activity:
            activity=state.get('activity','')
            facets=facets or activity_plan(activity)[1] or tuple(state.get('facets',[]))
            clarification=state.get('clarification','')
        zones=current_zones or tuple(state.get('zones',[]))
        opportunities=current_opportunities or (() if current_zones else tuple(state.get('opportunity_ids',[])))
        offered=tuple(state.get('offered_options',[]))
        focus=tuple(state.get('focus_opportunities',[]))
        if current_zones:
            focus=tuple(option['id'] for option in offered if set(current_zones)&set(option['zones']))[:2]
        base=(prior+'\nConsulta actual: '+question) if inherited and prior else question
        if information_request and not requests_next_step(question):
            intent='fact';facets=()
        elif re.search(r'\b(?:permis\w*|habilit\w*|requisit\w*|comprobar|verificar|revisar|antes de|tramites)\b',normalized):
            intent='requirements'
        elif requests_next_step(question) or re.search(r'\b(?:profundiz\w*|mas detalle\w*|me interesa|prefiero)\b',normalized):
            intent='develop'
        elif inherited and (focus or offered) and re.search(r'\b(?:no tengo experiencia|tengo experiencia|presupuesto|socio|capital)\b',normalized):
            intent='develop'
        elif inherited and current_zones and len(normalized.split())<=6 and not re.search(r'\b(?:cuanto\w*|habitantes|poblacion|fecha|distancia|quien|cuando|que es)\b',normalized):
            intent='develop'
        elif re.search(r'\b(?:donde|lugares?|localidades?|ubicacion|ubicarlo|en que zona)\b',normalized):
            intent='locations'
        elif re.search(r'\b(?:recomend\w*|recomiend\w*|conviene\w*)\b',normalized):
            intent='locations' if activity else 'recommend'
        elif EXPLORE_WORDS.search(normalized):intent='locations' if activity else 'explore'
        elif REQUIREMENT_WORDS.search(normalized):intent='requirements'
        else:intent='fact'
        # Provider suggestions cannot replace known user scope or current task.
        if proposed and proposed.intent in {'explore','recommend','develop','locations','requirements','fact'} and intent=='fact' and not information_request:
            intent=proposed.intent
        if intent in {'recommend','locations'}:focus=()
        standalone=base
        if activity:standalone+='\nActividad del proyecto: '+activity
        if focus:standalone+='\nOpción que la persona quiere desarrollar: '+', '.join(focus)
        searches=[standalone]
        if proposed:
            # Planner searches come first: they restate the need in the corpus vocabulary.
            searches.extend(search.strip() for search in proposed.searches if search.strip())
            if proposed.standalone_query.strip():searches.append(proposed.standalone_query.strip())
        searches=tuple(dict.fromkeys(search[:1200] for search in searches))[:4]
        brief=prior if inherited and prior else question[:1000]
        if intent=='develop' and current_zones:brief=question[:1000]
        return RetrievalPlan(intent,standalone,searches,zones,opportunities,inherited,activity,facets,clarification,brief,focus,offered,
                             next_step=intent=='develop' and requests_next_step(question),question=question)

    @staticmethod
    def plan_from_turn(question: str, history: list[dict], turn: TurnPlan, project_state: dict | None = None) -> RetrievalPlan:
        """Retrieval plan from the model's reading of the turn.

        The deterministic plan only contributes names the person typed (zones, opportunity IDs);
        intent, activity and searches come from the model, never from keywords.
        """
        base=AgentHarness.retrieval_plan(question,history,project_state=project_state)
        intent=KIND_INTENT[turn.kind]
        standalone=turn.standalone_question or question
        searches=tuple(dict.fromkeys(item[:1200] for item in (standalone,*turn.searches) if item.strip()))[:4]
        return replace(base,intent=intent,standalone_query=standalone,searches=searches,activity=turn.memory.project,
                       facets=(),clarification='',next_step=turn.kind=='next_steps',question=question,
                       project_brief=(turn.need or question)[:1000],need=turn.need,memory=turn.memory.model_dump())

    def decide(self, question: str, history: list[dict], settings, project_state=None) -> Decision:
        hard = self.hard_gate(question)
        if hard:
            return Decision(hard)
        text = fold(question)
        # Unambiguous courtesies need no interpretation call.
        if QUICK_SOCIAL.fullmatch(text):
            return Decision('chat')
        from .project_memory import clean_state,latest_state
        state=clean_state(project_state) if project_state else latest_state(history)
        memory=InvestorMemory.model_validate(state.get('memory') or {}) if state else InvestorMemory()
        try:
            turn,usage=self.agents.interpret(question,history,memory,settings)
        except (AgentFailure,DomainError):
            # An unreadable turn is not evidence that a topic is absent: search with the local plan.
            return Decision('rag',plan=replace(self.retrieval_plan(question,history,project_state=project_state),
                                              memory=memory.model_dump()))
        action={'knowledge':'rag'}.get(turn.act,turn.act)
        if action=='deescalate' and not INSULT.search(text):
            action='chat'
        # A request to assert a tax benefit without evidence is a grounding
        # problem, not by itself an illicit-act request. Explicit fraud/evasion
        # was already caught by the local safety gate above.
        if action=='refuse' and re.search(r'\bexonerac\w*\b',text) and not ILLICIT.search(text):
            action='rag'
        plan=self.plan_from_turn(question,history,turn,project_state) if action=='rag' else None
        return Decision(action,usage=usage,plan=plan,turn=turn)


def combine_usage(first: dict, second: dict) -> dict:
    return {key: sum(value for value in (first.get(key), second.get(key)) if isinstance(value, int))
            for key in ('prompt_tokens', 'output_tokens')}
