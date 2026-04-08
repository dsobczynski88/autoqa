#!/usr/bin/env python3
import asyncio
from autoqa.api.main import app

async def test_lifespan():
    print("Testing lifespan startup...")
    try:
        # Simulate the lifespan startup
        async with app.router.lifespan_context(app):
            print("✓ Lifespan startup successful")
            print(f"✓ Service attached: {hasattr(app.state, 'service')}")
            if hasattr(app.state, 'service'):
                print(f"✓ Service type: {type(app.state.service)}")
    except Exception as e:
        print(f"✗ Lifespan startup failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_lifespan())
