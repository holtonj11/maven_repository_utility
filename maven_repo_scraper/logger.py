"""
Logging system for Maven Repository Scraper.
Provides comprehensive logging to both file and console with configurable settings.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
import threading

# Thread-local storage for context
_context = threading.local()


class ContextFilter(logging.Filter):
    """
    A filter that adds contextual information to log records.
    This allows tracking which library or operation is being processed.
    """
    
    def filter(self, record):
        record.library = getattr(_context, 'library', '')
        record.operation = getattr(_context, 'operation', '')
        return True


class ColoredFormatter(logging.Formatter):
    """
    A formatter that adds colors to console output for better readability.
    """
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # Add color to the level name
        if record.levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelname]}{record.levelname}{self.RESET}"
            )
        return super().format(record)


class MavenScraperLogger:
    """
    Comprehensive logging system for the Maven repository scraper.
    
    Features:
    - Dual output to file and console
    - Rotating file handler with size limits
    - Colored console output
    - Context tracking for libraries and operations
    - Performance timing utilities
    """
    
    def __init__(
        self,
        name: str = "maven_scraper",
        log_file: Optional[Path] = None,
        log_level: str = "INFO",
        log_to_file: bool = True,
        log_to_console: bool = True,
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB
        backup_count: int = 5
    ):
        """
        Initialize the logger.
        
        Args:
            name: Logger name
            log_file: Path to the log file
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_to_file: Whether to log to file
            log_to_console: Whether to log to console
            max_bytes: Maximum size of each log file
            backup_count: Number of backup files to keep
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        self.logger.handlers = []  # Clear existing handlers
        
        # Create formatters
        self.file_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(library)s | %(operation)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.console_formatter = ColoredFormatter(
            fmt='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Add context filter
        context_filter = ContextFilter()
        self.logger.addFilter(context_filter)
        
        # Setup file handler
        if log_to_file and log_file:
            self._setup_file_handler(log_file, max_bytes, backup_count)
        
        # Setup console handler
        if log_to_console:
            self._setup_console_handler()
    
    def _setup_file_handler(self, log_file: Path, max_bytes: int, backup_count: int):
        """Setup rotating file handler."""
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(self.logger.level)
        file_handler.setFormatter(self.file_formatter)
        self.logger.addHandler(file_handler)
    
    def _setup_console_handler(self):
        """Setup console handler with colored output."""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.logger.level)
        console_handler.setFormatter(self.console_formatter)
        self.logger.addHandler(console_handler)
    
    def set_context(self, library: str = "", operation: str = ""):
        """
        Set the current logging context.
        
        Args:
            library: The library currently being processed
            operation: The operation currently being performed
        """
        _context.library = library
        _context.operation = operation
    
    def clear_context(self):
        """Clear the current logging context."""
        _context.library = ""
        _context.operation = ""
    
    def debug(self, message: str, *args, **kwargs):
        """Log a debug message."""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """Log an info message."""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Log a warning message."""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """Log an error message."""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """Log a critical message."""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """Log an exception with traceback."""
        self.logger.exception(message, *args, **kwargs)
    
    def library_info(self, library: str, message: str):
        """
        Log information about a specific library.
        
        Args:
            library: Library coordinate (e.g., com.example:lib:1.0)
            message: Log message
        """
        self.set_context(library=library)
        self.info(message)
        self.clear_context()
    
    def operation_start(self, operation: str, library: str = ""):
        """
        Log the start of an operation.
        
        Args:
            operation: Operation name
            library: Library being processed (optional)
        """
        self.set_context(library=library, operation=operation)
        self.info(f"Starting {operation}")
    
    def operation_end(self, operation: str, success: bool = True, library: str = ""):
        """
        Log the end of an operation.
        
        Args:
            operation: Operation name
            success: Whether the operation succeeded
            library: Library being processed (optional)
        """
        self.set_context(library=library, operation=operation)
        status = "completed successfully" if success else "failed"
        self.info(f"{operation} {status}")
        self.clear_context()


class Timer:
    """
    Context manager for timing operations.
    Logs the duration of the operation upon exit.
    """
    
    def __init__(self, logger: MavenScraperLogger, operation: str, library: str = ""):
        """
        Initialize the timer.
        
        Args:
            logger: The logger to use
            operation: Name of the operation being timed
            library: Library being processed (optional)
        """
        self.logger = logger
        self.operation = operation
        self.library = library
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.operation_start(self.operation, self.library)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()
        success = exc_type is None
        self.logger.operation_end(self.operation, success, self.library)
        self.logger.info(f"{self.operation} took {duration:.2f} seconds")
        return False  # Don't suppress exceptions
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()


def setup_logger(config) -> MavenScraperLogger:
    """
    Setup the logger from configuration.
    
    Args:
        config: ScraperConfig object with logging settings
    
    Returns:
        Configured MavenScraperLogger instance
    """
    return MavenScraperLogger(
        name="maven_scraper",
        log_file=config.logging.get_log_file_path() if config.logging.log_to_file else None,
        log_level=config.logging.log_level,
        log_to_file=config.logging.log_to_file,
        log_to_console=config.logging.log_to_console,
        max_bytes=config.logging.log_max_bytes,
        backup_count=config.logging.log_backup_count
    )


# Global logger instance (will be initialized by setup_logger)
_global_logger: Optional[MavenScraperLogger] = None


def get_logger() -> MavenScraperLogger:
    """
    Get the global logger instance.
    
    Returns:
        The global MavenScraperLogger instance
    
    Raises:
        RuntimeError: If logger has not been initialized
    """
    if _global_logger is None:
        raise RuntimeError("Logger has not been initialized. Call setup_logger first.")
    return _global_logger


def init_logger(config) -> MavenScraperLogger:
    """
    Initialize the global logger from configuration.
    
    Args:
        config: ScraperConfig object with logging settings
    
    Returns:
        Configured MavenScraperLogger instance
    """
    global _global_logger
    _global_logger = setup_logger(config)
    return _global_logger


if __name__ == "__main__":
    # Test the logger
    from config import ScraperConfig, LoggingConfig
    
    config = ScraperConfig(
        logging=LoggingConfig(
            log_to_file=True,
            log_to_console=True,
            log_level="DEBUG"
        )
    )
    
    logger = setup_logger(config)
    
    logger.info("Starting Maven scraper")
    logger.debug("Debug message")
    logger.warning("Warning message")
    logger.error("Error message")
    
    logger.library_info("com.example:test:1.0", "Processing library")
    
    with Timer(logger, "Download operation", "com.example:test:1.0"):
        import time
        time.sleep(1)
    
    logger.info("Maven scraper completed")