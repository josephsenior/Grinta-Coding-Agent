"""Sentry error tracking setup and verification script.

Verifies Sentry configuration and tests error reporting.

Usage:
    python scripts/setup_sentry.py --check
    python scripts/setup_sentry.py --test
"""

import argparse
import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")


def check_sentry_config():
    """Check if Sentry is properly configured."""
    print("Checking Sentry configuration...\n")

    # Check environment variables
    sentry_dsn = os.getenv("SENTRY_DSN")
    sentry_env = os.getenv("SENTRY_ENVIRONMENT", "production")
    sentry_release = os.getenv("SENTRY_RELEASE", "unknown")

    print("Environment Variables:")
    print(f"  SENTRY_DSN: {'✓ Set' if sentry_dsn else '✗ Not set'}")
    print(f"  SENTRY_ENVIRONMENT: {sentry_env}")
    print(f"  SENTRY_RELEASE: {sentry_release}\n")

    if not sentry_dsn:
        print("⚠ WARNING: Sentry DSN not configured!")
        print("\nTo enable Sentry:")
        print("1. Sign up at https://sentry.io")
        print("2. Create a new Python project")
        print("3. Get your DSN from the project settings")
        print("4. Set environment variables:")
        print("   export SENTRY_DSN='your-dsn-here'")
        return False

    # Validate DSN format
    if not sentry_dsn.startswith(("https://", "http://")):
        print("⚠ WARNING: Sentry DSN format appears invalid")
        print("  DSN should start with https:// or http://")
        return False

    print("✓ Sentry DSN is configured")
    return True


def test_sentry():
    """Test Sentry error reporting."""
    print("Testing Sentry error reporting...\n")

    # Test backend Sentry
    try:
        import sentry_sdk
        from sentry_sdk import capture_exception

        sentry_dsn = os.getenv("SENTRY_DSN")
        if not sentry_dsn:
            print("✗ SENTRY_DSN not set, cannot test backend Sentry")
        else:
            sentry_sdk.init(
                dsn=sentry_dsn,
                environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
                release=os.getenv("SENTRY_RELEASE", "unknown"),
                traces_sample_rate=0.1,
            )

            # Send a test error
            try:
                raise ValueError("This is a test error from App backup script")
            except Exception as e:
                capture_exception(e)

            print("✓ Backend Sentry test error sent")
            print("  Check your Sentry dashboard to verify it was received")

    except ImportError:
        print("⚠ sentry-sdk not installed")
        print("  Install with: pip install sentry-sdk")
        return False
    except Exception as e:
        print(f"✗ Backend Sentry test failed: {e}")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Sentry Setup and Verification")
    parser.add_argument(
        "--check", action="store_true", help="Check Sentry configuration"
    )
    parser.add_argument(
        "--test", action="store_true", help="Test Sentry error reporting"
    )

    args = parser.parse_args()

    if args.check:
        success = check_sentry_config()
        sys.exit(0 if success else 1)
    elif args.test:
        success = test_sentry()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
