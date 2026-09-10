"""No retrieval: Stage 2 consumes the completed parent's pinned evidence only."""
import asyncio
from uuid import uuid4

from app.ai_engine.analysis import Evidence, TextAnalysis
from app.ai_engine.errors import AnalysisError
from app.ai_engine.flares import FlareCandidates, validate_candidates
from app.ai_engine.flare_prompts import PROMPT_VERSION, SCHEMA_VERSION
from app.models.flare_runs import FlareRuns
from app.services.analysis_jobs import retry_delay, safe_metadata


class FlareProcessor:
    def __init__(self, runs: FlareRuns, detector, ai, flare, settings):
        settings.validate(ai)
        flare.validate()
        self.runs,self.detector,self.ai,self.flare,self.settings = runs,detector,ai,flare,settings
        self.owner=uuid4()

    async def process_one(self):
        claim=await asyncio.to_thread(self.runs.claim,self.owner,self.settings.lease_seconds)
        if claim is None:
            return None
        error=metadata=result=delay=None
        if claim['generation_revision']!=self.flare.revision(self.ai):
            error='generation_mismatch'
        else:
            loaded=await asyncio.to_thread(self.runs.load,claim,self.ai.max_sources,self.ai.max_input_bytes)
            if 'error' in loaded:
                if loaded['error']=='lease_lost': return 'lease_lost'
                error=loaded['error']
            else:
                try:
                    analysis=TextAnalysis.model_validate(loaded['analysis'])
                    evidence=tuple(Evidence.model_validate(e) for e in loaded['evidence'])
                    # Both claim/load transactions have committed and connections closed.
                    async with asyncio.timeout(self.ai.deadline_seconds):
                        response=await self.detector.detect(analysis,evidence)
                    candidates=FlareCandidates.model_validate(response.candidates.model_dump())
                    candidates=validate_candidates(candidates,analysis,evidence)
                    metadata=safe_metadata(response.metadata)
                    if (not metadata or metadata['validation_outcome']!='valid' or metadata['finish_reason']!='stop'
                        or metadata['configured_model']!=self.ai.model or metadata['returned_model']!=self.ai.model
                        or metadata['prompt_version']!=PROMPT_VERSION or metadata['schema_version']!=SCHEMA_VERSION):
                        raise ValueError('Invalid detector metadata')
                    result=[c.model_dump() for c in candidates.flares]
                except AnalysisError as failure:
                    error=failure.code
                    metadata=safe_metadata(failure.metadata)
                    delay=retry_delay(failure,claim['attempts'],self.settings)
                except TimeoutError:
                    error='timeout'
                    delay=retry_delay(AnalysisError('timeout',retryable=True),claim['attempts'],self.settings)
                except (ValueError,TypeError,KeyError,AttributeError):
                    error,metadata='invalid_output',None
                except Exception:
                    error,metadata='internal_error',None
        return await asyncio.to_thread(self.runs.finish,claim,flares=result,metadata=metadata,
                                       error=error,retry_seconds=delay)


class PipelineProcessor:
    """Alternate stage priority; each process_one still runs at most one attempt."""
    def __init__(self, extraction, generation):
        self.stages=[extraction,generation]
        self.settings=extraction.settings

    async def process_one(self):
        first,second=self.stages
        self.stages.reverse()
        result=await first.process_one()
        return result if result is not None else await second.process_one()
