#!/usr/bin/env python3
"""
Proxy to strip x-api-key header and forward to opencode.
Anthropic: port 8080
OpenAI: port 8081
"""
import os
import asyncio
from aiohttp import web, ClientSession, TCPConnector

CF_ACCESS_TOKEN = os.environ.get('CF_ACCESS_TOKEN', '')
API_BASE_URL = os.environ.get('API_BASE_URL', '')

async def health(request: web.Request) -> web.Response:
    return web.Response(text='OK')

async def proxy_anthropic(request: web.Request) -> web.Response:
    """Proxy requests to opencode anthropic endpoint, stripping x-api-key."""
    path = request.path
    target_url = f"{API_BASE_URL}/anthropic{path}"

    # Copy headers but remove x-api-key
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ('host', 'x-api-key', 'content-length')}
    headers['cf-access-token'] = CF_ACCESS_TOKEN

    body = await request.read()

    connector = TCPConnector(ssl=True)
    async with ClientSession(connector=connector) as session:
        async with session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body
        ) as resp:
            response_body = await resp.read()
            return web.Response(
                body=response_body,
                status=resp.status,
                headers={k: v for k, v in resp.headers.items()
                        if k.lower() not in ('transfer-encoding', 'content-encoding')}
            )

async def proxy_openai(request: web.Request) -> web.Response:
    """Proxy requests to opencode openai endpoint."""
    path = request.path
    target_url = f"{API_BASE_URL}/openai{path}"

    # Copy headers but strip authorization
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ('host', 'authorization', 'content-length')}
    headers['cf-access-token'] = CF_ACCESS_TOKEN

    body = await request.read()

    connector = TCPConnector(ssl=True)
    async with ClientSession(connector=connector) as session:
        async with session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body
        ) as resp:
            response_body = await resp.read()
            return web.Response(
                body=response_body,
                status=resp.status,
                headers={k: v for k, v in resp.headers.items()
                        if k.lower() not in ('transfer-encoding', 'content-encoding')}
            )

def create_anthropic_app():
    app = web.Application()
    app.router.add_get('/health', health)
    app.router.add_route('*', '/{path:.*}', proxy_anthropic)
    return app

def create_openai_app():
    app = web.Application()
    app.router.add_get('/health', health)
    app.router.add_route('*', '/{path:.*}', proxy_openai)
    return app

async def main():
    anthropic_app = create_anthropic_app()
    openai_app = create_openai_app()

    runner1 = web.AppRunner(anthropic_app)
    runner2 = web.AppRunner(openai_app)

    await runner1.setup()
    await runner2.setup()

    site1 = web.TCPSite(runner1, '0.0.0.0', 8080)
    site2 = web.TCPSite(runner2, '0.0.0.0', 8081)

    print("Starting proxies:")
    print("  Anthropic proxy: http://0.0.0.0:8080")
    print("  OpenAI proxy: http://0.0.0.0:8081")

    await site1.start()
    await site2.start()

    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
