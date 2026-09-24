import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.ai_engine.analysis import Evidence, TextAnalysis
from app.ai_engine.flares import FlareCandidates, validate_candidates, candidate_fingerprint
from app.ai_engine.flare_config import FlareSettings
from app.ai_engine.groq_flare_adapter import GroqFlareDetector
from app.ai_engine.errors import AnalysisError
from app.config import AISettings
from app.ai_engine.flare_prompts import PROMPT_VERSION, SCHEMA_VERSION, SYSTEM_PROMPT, build_flare_request
from test_groq_adapter import completion

S1, S2 = str(uuid4()), str(uuid4())
SOURCES = [Evidence(source_id=S1, content='Our goal is to ship the MVP in two weeks.'),
           Evidence(source_id=S2, content='The core analysis flow is unfinished; Telegram was explicitly deferred.')]
EMPTY = TextAnalysis(observations=[])


def candidate():
    return {'type':'Recommendation', 'title':'Complete the core loop',
            'statement':'Telegram work would expand scope before the core flow is ready.',
            'action':'Finish Analyze and evidence display before starting Telegram.',
            'reason':'The release deadline leaves two weeks for an unfinished core flow.',
            'evidence':[{'source_id':S1,'quote':SOURCES[0].content,'supports':['goal']},
                        {'source_id':S2,'quote':SOURCES[1].content,'supports':['state','constraint']}]}


def validated(c, sources=SOURCES, analysis=EMPTY):
    return validate_candidates(FlareCandidates(flares=c), analysis, sources)


def test_empty_and_specific_recommendation():
    assert validated([]).flares == []
    assert len(validated([candidate()]).flares) == 1


@pytest.mark.parametrize('kind', ['fact','problem','intention','generic','no_goal','fake_goal'])
def test_weak_candidates_drop(kind):
    c=candidate()
    if kind in ('fact','problem','intention'):
        c['type'] = 'Reminder' if kind == 'intention' else 'Warning'
        c['action'] = None
        c['evidence'] = [{'source_id':S2,'quote':SOURCES[1].content,'supports':['state']}]
    elif kind == 'generic': c['action']='Improve communication.'
    elif kind == 'no_goal': c['evidence'][0]['supports']=['state']
    else: c['evidence']=[{'source_id':S2,'quote':SOURCES[1].content,'supports':['goal','state']}]
    assert validated([c]).flares == []


@pytest.mark.parametrize('text,kind,roles', [
    ('We committed to review the contract before signing tomorrow.','Reminder',['commitment','relevance']),
    ('We agreed to avoid integrations, but today started Telegram.','Warning',['conflict','constraint','state']),
    ('The build is still blocked by the same credentials issue again.','Warning',['conflict','state']),
])
def test_one_strong_source_can_suffice(text,kind,roles):
    c=candidate(); c.update(type=kind,action=None,evidence=[{'source_id':S1,'quote':text,'supports':roles}])
    assert len(validated([c],[Evidence(source_id=S1,content=text)]).flares)==1


def test_explicit_decision_can_be_a_durable_reminder_without_today_filler():
    text = 'We decided to use PostgreSQL for the MVP database.'
    c = candidate()
    c.update(type='Reminder', action=None, evidence=[
        {'source_id': S1, 'quote': text, 'supports': ['commitment']},
    ])
    assert len(validated([c], [Evidence(source_id=S1, content=text)]).flares) == 1


@pytest.mark.parametrize('field,value', [
    ('title','x'*81),('title','a '*12+'b'),('statement','x'*181),
    ('action','x'*161),('reason','x'*241),('statement','a '*30+'b'),
    ('action','a '*24+'b'),('reason','a '*40+'b'),('title','Line\nbreak'),
    ('statement','One sentence. Another sentence.'),('statement','One sentence. Another sentence'),
    ('statement','First\u2028second'),('title','Great!'),
    ('title','🔥 Focus'),('reason','It is important to note the deadline.'),
    ('title','**Bold**'),('action',None),
])
def test_prose_limits(field,value):
    c=candidate(); c[field]=value
    with pytest.raises(ValidationError): FlareCandidates(flares=[c])


def test_quote_ref_and_count_limits():
    c=candidate(); c['evidence'][0]['quote']='x'*241
    with pytest.raises(ValidationError): FlareCandidates(flares=[c])
    c=candidate(); c['evidence']*=3
    with pytest.raises(ValidationError): FlareCandidates(flares=[c])
    with pytest.raises(ValidationError): FlareCandidates(flares=[candidate()]*4)
    c=candidate(); c['reason']=c['statement']
    with pytest.raises(ValidationError): FlareCandidates(flares=[c])


@pytest.mark.parametrize('mutation', ['source','quote'])
def test_fabrications_fail(mutation):
    c=candidate()
    c['evidence'][0]['source_id' if mutation=='source' else 'quote']='invented'
    with pytest.raises(ValueError): validated([c])


def test_quote_normalization_and_fingerprint():
    c=candidate(); c['evidence'][0]['quote']='Our goal\u00a0is to ship the MVP in two weeks.'
    v=validated([c]).flares[0]; w=uuid4()
    first=candidate_fingerprint(w,'v1',v)
    assert first==candidate_fingerprint(w,'v1',replace_evidence(v))
    for changes in ({'action':'Complete the core implementation before Telegram.'}, {'reason':'A finished core flow is required by the stated deadline.'}):
        assert first!=candidate_fingerprint(w,'v1',v.model_copy(update=changes))
    assert first!=candidate_fingerprint(w,'v2',v)


def replace_evidence(v):
    return v.model_copy(update={'evidence':list(reversed(v.evidence))})


def test_sdk_contract_and_safe_result():
    calls=[]
    def handler(request):
        calls.append(request)
        body=json.loads(request.content)
        assert body['max_completion_tokens']==1024
        assert body['model']=='openai/gpt-oss-20b' and body['reasoning_effort']=='low'
        assert body['include_reasoning'] is False and body['stream'] is False
        assert body['response_format']['json_schema']['strict'] is True
        assert body['messages'][0] == {'role': 'system', 'content': SYSTEM_PROMPT}
        response = completion(json.dumps({'flares':[candidate()]}))
        response['choices'][0]['message']['reasoning'] = 'hidden provider reasoning sentinel'
        return httpx.Response(200,json=response)
    async def run():
        async with GroqFlareDetector(AISettings(api_key='fake'),transport=httpx.MockTransport(handler)) as detector:
            return await detector.detect(EMPTY,SOURCES)
    result=asyncio.run(run())
    assert len(calls)==1 and len(result.candidates.flares)==1 and result.metadata.validation_outcome=='valid'
    assert 'hidden provider reasoning sentinel' not in repr(result)


def test_support_prompt_contract_and_unchanged_schema():
    request = build_flare_request(EMPTY, SOURCES)
    prompt = ' '.join(request['messages'][0]['content'].split())
    schema = request['response_format']['json_schema']
    assert schema['strict'] is True
    roles = schema['schema']['$defs']['FlareEvidence']['properties']['supports']['items']['enum']
    assert roles == ['goal', 'state', 'constraint', 'commitment', 'relevance', 'conflict']
    assert 'ONLY these six exact strings: ' + ', '.join(f'"{role}"' for role in roles) + '.' in prompt
    assert 'fact/decision/intention/problem/entity are a separate taxonomy and are forbidden in supports' in prompt
    assert 'semantic role of the quoted evidence for the Flare, not the observation category' in prompt
    assert 'A decision quote may support "commitment" and/or "constraint" only when semantically justified' in prompt
    assert 'return one Reminder backed by that exact quote' in prompt
    assert 'A current state/problem/plan quote involved in a contradiction may support both "state" and "conflict" only when semantically justified' in prompt
    assert 'Never output "decision", "problem", "fact", "intention", or "entity" inside supports' in prompt


@pytest.mark.parametrize('category', ['fact', 'decision', 'intention', 'problem', 'entity'])
def test_observation_categories_still_rejected_as_supports(category):
    c = candidate()
    c['evidence'][0]['supports'] = [category, 'constraint']
    with pytest.raises(ValidationError):
        FlareCandidates(flares=[c])


def test_prompt_revision_changes_generation_identity(monkeypatch):
    import app.ai_engine.flare_config as config
    assert PROMPT_VERSION == 'flare-v4'
    assert SCHEMA_VERSION == 'flare-v1'
    settings, ai = FlareSettings(), AISettings()
    current = settings.revision(ai)
    assert current == settings.revision(ai)
    monkeypatch.setattr(config, 'PROMPT_VERSION', 'flare-v2')
    assert current != settings.revision(ai)


@pytest.mark.parametrize('finish', ['length','tool_calls','content_filter'])
def test_incomplete_output_invalid(finish):
    def handler(_):
        response=completion('{"flares":[]}'); response['choices'][0]['finish_reason']=finish
        return httpx.Response(200,json=response)
    async def run():
        async with GroqFlareDetector(AISettings(api_key='fake'),transport=httpx.MockTransport(handler)) as detector:
            await detector.detect(EMPTY,SOURCES)
    with pytest.raises(AnalysisError,match='invalid_output'): asyncio.run(run())


def test_provider_error_has_no_sdk_retry():
    calls=[]
    def handler(request):
        calls.append(request); return httpx.Response(429,json={'error':{'message':'private raw body'}},headers={'retry-after':'9'})
    async def run():
        async with GroqFlareDetector(AISettings(api_key='fake'),transport=httpx.MockTransport(handler)) as detector:
            await detector.detect(EMPTY,SOURCES)
    with pytest.raises(AnalysisError) as e: asyncio.run(run())
    assert len(calls)==1 and e.value.retry_after_seconds==9 and 'private' not in str(e.value)


def test_ambiguous_goal_and_untrusted_commitment_label_drop():
    c = candidate()
    text = 'Maybe our goal is to launch the MVP next week.'
    c['evidence'][0]['quote'] = text
    assert validated([c], [Evidence(source_id=S1, content=text), SOURCES[1]]).flares == []
    text = 'I intend to review the contract tomorrow.'
    c.update(type='Reminder', action=None, evidence=[
        {'source_id':S1, 'quote':text, 'supports':['commitment','relevance']}])
    assert validated([c], [Evidence(source_id=S1, content=text)]).flares == []


def test_extra_reasoning_forbidden_and_bad_config_normalized():
    with pytest.raises(ValidationError):
        FlareCandidates.model_validate({'flares':[], 'reasoning':'private thoughts'})
    with pytest.raises(AnalysisError, match='configuration'):
        GroqFlareDetector(AISettings(api_key='fake'), FlareSettings(max_completion_tokens=0))


@pytest.mark.parametrize('text', [
    'On 2020-01-01 we committed to send the report before 2020-01-02.',
    'We agreed last year to send the report before the deadline.',
    'We committed to review the contract.',
])
def test_historical_commitment_is_not_present_relevance(text):
    c = candidate()
    c.update(type='Reminder', action=None, evidence=[
        {'source_id': S1, 'quote': text, 'supports': ['commitment', 'relevance']}])
    assert validated([c], [Evidence(source_id=S1, content=text)]).flares == []


@pytest.mark.parametrize('one_chunk', [False, True])
def test_reminder_explicit_current_trigger(one_chunk):
    commitment = 'Revisit CSV export after we reach 10 beta signups.'
    trigger = 'Ten people have now signed up.'
    texts = [commitment + ' ' + trigger] if one_chunk else [commitment, trigger]
    roles = [['commitment', 'relevance']] if one_chunk else [['commitment'], ['relevance']]
    sources = [Evidence(source_id=s, content=t) for s, t in zip((S1, S2), texts)]
    c = candidate()
    c.update(type='Reminder', action=None, evidence=[
        {'source_id': e.source_id, 'quote': e.content, 'supports': role}
        for e, role in zip(sources, roles)])
    assert len(validated([c], sources).flares) == 1


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('extra', [None, 'The team uses PostgreSQL.', 'Today the team repeated the PostgreSQL tutorial.'])
def test_unrelated_evidence_cannot_rescue_warning(reverse, extra):
    sources = [Evidence(source_id=S1, content='The office coffee machine is broken.')]
    refs = [{'source_id': S1, 'quote': sources[0].content, 'supports': ['conflict', 'state']}]
    if extra:
        sources.append(Evidence(source_id=S2, content=extra))
        refs.append({'source_id': S2, 'quote': extra, 'supports': ['state']})
    c = candidate()
    c.update(type='Warning', action=None, evidence=list(reversed(refs)) if reverse else refs)
    assert validated([c], sources).flares == []


@pytest.mark.parametrize('goal', [
    'We have no goal to launch the MVP.', 'Launching the MVP is not a goal.',
    'Launching the MVP is no longer a goal.', 'We canceled the MVP launch.',
    'We cancelled the MVP launch.', 'We abandoned the MVP launch.',
    'We dropped the MVP launch.', 'We deprioritized the MVP launch.',
    'We deprioritised the MVP launch.',
])
def test_negative_goal_abstains(goal):
    c = candidate()
    c['evidence'][0]['quote'] = goal
    assert validated([c], [Evidence(source_id=S1, content=goal), SOURCES[1]]).flares == []


@pytest.mark.parametrize('state,action', [
    ('The office coffee machine is broken.', 'Hold a meeting about office furniture.'),
    ('The office coffee machine is broken.', 'Repair the office coffee machine.'),
    (SOURCES[1].content, 'Hold a meeting about office furniture.'),
])
def test_recommendation_requires_linked_state_and_action(state, action):
    c = candidate()  # Keep the same plausible title; it cannot supply linkage.
    c['action'] = action
    c['evidence'][1]['quote'] = state
    assert validated([c], [SOURCES[0], Evidence(source_id=S2, content=state)]).flares == []


def test_mvp_analyze_flare_trajectory_is_linked():
    c = candidate()
    texts = ['Our goal is to launch the MVP.', 'The core Analyze to Flare flow is unfinished.']
    sources = [Evidence(source_id=s, content=t) for s, t in zip((S1, S2), texts)]
    for ref, source in zip(c['evidence'], sources):
        ref['quote'] = source.content
    c['action'] = 'Finish Analyze to Flare to Evidence before Telegram.'
    assert len(validated([c], sources).flares) == 1


@pytest.mark.parametrize('field,text', [
    ('title', '_Italic heading_'), ('title', '__Bold heading__'),
    ('title', '**Bold**'), ('title', '*Italic*'), ('title', '# Heading'),
    ('title', '- List entry'), ('title', '1. List entry'),
    ('statement', 'First sentence。 Second sentence。'),
    ('statement', 'First sentence.Second sentence.'),
    ('statement', 'First sentence？Second sentence。'),
    ('statement', 'First sentence！'),
    ('reason', 'I am an AI assistant.'), ('reason', 'I’m an AI assistant.'),
    ('reason', "I'm an AI assistant."), ('reason', 'As an AI, I recommend testing.'),
    ('reason', 'As a model, I recommend testing.'),
    ('reason', 'I am an assistant.'), ('reason', 'This model recommends testing.'),
    ('title', '1\u20e3 Release priority'),
])
def test_audit_prose_bypasses_rejected(field, text):
    c = candidate()
    c[field] = text
    with pytest.raises(ValidationError):
        FlareCandidates(flares=[c])


@pytest.mark.parametrize('text', [
    'Проверьте экспорт перед запуском.', 'Café déjà prêt.', 'Cafe\u0301 ready.',
    '版本已经准备好。', 'Check version v1.2.3 before release.',
    'The measured value is 3.14.', 'Ask Dr. Smith to review the export.',
    'Check the export, e.g. its CSV headers.',
])
def test_plain_unicode_decimals_and_abbreviations_remain_valid(text):
    c = candidate()
    c['statement'] = text
    FlareCandidates(flares=[c])


def test_generic_team_anchor_cannot_link_unrelated_trajectory():
    c = candidate()
    texts = ['Our team goal is to launch the MVP.', 'The team coffee machine is broken.']
    sources = [Evidence(source_id=s, content=t) for s, t in zip((S1, S2), texts)]
    for ref, source in zip(c['evidence'], sources):
        ref['quote'] = source.content
    c['action'] = 'Repair the team coffee machine.'
    assert validated([c], sources).flares == []


def test_support_arrays_and_final_allowlist_check():
    prompt = ' '.join(SYSTEM_PROMPT.split())
    assert '\"supports\": [\"commitment\", \"constraint\"]' in prompt
    assert '\"supports\": [\"state\", \"conflict\"]' in prompt
    assert 'not category conversions' in prompt
    assert 'check every evidence.supports member against this exact allowlist' in prompt
    assert 'Never copy analysis.observations[].category into supports' in prompt
    assert 'Do not output combined labels or any other string' in prompt
    assert 'omit any candidate left without sufficient evidence; zero Flares is valid' in prompt
