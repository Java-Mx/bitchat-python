"""BitChat CLI entry point bootstrap."""

import sys

from bitchat.app.application import Application


def main() -> None:
    """Bootstrap and run the BitChat application."""
    app = Application()
    exit_code = app.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
