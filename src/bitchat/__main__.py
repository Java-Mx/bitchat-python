"""BitChat CLI entry point."""

from bitchat import __version__


def main() -> None:
    """Entry point for the bitchat command."""
    print(f"BitChat Python v{__version__}")
    print("Status: development")
    print("Phase: repository foundation")
    print()
    print("BitChat is not yet functional.")
    print("See README.md for project status and roadmap.")


if __name__ == "__main__":
    main()
