#!/usr/bin/env python3
"""
Single-port proxy that injects a Cloudflare Access token and forwards to OpenCode.

OpenCode is a unified gateway — all requests (Anthropic, OpenAI, etc.) go to
the same base URL. This proxy just strips outbound auth headers and injects
the CF Access token so the request clears the Cloudflare Access policy.

CF Access token is loaded dynamically from ~/.cloudflared/<hostname>-*-token
(written by `cloudflared access login <URL>`), with fallback to CF_ACCESS_TOKEN
env var. Token is re-read on every request so refresh-token.sh takes effect
without a container restart.
"""
import glob
import os
import sys
import asyncio
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

API_BASE_URL = os.environ.get('API_BASE_URL', '').rstrip('/')

_remote_host = urlparse(API_BASE_URL).hostname or ''
_TOKEN_PATTERN = os.path.expanduser(f'~/.cloudflared/{_remote_host}-*-token') if _remote_host else ''
_TOKEN_ENV = os.environ.get('CF_ACCESS_TOKEN', '')

HOP_BY_HOP = frozenset([
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade',
])

# Auth headers that should never be forwarded to the upstream
STRIP_HEADERS = frozenset(['host', 'x-api-key', 'authorization', 'content-length', 'cf-access-token'])

session: aiohttp.ClientSession = None


def get_cf_token() -> str:
    if _TOKEN_PATTERN:
        files = glob.glob(_TOKEN_PATTERN)
        if files:
            try:
                token = open(files[0]).read().strip()
                if token:
                    return token
            except OSError:
                pass
    if _TOKEN_ENV:
        return _TOKEN_ENV
    print('WARNING: No CF Access token found — requests will likely be rejected.', file=sys.stderr)
    return ''


async def health(request: web.Request) -> web.Response:
    return web.Response(text='OK')


async def proxy(request: web.Request) -> web.StreamResponse:
    target_url = f'{API_BASE_URL}{request.path_qs}'
    print(f'[proxy] {request.method} {request.path}', file=sys.stderr)

    headers = {'cf-access-token': get_cf_token()}
    for k, v in request.headers.items():
        if k.lower() not in STRIP_HEADERS and k.lower() not in HOP_BY_HOP:
            headers[k] = v

    body = await request.read() if request.can_read_body else None

    try:
        async with session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=600, sock_read=300),
        ) as resp:
            content_type = resp.headers.get('Content-Type', '')
            is_sse = 'text/event-stream' in content_type

            resp_headers = {}
            for k, v in resp.headers.items():
                if k.lower() not in HOP_BY_HOP | {'content-length', 'content-encoding'}:
                    resp_headers[k] = v

            if is_sse:
                response = web.StreamResponse(status=resp.status, headers=resp_headers)
                response.content_type = content_type
                await response.prepare(request)
                async for chunk in resp.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
            else:
                return web.Response(status=resp.status, headers=resp_headers, body=await resp.read())
    except Exception as e:
        print(f'[proxy] error: {e}', file=sys.stderr)
        return web.Response(status=502, text=f'Proxy error: {e}')


async def on_startup(app):
    global session
    connector = aiohttp.TCPConnector(ssl=True)
    session = aiohttp.ClientSession(connector=connector)


async def on_cleanup(app):
    await session.close()


async def main():
    if not API_BASE_URL:
        print('ERROR: API_BASE_URL is not set', file=sys.stderr)
        sys.exit(1)

    token = get_cf_token()
    src = f'~/.cloudflared/{_remote_host}-*-token' if glob.glob(_TOKEN_PATTERN) else 'CF_ACCESS_TOKEN env'
    print(f'CF Access token loaded from: {src}' if token else 'WARNING: Starting without CF Access token',
          file=sys.stderr)

    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get('/health', health)
    app.router.add_route('*', '/{path:.*}', proxy)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    print(f'Proxy listening on http://0.0.0.0:8080 → {API_BASE_URL}')
    while True:
        await asyncio.sleep(3600)


if __name__ == '__main__':
    asyncio.run(main())
