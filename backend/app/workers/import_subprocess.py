"""Isolated bounded ZIP decoder. Input is a server-owned scratch file descriptor."""
import csv
import json
import os
import resource
import sys
import zipfile
import zlib
from app.import_staging.policy import ImportPolicy
from app.services.zip_import import ZipRejected, manifest, parse_entry, verified_bytes


def main():
    request = json.loads(sys.stdin.buffer.read(16_384))
    policy = ImportPolicy(**request['policy'])
    resource.setrlimit(resource.RLIMIT_CPU, (policy.cpu_seconds, policy.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (policy.memory_bytes, policy.memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (request['outputLimit'], request['outputLimit']))
    csv.field_size_limit(policy.csv_field_bytes)
    try:
        with os.fdopen(request['fd'], 'rb', closefd=False) as stream:
            rows = manifest(stream, policy)
            if request['action']=='manifest':
                result = {'manifest':rows}
            else:
                ordinal = request['ordinal']
                with zipfile.ZipFile(stream) as archive:
                    raw,digest = verified_bytes(stream,archive,archive.infolist()[ordinal],policy,policy.expanded_bytes)
                    result = {'ordinal':ordinal,'hash':digest,'parsed':parse_entry(raw,rows[ordinal],policy)}
    except ZipRejected as error:
        result = {'error':str(error)}
    except (zipfile.BadZipFile,EOFError,zlib.error,UnicodeError,ValueError):
        result = {'error':'malformed_zip'}
    encoded = json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(encoded)>request['outputLimit']:
        encoded = b'{"error":"scratch_bound"}'
    sys.stdout.buffer.write(encoded)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
