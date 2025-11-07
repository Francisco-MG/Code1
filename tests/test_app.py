"""Tests for the Code1 application."""
import unittest
import sys
import os

# Add the parent directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from code1.app import App


class TestApp(unittest.TestCase):
    """Test cases for the App class."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = App()

    def test_init_default_name(self):
        """Test that App initializes with default name."""
        self.assertEqual(self.app.name, "Code1")

    def test_init_custom_name(self):
        """Test that App initializes with custom name."""
        custom_app = App("CustomApp")
        self.assertEqual(custom_app.name, "CustomApp")

    def test_run(self):
        """Test that run method returns expected string."""
        result = self.app.run()
        self.assertEqual(result, "Running Code1")

    def test_greet_without_user(self):
        """Test greet method without user."""
        result = self.app.greet()
        self.assertEqual(result, "Hello, World!")

    def test_greet_with_user(self):
        """Test greet method with user."""
        result = self.app.greet("Alice")
        self.assertEqual(result, "Hello, Alice!")


if __name__ == '__main__':
    unittest.main()
