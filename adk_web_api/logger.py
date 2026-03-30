"""Comprehensive Logging Utility for Debugging and Auditing"""
import logging
import sys
import time
from typing import Optional, Any, Dict
from datetime import datetime
from functools import wraps


# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for terminal."""
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    GREY = '\033[90m'


class SystemLogger:
    """
    Comprehensive logging system for debugging and auditing.
    
    Provides structured logging with:
    - Visual formatting with colors
    - Before/after value tracking
    - Flow tracking with timestamps
    - Success/failure indicators
    - Audit trail
    """
    
    def __init__(self, name: str = "MasterLogger", log_file: Optional[str] = None):
        """
        Initialize the logger.
        
        Args:
            name: Logger name
            log_file: Optional file path to write logs
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Clear existing handlers
        self.logger.handlers = []
        
        # Console handler with colors
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        # File handler if specified
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        
        self.logger.addHandler(console_handler)
        self.log_file = log_file
        self._indentation = 0
    
    def _indent(self) -> str:
        """Return indentation string based on current level."""
        return "  " * self._indentation
    
    def _color(self, text: str, color: str) -> str:
        """Apply color to text if not writing to file."""
        if self.log_file:
            return text
        return f"{color}{text}{Colors.RESET}"
    
    def section(self, title: str):
        """Print a section header with visual separation."""
        separator = "=" * 80
        self.logger.info("")
        self.logger.info(self._color(f"{separator}", Colors.BLUE))
        self.logger.info(self._color(f"  {title}".center(80), Colors.BOLD + Colors.CYAN))
        self.logger.info(self._color(f"{separator}", Colors.BLUE))
        self.logger.info("")
    
    def subsection(self, title: str):
        """Print a subsection header."""
        self.logger.info(self._color(f"{self._indent()}{'─' * 60}", Colors.GREY))
        self.logger.info(self._color(f"{self._indent()}  {title}", Colors.BOLD + Colors.MAGENTA))
        self.logger.info(self._color(f"{self._indent()}{'─' * 60}", Colors.GREY))
    
    def step(self, step_name: str, details: Optional[str] = None):
        """Log a step in the flow."""
        indent = self._indent()
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        message = f"{indent}📍 {self._color(f'[{timestamp}]', Colors.GREY)} {self._color(step_name, Colors.CYAN)}"
        if details:
            message += f"\n{indent}   └─ {details}"
        
        self.logger.info(message)
    
    def before_after(self, label: str, before: str, after: str, changed: bool):
        """
        Log before/after values with visual comparison.
        
        Args:
            label: What is being compared (e.g., "PII Masking")
            before: Value before transformation
            after: Value after transformation
            changed: Whether there was a change
        """
        indent = self._indent()
        change_icon = "✅" if changed else "ℹ️"
        change_color = Colors.GREEN if changed else Colors.GREY
        
        self.logger.info(f"{indent}{change_icon} {self._color(label, Colors.BOLD + change_color)}")
        
        if before:
            # Truncate long values for readability
            before_display = before[:500] if len(before) > 500 else before
            before_display += "..." if len(before) > 500 else ""
            self.logger.info(f"{indent}   -> Before: {self._color(before_display, Colors.GREY)}")
        
        if after and after != before:
            after_display = after[:500] if len(after) > 500 else after
            after_display += "..." if len(after) > 500 else ""
            self.logger.info(f"{indent}   -> After:  {self._color(after_display, Colors.GREEN)}")
    
    def success(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Log a success message."""
        indent = self._indent()
        self.logger.info(f"{indent}✅ {self._color(message, Colors.GREEN)}")
        if details:
            self.logger.info(f"{indent}   └─ {details}")
    
    def error(self, message: str, error: Optional[Exception] = None, details: Optional[Dict[str, Any]] = None):
        """Log an error message with optional exception details."""
        indent = self._indent()
        self.logger.error(f"{indent}❌ {self._color(message, Colors.RED)}")
        if error:
            self.logger.error(f"{indent}   └─ Error: {str(error)}")
            import traceback
            self.logger.error(f"{indent}   └─ Traceback:\n{indent}{''.join(traceback.format_tb(error.__traceback__))}")
        if details:
            self.logger.error(f"{indent}   └─ Details: {details}")
    
    def warning(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Log a warning message."""
        indent = self._indent()
        self.logger.warning(f"{indent}⚠️ {self._color(message, Colors.YELLOW)}")
        if details:
            self.logger.warning(f"{indent}   └─ {details}")
    
    def info(self, message: str, details: Optional[str] = None):
        """Log an informational message."""
        indent = self._indent()
        info_msg = f"{indent}ℹ️ {self._color(message, Colors.BLUE)}"
        if details:
            info_msg += f"\n{indent}   └─ {details}"
        self.logger.info(info_msg)
    
    def audit(self, event_type: str, data: Dict[str, Any]):
        """Log an audit event with structured data."""
        indent = self._indent()
        timestamp = datetime.now().isoformat()
        self.logger.info(f"{indent}📋 {self._color(f'AUDIT: {event_type}', Colors.BOLD + Colors.MAGENTA)}")
        self.logger.info(f"{indent}   └─ Timestamp: {timestamp}")
        for key, value in data.items():
            self.logger.info(f"{indent}   └─ {key}: {value}")
    
    def flow(self, from_step: str, to_step: str, data: Optional[str] = None):
        """Log a flow transition between components."""
        indent = self._indent()
        message = f"{indent}➡️ {self._color(from_step, Colors.CYAN)} → {self._color(to_step, Colors.GREEN)}"
        if data:
            message += f"\n{indent}      └─ {data}"
        self.logger.info(message)
    
    def indent(self):
        """Increase indentation level."""
        self._indentation += 1
    
    def dedent(self):
        """Decrease indentation level."""
        self._indentation = max(0, self._indentation - 1)
    
    def debug(self, message: str, details: Optional[Any] = None):
        """Log a debug message."""
        indent = self._indent()
        if details:
            self.logger.debug(f"{indent}🔍 {message}\n{indent}   └─ {details}")
        else:
            self.logger.debug(f"{indent}🔍 {message}")
    
    def agent_action(self, agent_name: str, action: str, details: Optional[str] = None):
        """Log an agent action."""
        indent = self._indent()
        message = f"{indent}🤖 {self._color(f'{agent_name}: {action}', Colors.BOLD + Colors.BLUE)}"
        if details:
            message += f"\n{indent}   └─ {details}"
        self.logger.info(message)
    
    def llm_call(self, model: str, direction: str, content_preview: str):
        """Log an LLM call (request or response)."""
        indent = self._indent()
        icon = "📤" if direction == "request" else "📥"
        direction_color = Colors.YELLOW if direction == "request" else Colors.GREEN
        
        content = content_preview[:300] if len(content_preview) > 300 else content_preview
        content += "..." if len(content_preview) > 300 else ""
        
        self.logger.info(f"{indent}{icon} {self._color(f'LLM {direction}', Colors.BOLD + direction_color)}")
        self.logger.info(f"{indent}   └─ Model: {model}")
        self.logger.info(f"{indent}   └─ Content: {self._color(content, Colors.GREY)}")


# Global logger instance
master_logger = SystemLogger(name="MasterLogger", log_file="app_debug.log")


def log_function(logger: Optional[SystemLogger] = None):
    """Decorator to log function entry/exit."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            lg = logger or master_logger
            lg.step(f"Entering: {func.__name__}")
            lg.indent()
            try:
                result = await func(*args, **kwargs)
                lg.dedent()
                lg.step(f"Exiting: {func.__name__} (Success)")
                return result
            except Exception as e:
                lg.dedent()
                lg.error(f"Error in {func.__name__}", error=e)
                raise
        return async_wrapper
    return decorator


def get_logger() -> SystemLogger:
    """Get the master logger instance."""
    return master_logger