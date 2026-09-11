"""One bounded retry for Groq's strict-schema generation failure only."""
import groq


async def create_strict_completion(client, request):
    strict_schema = request.get('response_format', {})
    strict = (strict_schema.get('type') == 'json_schema'
              and strict_schema.get('json_schema', {}).get('strict') is True)
    for attempt in range(2):
        try:
            return await client.chat.completions.with_raw_response.create(**request)
        except groq.APIStatusError as error:
            if attempt or not strict or error.status_code != 400:
                raise
            try:
                body = error.response.json()
            except ValueError:
                raise error from None
            detail = body.get('error') if isinstance(body, dict) else None
            if not isinstance(detail, dict) or detail.get('code') != 'json_validate_failed':
                raise
            # The provider code identifies generated JSON failing the requested
            # schema. Never inspect or salvage failed_generation. Both attempts
            # remain inside the caller's existing overall deadline.
