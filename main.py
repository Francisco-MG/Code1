"""Main module for Code1 application."""

from code1.app import App


def main():
    """Main entry point for the application."""
    app = App()
    print(app.greet())
    print(app.run())
    return 0


if __name__ == "__main__":
    exit(main())
