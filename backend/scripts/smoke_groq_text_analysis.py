"""One synthetic, opt-in provider request. Never collected or run by pytest/CI."""

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Authorize one real Groq request')
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live to explicitly request the single provider call')
    # Direct script execution adds scripts/, not backend/, to the import path.
    # Anchor imports and the optional local .env to this checkout, not cwd.
    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root))
    from dotenv import load_dotenv
    load_dotenv(backend_root / '.env', override=False)
    if not os.environ.get('GROQ_API_KEY', '').strip():
        parser.exit(2, 'SKIPPED: GROQ_API_KEY is not configured.\n')

    from app.ai_engine.analysis import Evidence
    from app.ai_engine.errors import AnalysisError
    from app.ai_engine.groq_adapter import create_text_analyzer

    async def run():
        async with create_text_analyzer() as analyzer:
            result = await analyzer.analyze([
                Evidence(source_id='smoke-note-1', content='We decided to use PostgreSQL for the MVP database.')
            ])
        if not result.analysis.observations:
            raise RuntimeError('Smoke expected a supported observation for an explicit decision')
        print(json.dumps({'status': 'passed', **asdict(result.metadata),
                          'analysis': result.analysis.model_dump()}))
    try:
        asyncio.run(run())
    except AnalysisError as error:
        report = {'status': 'failed', 'code': error.code}
        if error.metadata is not None:
            report['metadata'] = asdict(error.metadata)
        print(json.dumps(report))
        parser.exit(1)
    except RuntimeError:
        parser.exit(1, 'FAILED: smoke assertion\n')


if __name__ == '__main__':
    main()
