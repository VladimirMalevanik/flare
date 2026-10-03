"""Narrow voluntary activity and aggregate export contracts."""
import csv
import io
from uuid import UUID


class FunnelService:
    def __init__(self, database, identity):
        self.database, self.identity = database, identity

    def inspect(self, interaction_id: UUID, flare_id: UUID, source_id: UUID | None = None) -> None:
        with self.database.workspace_transaction(self.identity) as c:
            c.execute("SET LOCAL statement_timeout='500ms'")
            c.execute('SELECT public.growth_inspection(%s,%s,%s)', (interaction_id,flare_id,source_id))

    def withdraw(self, *, workspace: bool = False) -> None:
        with self.database.workspace_transaction(self.identity) as c:
            c.execute('SELECT public.growth_withdraw(%s)', (workspace,))


def aggregate_csv(report: dict) -> str:
    """Fixed aggregate columns and bounded report-approved attribution buckets."""
    allowed = ('accounts','eligible','unknown','snapshot_present','snapshot_missing','actual_verified','bypassed','verification_unknown',
               'committed_outcome','manual_analyze','voluntary_inspection','later_day_activity','later_day_observable',
               'inspection_later_day_observable')
    stream = io.StringIO()
    writer = csv.writer(stream)
    dimensions = ('coverage','source','medium','campaign','ref','referrer_domain','landing_route')
    writer.writerow(('revision','unit','basis','calendar','row_type',*dimensions,'metric','count'))
    def safe(value):
        text = str(value)
        return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else text
    rows = [('total',{},report.get('metrics',{}))]
    buckets = report.get('attribution')
    if report.get('attribution_suppressed') is False and isinstance(buckets,list) and len(buckets)<=100:
        rows.extend(('attribution',bucket,bucket.get('metrics',{})) for bucket in buckets if isinstance(bucket,dict))
    for row_type,bucket,metrics in rows:
        if metrics.get('suppressed'):
            continue
        for key in allowed:
            count = metrics.get(key)
            if type(count) is int and count>=0:
                writer.writerow([safe(report.get(k,'')) for k in ('revision','unit','basis','calendar')]+
                                [row_type]+[safe(str(bucket.get(k,''))[:80]) for k in dimensions]+[key,count])
    return stream.getvalue()
