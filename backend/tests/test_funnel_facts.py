"""Committed facts, domain rollback, terminal completeness and privacy replay."""
from uuid import uuid4
import psycopg
import pytest
from app.services.item_service import ItemService
from app.services.import_service import ImportService
from app.services.funnel_service import FunnelService
from test_acquisition import growth
from test_analysis_runs import jobs, admin_url, executor_role, start, service
from test_analysis_jobs import FakeAnalyzer
from test_flare_runs import Detector
from app.services.analysis_jobs import AnalysisProcessor
from app.services.flare_generation import FlareProcessor
from app.config import AISettings
from app.workers.config import WorkerSettings
from app.ai_engine.flare_config import FlareSettings
import asyncio


def facts(e,user):
    with psycopg.connect(e.admin_url) as c:return c.execute('SELECT kind,logical_id FROM public.funnel_facts WHERE workspace_id=%s',(user.workspace_id,)).fetchall()


def test_capture_and_sync_commit_not_best_effort(growth):
    db,e,_,account=growth;u,_=account()
    item=ItemService(db,u.identity).create_note(title='synthetic',content='synthetic')
    importer=ImportService(db,u.identity)
    result=importer.create_import(format='txt',file_name='synthetic.txt',file_type='text/plain',file_size=9,content='synthetic')
    importer.create_import(format='txt',file_name='synthetic.txt',file_type='text/plain',file_size=9,content='synthetic')
    assert sorted(k for k,_ in facts(e,u))==['capture','sync_import']
    with pytest.raises(RuntimeError):
        with db.workspace_transaction(u.identity,write=True) as c:
            c.execute('UPDATE public.documents SET current_version_id=NULL WHERE id=%s',(item.id,))
            c.execute('UPDATE public.documents SET current_version_id=%s WHERE id=%s',(item.current_version_id,item.id))
            raise RuntimeError('rollback')
    assert len(facts(e,u))==2
    FunnelService(db,u.identity).withdraw()
    assert facts(e,u)==[]
    ItemService(db,u.identity).create_note(title=None,content='after withdrawal')
    with psycopg.connect(e.admin_url) as c:c.execute('SELECT public.growth_reconcile(100)')
    assert facts(e,u)==[]


def test_both_terminal_manual_mode_preserved_after_cleanup(jobs,admin_url):
    run=start(jobs)
    db=jobs[0].database;identity=jobs[2][0]
    def count():
        with psycopg.connect(admin_url) as c:return c.execute("SELECT logical_id,mode,result_count FROM public.funnel_facts WHERE workspace_id=%s AND kind='analyze'",(identity.workspace_id,)).fetchall()
    assert count()==[]
    asyncio.run(AnalysisProcessor(jobs[1],FakeAnalyzer(),AISettings(),WorkerSettings()).process_one())
    assert count()==[]
    asyncio.run(FlareProcessor(__import__('app.models.flare_runs',fromlist=['FlareRuns']).FlareRuns(jobs[1]._database_url),Detector(),AISettings(),FlareSettings(),WorkerSettings()).process_one())
    assert len(count())==1 and count()[0][1]=='manual'
    before=count()
    with psycopg.connect(admin_url) as c:
        job=c.execute('SELECT analysis_job_id FROM public.analysis_runs WHERE id=%s',(run['id'],)).fetchone()[0]
        c.execute('SELECT public.growth_analyze_fact(%s)',(job,))
        c.execute('DELETE FROM public.analysis_jobs WHERE id=%s',(job,))
    assert count()==before
