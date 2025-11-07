# Code1

A simple Python application with a modular structure.

## Structure

- `code1/` - Main package directory
  - `app.py` - Application class with basic functionality
- `tests/` - Unit tests
  - `test_app.py` - Tests for the App class
- `main.py` - Main entry point

## Usage

Run the main script:
```bash
python3 main.py
```

Use the App class:
```python
from code1.app import App

app = App()
print(app.greet("User"))  # Hello, User!
print(app.run())          # Running Code1
```

## Testing

Run tests using unittest:
```bash
python3 -m unittest tests.test_app -v
```