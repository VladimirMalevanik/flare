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
    """Only fixed aggregate columns; never export identities or raw campaign labels."""
    allowed = ('accounts','eligible','unknown','actual_verified','bypassed','verification_unknown',
               'committed_outcome','manual_analyze','voluntary_inspection','later_day_activity','later_day_observable')
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(('revision','unit','basis','calendar','metric','count'))
    def safe(value):
        text = str(value)
        return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else text
    for key in allowed:
        count = report.get('metrics',{}).get(key)
        if type(count) is int and count>=0:
            writer.writerow([safe(report.get(k,'')) for k in ('revision','unit','basis','calendar')]+[key,count])
    return stream.getvalue()
