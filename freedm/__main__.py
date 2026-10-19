"""Allow ``python -m freedm`` to start the application."""
from freedm.main import main

if __name__ == "__main__":
    raise SystemExit(main())
