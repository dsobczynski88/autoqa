#!/usr/bin/env python3
import sys
import traceback

print("=" * 60)
print("Testing imports...")
print("=" * 60)

# Test 1: Import autoqa package
try:
    import autoqa
    print("✓ autoqa package imported")
except Exception as e:
    print(f"✗ Failed to import autoqa: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 2: Import autoqa.api
try:
    import autoqa.api
    print("✓ autoqa.api package imported")
except Exception as e:
    print(f"✗ Failed to import autoqa.api: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 3: Import schemas
try:
    from autoqa.api.schemas import ReviewRequest, ReviewResponse
    print("✓ Schemas imported")
except Exception as e:
    print(f"✗ Failed to import schemas: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 4: Import services
try:
    from autoqa.api.services import RTMReviewService
    print("✓ Services imported")
except Exception as e:
    print(f"✗ Failed to import services: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 5: Import routes
try:
    from autoqa.api.routes import router
    print("✓ Routes imported")
except Exception as e:
    print(f"✗ Failed to import routes: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 6: Import main and app
try:
    from autoqa.api.main import app
    print("✓ App imported")
    print(f"  - Title: {app.title}")
    print(f"  - Version: {app.version}")
    print(f"  - Routes: {len(app.routes)}")
    for route in app.routes:
        print(f"    - {route.path}")
except Exception as e:
    print(f"✗ Failed to import app: {e}")
    traceback.print_exc()
    sys.exit(1)

print("=" * 60)
print("All imports successful!")
print("=" * 60)
