"""Strict Flare candidates over supplied context; never a context selector."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
import unicodedata
from typing import Literal, Protocol, Sequence
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.ai_engine.analysis import (StrictModel, Evidence, EvidenceReference, Observation,
                                    TextAnalysis, AnalysisMetadata, validate_evidence)

Support = Literal['goal', 'state', 'constraint', 'commitment', 'relevance', 'conflict']
FlareType = Literal['Reminder', 'Warning', 'Recommendation']


def normalized(value: str) -> str:
    return ' '.join(value.split())


FILLER = re.compile(r'(?i)(it (?:is important to note|seems)|you may want|great opportunity|as an ai|as a language model|interesting insight|unlock|game.chang|важно отметить|кажется,|как языковая модель)')
GENERIC = re.compile(r'(?i)^(?:improve communication|focus on priorities|consider testing with users|prioritize tasks|communicate better|улучшить коммуникацию|сосредоточиться на приоритетах)[.! ]*$')
NEGATIVE_GOAL = re.compile(r'(?i)\b(no (?:longer (?:a |our |the )?)?goal|not (?:a |our |the )?goal|cancelled|canceled|abandoned|dropped|deprioritized|deprioritised)\b')
# Bounded lexical linkage, not similarity inference. MVP/core and Analyze/analysis
# are the two explicit product vocabulary aliases; no general synonym inference.
ANCHOR_ALIASES = {'mvp': 'core', 'analyze': 'analysis'}
ANCHOR_STOPWORDS = frozenset('''a an the our we us their they it its is are was were be been
    to of for from with and or but before after while this that these those in on at by
    has have had will would should can could must not no goal aim target objective
    now today tomorrow week weeks next current state unfinished blocked finish complete
    launch ship release improve consider prioritize focus hold discuss do make taking
    team project work task tasks problem issue plan'''.split())


def lexical_anchors(value: str) -> set[str]:
    return {ANCHOR_ALIASES.get(word, word) for word in
            re.findall(r'[^\W\d_]+', unicodedata.normalize('NFC', value).casefold())
            if len(word) > 2 and word not in ANCHOR_STOPWORDS}


def prose(value: str, chars: int, words: int, *, sentence: bool) -> str:
    if not value.strip() or value != value.strip() or len(value) > chars or len(value.split()) > words:
        raise ValueError('Flare text exceeds its contract')
    if any(c in value for c in '\n\r\t!?？！#*`[]<>') or FILLER.search(value):
        raise ValueError('Decorative or multiline Flare text')
    if re.search(r'(?<!\w)_{1,2}\S.*?_{1,2}(?!\w)|^(?:[-+]\s|\d+[.)]\s)', value):
        raise ValueError('Markdown Flare text')
    if re.search(r'(?i)\bi(?: am|[\u2019\x27]m) an? (?:ai|assistant|model)\b|\bas an? (?:ai|model)\b|\bthis model (?:recommends|suggests)\b', value):
        raise ValueError('Model self-reference')
    if any(unicodedata.category(c) in ('So', 'Cs', 'Cc', 'Zl', 'Zp') or c in ('\u200d', '\ufe0f', '\u20e3') for c in value):
        raise ValueError('Unsupported Flare text characters')
    if sentence:
        # Preserve decimal/version dots and a bounded set of common abbreviations.
        boundaries = re.sub(r'(?i)\b(?:e\.g\.|i\.e\.|dr\.|mr\.|mrs\.|ms\.|prof\.|vs\.|etc\.)', '', value)
        boundaries = re.sub(r'(?<=\d)\.(?=\d)', '', boundaries)
        if re.search(r'[.。;][\s\"\u201d\u2019)]*\S', boundaries):
            raise ValueError('Use one sentence')
    return value


class FlareEvidence(StrictModel):
    source_id: str
    quote: str = Field(min_length=1, max_length=240)
    supports: list[Support] = Field(min_length=1, max_length=6)

    @model_validator(mode='after')
    def valid_reference(self):
        EvidenceReference(source_id=self.source_id, quote=self.quote)
        if len(set(self.supports)) != len(self.supports):
            raise ValueError('Duplicate support roles')
        return self


class FlareCandidate(StrictModel):
    type: FlareType
    title: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=180)
    action: str | None = Field(max_length=160)
    reason: str = Field(min_length=1, max_length=240)
    evidence: list[FlareEvidence] = Field(min_length=1, max_length=4)

    @field_validator('title', 'statement', 'action', 'reason')
    @classmethod
    def strict_prose(cls, value, info):
        if value is None:
            return value
        limits = {'title': (80,12), 'statement': (180,30), 'action': (160,24), 'reason': (240,40)}
        return prose(value, *limits[info.field_name], sentence=info.field_name != 'title')

    @model_validator(mode='after')
    def structure(self):
        if self.type == 'Recommendation' and self.action is None:
            raise ValueError('Recommendation requires an action')
        if len({e.source_id for e in self.evidence}) != len(self.evidence):
            raise ValueError('Select one quote per chunk')
        fields = [re.sub(r'\W+', ' ', v.casefold()).strip() for v in
                  (self.title,self.statement,self.action,self.reason) if v]
        for i, first in enumerate(fields):
            for second in fields[i+1:]:
                a, b = set(first.split()), set(second.split())
                if first == second or (len(a | b) >= 5 and len(a & b)/len(a | b) > .85):
                    raise ValueError('Repeated prose fields')
        return self


class FlareCandidates(StrictModel):
    flares: list[FlareCandidate] = Field(max_length=3)


def validate_candidates(candidates: FlareCandidates, analysis: TextAnalysis,
                        evidence: Sequence[Evidence]) -> FlareCandidates:
    """Exact citation errors fail the response; insufficient support drops candidates.

    Structural/lexical checks are conservative guards, not proof of model judgment.
    Supports are untrusted labels: an explicit goal cue is required in its quote.
    """
    validate_evidence(analysis, tuple(evidence))
    accepted = []
    for c in candidates.flares:
        references = [EvidenceReference(source_id=e.source_id, quote=e.quote) for e in c.evidence]
        validate_evidence(TextAnalysis(observations=[Observation(category='fact',text=c.statement,
                                                                 evidence=references)]), tuple(evidence))
        roles = {role for e in c.evidence for role in e.supports}
        quotes = ' '.join(e.quote for e in c.evidence)
        if c.type == 'Reminder':
            anchors = ' '.join(e.quote for e in c.evidence if set(e.supports) & {'commitment','constraint'})
            if not re.search(r'(?i)\b(committed|promised|agreed|decided|must|required|обязались|решили|договорились|должны)\b|\brevisit\b.{1,100}\b(after|when)\b', anchors):
                continue
            if not roles & {'commitment','constraint'}:
                continue
            # A concrete decision remains useful durable context and can be surfaced
            # once without an artificial "today" sentence. Other commitments still
            # need evidence that their trigger or deadline is currently relevant.
            decision = re.search(r'(?i)\b(decided|chose|selected|решили|выбрали)\b', anchors)
            if not decision:
                if 'relevance' not in roles:
                    continue
                relevance = ' '.join(e.quote for e in c.evidence if 'relevance' in e.supports)
                if not re.search(r'(?i)\b(now|today|tomorrow|this week|сегодня|завтра|теперь)\b', relevance):
                    continue
        if c.type == 'Warning':
            if not ('conflict' in roles and roles & {'state','constraint','goal'}):
                continue
            conflict = ' '.join(e.quote for e in c.evidence if 'conflict' in e.supports)
            if not re.search(r'(?i)\b(but|however|yet|instead|again|repeated|still|contradict|но|снова|вопреки|повторно|по-прежнему)\b', conflict):
                continue
        if c.type == 'Recommendation':
            if not ('goal' in roles and roles & {'state','constraint'}):
                continue
            goals = ' '.join(e.quote for e in c.evidence if 'goal' in e.supports)
            if NEGATIVE_GOAL.search(goals):
                continue
            if re.search(r'(?i)\b(maybe|might|possibly|perhaps|unclear|either|возможно|неясно)\b', goals):
                continue
            if not re.search(r'(?i)\b(goal|aim|target|objective|ship|launch|release|цель|выпустить|запустить)\b', goals):
                continue
            if GENERIC.match(c.action or '') or len((c.action or '').split()) < 3:
                continue
            states = ' '.join(e.quote for e in c.evidence if set(e.supports) & {'state', 'constraint'})
            goal_anchors = lexical_anchors(goals)
            state_anchors = lexical_anchors(states)
            action_anchors = lexical_anchors(c.action or '')
            if not (action_anchors & state_anchors and goal_anchors & (state_anchors | action_anchors)):
                continue
            action = re.sub(r'\W+', ' ', (c.action or '').casefold()).strip()
            if any(o.category == 'intention' and re.sub(r'\W+', ' ', o.text.casefold()).strip() == action
                   for o in analysis.observations):
                continue
        accepted.append(c)
    return FlareCandidates(flares=accepted)


def candidate_fingerprint(workspace_id: UUID, revision: str, candidate: FlareCandidate) -> str:
    canonical = [str(workspace_id), revision, candidate.type,
                 normalized(candidate.title), normalized(candidate.statement),
                 normalized(candidate.action) if candidate.action is not None else None,
                 normalized(candidate.reason),
                 sorted((str(UUID(e.source_id)),normalized(e.quote)) for e in candidate.evidence)]
    return sha256(json.dumps(canonical,ensure_ascii=False,separators=(', ', ': ')).encode()).hexdigest()


@dataclass(frozen=True)
class FlareResult:
    candidates: FlareCandidates
    metadata: AnalysisMetadata


class FlareDetector(Protocol):
    async def detect(self, analysis: TextAnalysis, evidence: Sequence[Evidence]) -> FlareResult: ...
