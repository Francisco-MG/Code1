"""Application module for Code1."""


class App:
    """Main application class."""

    def __init__(self, name="Code1"):
        """Initialize the application.
        
        Args:
            name: The name of the application.
        """
        self.name = name

    def run(self):
        """Run the application."""
        return f"Running {self.name}"

    def greet(self, user=None):
        """Greet a user.
        
        Args:
            user: The user to greet. If None, greets everyone.
            
        Returns:
            A greeting message.
        """
        if user:
            return f"Hello, {user}!"
        return "Hello, World!"
