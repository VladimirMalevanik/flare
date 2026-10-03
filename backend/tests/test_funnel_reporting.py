from datetime import datetime,timedelta,timezone
from uuid import uuid4
import os
import psycopg
import pytest
from app.services.funnel_service import aggregate_csv
from test_acquisition import growth,configure,touch


def test_reporting_denied_to_runtime_worker_and_small_cohorts(growth):
    db,e,_,account=growth;user,_=account()
    now=datetime.now(timezone.utc);args=(now-timedelta(days=1),now,'account','first')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.connection() as c:c.execute('SELECT public.growth_report(%s,%s,%s,%s)',args)
    with psycopg.connect(os.environ['WORKER_DATABASE_URL']) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):c.execute('SELECT * FROM public.signup_attribution')
    with psycopg.connect(e.admin_url) as c:
        # A narrow synthetic cohort window excludes unrelated test accounts.
        since=c.execute('SELECT created_at FROM public.signup_attribution WHERE user_id=%s',(user.user_id,)).fetchone()[0]
        report=c.execute('SELECT public.growth_report(%s,clock_timestamp(),%s,%s)',(since,'workspace_creator','last')).fetchone()[0]
        assert report['metrics']=={'suppressed':True}
        with pytest.raises(psycopg.errors.RaiseException):c.execute('SELECT public.growth_report(%s,%s,%s,%s)',(now-timedelta(days=31),now,'account','first'))


def test_ordered_actor_milestones_later_day_and_basis(growth):
    db,e,_,account=growth
    users=[account(touch(db,source='alpha'))[0],account(touch(db,source='beta'))[0]]
    now=datetime.now(timezone.utc)
    with psycopg.connect(e.admin_url) as c:
        for u in users:
            c.execute("UPDATE public.signup_attribution SET created_at=%s WHERE user_id=%s",(now-timedelta(days=3),u.user_id))
            for kind,day,mode in [('capture',2,'manual'),('analyze',2,'manual'),('inspection',2,'manual'),('inspection',1,'manual')]:
                c.execute('SELECT public.growth_fact(%s,%s,%s,%s,%s,%s,1,1)',(u.workspace_id,u.user_id,kind,uuid4(),now-timedelta(days=day),mode))
        report=c.execute('SELECT public.growth_report(%s,%s,%s,%s)',(now-timedelta(days=4),now,'account','first')).fetchone()[0]
        assert report['metrics']['manual_analyze']>=2 and report['metrics']['later_day_activity']>=2
        assert report['unit']=='account' and report['basis']=='first'
        raw=str(report);assert all(u.user_id not in raw and str(u.workspace_id) not in raw for u in users)


def test_formula_safe_export_only_aggregate_columns():
    report={'revision':'=danger','unit':'@formula','basis':'+evil','calendar':'-evil','metrics':{'accounts':2,'email':'secret','unknown':True}}
    csv=aggregate_csv(report)
    assert "'=danger" in csv and "'@formula" in csv and 'secret' not in csv and 'unknown' not in csv
