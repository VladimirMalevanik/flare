"""Bounded synthetic security/load evidence, no providers/infrastructure/private inputs.

PYTHONPATH=backend python backend/scripts/check_zip_imports.py --entries 100 --file-bytes 2000
Use results to plan deployment benchmarks, never as production quota recommendations.
"""
import argparse
from dataclasses import asdict
import hashlib
import io
import json
import platform
import resource
import tempfile
import time
import zipfile
from app.import_staging.policy import ImportPolicy
from app.models.import_packages import ImportPackageError
from app.workers.import_worker import ImportProcessor


class NoDatabase:
    def step(self,job,action,data=None):
        assert action=='heartbeat'
        return {'ok':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entries',type=int,default=100)
    parser.add_argument('--file-bytes',type=int,default=2000)
    args=parser.parse_args(); policy=ImportPolicy()
    if not 1<=args.entries<=min(policy.entries,1000) or not 1<=args.file_bytes<=policy.file_bytes or args.entries*args.file_bytes>policy.expanded_bytes:
        parser.error('Fixture exceeds bounded local/test policy')
    # Deterministic UTF-8 data, moderate compressibility, no private evidence.
    body=(''.join(hashlib.sha256(str(i).encode()).hexdigest()+'\n' for i in range(args.file_bytes//65+1)))[:args.file_bytes]
    with tempfile.TemporaryFile() as source:
        with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for index in range(args.entries): archive.writestr(f'folder-{index%10}/note-{index}.md',body)
        source.flush(); source.seek(0,2); compressed=source.tell()
        processor=ImportProcessor(NoDatabase(),None,policy)
        job={'policy':asdict(policy),'file_size':compressed}
        started=time.perf_counter()
        rows=processor.decode(job,source,'manifest')['manifest']; inspected=time.perf_counter()
        chunks=0; expanded=0
        for row in rows:
            result=processor.decode(job,source,'file',row['ordinal'])
            assert ''.join(c['content'] for c in result['parsed']['chunks'])==body
            expanded+=row['fileBytes'];chunks+=len(result['parsed']['chunks'])
        end=time.perf_counter()
        maxrss=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        child_rss_bytes=maxrss if platform.system()=='Darwin' else maxrss*1024
    security=[]
    for name,value in [('../escape.md','unsafe_path'),('/absolute.md','unsafe_path'),('a\\b.md','unsafe_path')]:
        with tempfile.TemporaryFile() as source:
            with zipfile.ZipFile(source,'w') as z:z.writestr(name,'never extracted')
            source.flush();source.seek(0,2);job['file_size']=source.tell()
            try:processor.decode(job,source,'manifest')
            except ImportPackageError as e:assert e.code==value;security.append({'fixture':name,'rejection':e.code})
            else:raise AssertionError('Unsafe fixture accepted')
    print(json.dumps({'platform':platform.platform(),'python':platform.python_version(),
        'policyPurpose':'local/test defaults; not production-tuned', 'policy':asdict(policy),
        'entries':len(rows),'compressedBytes':compressed,'expandedBytes':expanded,'chunks':chunks,
        'inspectSeconds':round(inspected-started,4),'parseSeconds':round(end-inspected,4),
        'childPeakRssBytes':child_rss_bytes,'security':security,
        'limitations':'Decoder/local scratch only; excludes upload network, PostgreSQL publication, concurrent tenants and production storage.'},indent=2))


if __name__=='__main__':main()
