"""Explicit, bounded per-workspace repair. Dry-run by default; no dotenv discovery."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
from uuid import UUID


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=UUID,required=True)
    parser.add_argument('--user',required=True,help='Existing workspace owner identity, never an email or password')
    parser.add_argument('--limit',type=int,default=25,choices=range(1,101),metavar='1..100')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--max-input-bytes',type=int,default=32000,
                        help='Match deployed LLM_MAX_INPUT_BYTES; default32000')
    args=parser.parse_args(argv)
    # Only a connection explicitly supplied for this tool is used. No .env files
    # or ambient API/migration/worker connection fallback are read.
    dsn=os.getenv('NOTE_REPAIR_DATABASE_URL')
    if not dsn:
        print(json.dumps({'error':'Set NOTE_REPAIR_DATABASE_URL to the restricted runtime connection.'}))
        return 2
    previous={name:os.environ.get(name) for name in ('PYTHON_DOTENV_DISABLED','FLARE_DOTENV_PATH')}
    pool_logger=logging.getLogger('psycopg.pool')
    previous_level=pool_logger.level
    database=None
    try:
        os.environ['PYTHON_DOTENV_DISABLED']='1'
        os.environ.pop('FLARE_DOTENV_PATH',None)
        pool_logger.setLevel(logging.CRITICAL)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from app.models.database import Database, WorkspaceIdentity
        from app.services.note_repair import NoteRepair
        from app.config import AISettings
        database=Database(dsn)
        database.open()
        if not database.is_ready():
            print(json.dumps({'error':'Use the initialized restricted flare_app runtime connection.'}))
            return 2
        service=NoteRepair(database,WorkspaceIdentity(args.workspace,args.user),AISettings(max_input_bytes=args.max_input_bytes))
        plan=service.plan(limit=args.limit)
        result=service.apply(plan) if args.apply else {'planned':len(plan),'items':plan}
        print(json.dumps({'mode':'apply' if args.apply else 'dry-run',**result}))
        return 0
    except Exception:
        print(json.dumps({'error':'Repair stopped. Earlier completed notes may be repaired; run dry-run again. No source text is logged.'}))
        return 1
    finally:
        if database is not None:
            database.close()
        for name,value in previous.items():
            if value is None: os.environ.pop(name,None)
            else: os.environ[name]=value
        pool_logger.setLevel(previous_level)


if __name__=='__main__':
    raise SystemExit(main())
