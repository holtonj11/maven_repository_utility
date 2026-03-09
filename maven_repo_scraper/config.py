"""
Configuration management for Maven Repository Scraper.
Provides heavily configurable settings via command-line arguments and config files.
"""

import argparse
import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class RepositoryConfig:
    """Configuration for a single Maven repository."""
    url: str
    name: str = ""
    browse_url: str = ""  # For repositories that need special handling
    
    def __post_init__(self):
        if not self.name:
            self.name = self.url.split("//")[-1].split("/")[0]


@dataclass 
class XMLValidationConfig:
    """Configuration for XML validation settings."""
    validation_mode: str = "xsd"  # "simple" or "xsd"
    xsd_filename: str = "maven-4.0.0.xsd"
    xsd_url: str = "https://maven.apache.org/xsd/maven-4.0.0.xsd"
    xsd_directory: str = ""  # Will be set to script directory by default
    
    def get_xsd_path(self) -> Path:
        """Get the full path to the XSD file."""
        return Path(self.xsd_directory) / self.xsd_filename


@dataclass
class OutputConfig:
    """Configuration for output settings."""
    output_directory: str = ""  # Will be set to script directory by default
    tree_directory_name: str = "directoryTree_output"
    timestamp_format: str = "%Y-%m-%dT%H:%M:%S.%f"
    
    def get_tree_directory(self) -> Path:
        """Get the full path to the tree output directory."""
        return Path(self.output_directory) / self.tree_directory_name


@dataclass
class LoggingConfig:
    """Configuration for logging settings."""
    log_to_file: bool = True
    log_to_console: bool = True
    log_file_name: str = "maven_scraper.log"
    log_directory: str = ""  # Will be set to script directory by default
    log_level: str = "INFO"
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 5
    
    def get_log_file_path(self) -> Path:
        """Get the full path to the log file."""
        return Path(self.log_directory) / self.log_file_name


@dataclass
class ScraperConfig:
    """Main configuration class for the Maven repository scraper."""
    
    # Repository settings
    repositories: List[RepositoryConfig] = field(default_factory=list)
    local_repository: str = ""  # Will be set to user/.m2/repository by default
    
    # XML validation settings
    xml_validation: XMLValidationConfig = field(default_factory=XMLValidationConfig)
    
    # Output settings
    output: OutputConfig = field(default_factory=OutputConfig)
    
    # Logging settings
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # Scraper behavior settings
    max_retries: int = 3
    retry_delay: float = 2.0  # seconds
    download_timeout: int = 300  # seconds
    max_concurrent_downloads: int = 5
    min_jar_size_bytes: int = 5 * 1024  # 5 KB
    
    # Dependency resolution settings
    max_dependency_depth: int = 100  # Prevent infinite recursion
    include_optional_dependencies: bool = True
    
    # Known libraries tracking
    known_libraries_file: str = "known_libraries.json"
    
    def get_known_libraries_path(self) -> Path:
        """Get the full path to the known libraries tracking file."""
        return Path(self.output.output_directory) / self.known_libraries_file


def get_default_m2_repository() -> str:
    """Get the default Maven local repository path (user/.m2/repository)."""
    home = Path.home()
    m2_repo = home / ".m2" / "repository"
    return str(m2_repo)


def parse_repository_url(url: str) -> RepositoryConfig:
    """Parse a repository URL into a RepositoryConfig object."""
    url = url.strip()
    if not url:
        raise ValueError("Repository URL cannot be empty")
    
    # Handle special repository types
    if "mulesoft.org" in url and "#browse" in url:
        return RepositoryConfig(
            url=url,
            name="mulesoft-releases",
            browse_url=url
        )
    elif "repo1.maven.org" in url or "maven2" in url:
        return RepositoryConfig(
            url=url,
            name="maven-central"
        )
    else:
        return RepositoryConfig(url=url)


def load_config_from_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from a JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)


def save_config_to_file(config: ScraperConfig, config_path: str) -> None:
    """Save configuration to a JSON file."""
    config_dict = {
        'repositories': [
            {'url': r.url, 'name': r.name, 'browse_url': r.browse_url}
            for r in config.repositories
        ],
        'local_repository': config.local_repository,
        'xml_validation': {
            'validation_mode': config.xml_validation.validation_mode,
            'xsd_filename': config.xml_validation.xsd_filename,
            'xsd_url': config.xml_validation.xsd_url,
            'xsd_directory': config.xml_validation.xsd_directory
        },
        'output': {
            'output_directory': config.output.output_directory,
            'tree_directory_name': config.output.tree_directory_name,
            'timestamp_format': config.output.timestamp_format
        },
        'logging': {
            'log_to_file': config.logging.log_to_file,
            'log_to_console': config.logging.log_to_console,
            'log_file_name': config.logging.log_file_name,
            'log_directory': config.logging.log_directory,
            'log_level': config.logging.log_level
        },
        'max_retries': config.max_retries,
        'retry_delay': config.retry_delay,
        'download_timeout': config.download_timeout,
        'max_concurrent_downloads': config.max_concurrent_downloads,
        'min_jar_size_bytes': config.min_jar_size_bytes,
        'max_dependency_depth': config.max_dependency_depth,
        'include_optional_dependencies': config.include_optional_dependencies
    }
    
    with open(config_path, 'w') as f:
        json.dump(config_dict, f, indent=2)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the Maven scraper."""
    parser = argparse.ArgumentParser(
        description="Maven Repository Scraper and Maintenance Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with default settings
  python maven_scraper.py
  
  # Add custom repositories
  python maven_scraper.py --add-repo https://my.repo.com/maven2
  
  # Use simple XML validation instead of XSD
  python maven_scraper.py --xml-validation simple
  
  # Custom output directory
  python maven_scraper.py --output-dir /path/to/output
        """
    )
    
    # Repository arguments
    repo_group = parser.add_argument_group('Repository Settings')
    repo_group.add_argument(
        '--add-repo', '--ar',
        action='append',
        dest='repositories',
        metavar='URL',
        help='Add a repository URL (can be used multiple times)'
    )
    repo_group.add_argument(
        '--local-repo', '--lr',
        default=None,
        metavar='PATH',
        help='Local repository path (default: user/.m2/repository)'
    )
    repo_group.add_argument(
        '--config-file', '-c',
        metavar='PATH',
        help='Load configuration from a JSON file'
    )
    
    # XML Validation arguments
    xml_group = parser.add_argument_group('XML Validation Settings')
    xml_group.add_argument(
        '--xml-validation', '--xv',
        choices=['simple', 'xsd'],
        default='xsd',
        help='XML validation mode: simple (check <?xml header) or xsd (validate against XSD schema)'
    )
    xml_group.add_argument(
        '--xsd-file',
        default='maven-4.0.0.xsd',
        metavar='FILENAME',
        help='Name of the XSD file to use for validation'
    )
    xml_group.add_argument(
        '--xsd-url',
        default='https://maven.apache.org/xsd/maven-4.0.0.xsd',
        metavar='URL',
        help='URL to download XSD schema from'
    )
    xml_group.add_argument(
        '--xsd-dir',
        default=None,
        metavar='PATH',
        help='Directory containing XSD file (default: script directory)'
    )
    
    # Output arguments
    output_group = parser.add_argument_group('Output Settings')
    output_group.add_argument(
        '--output-dir', '-o',
        default=None,
        metavar='PATH',
        help='Output directory for dependency trees (default: script directory)'
    )
    output_group.add_argument(
        '--tree-dir-name',
        default='directoryTree_output',
        metavar='NAME',
        help='Name of the dependency tree output directory'
    )
    
    # Logging arguments
    log_group = parser.add_argument_group('Logging Settings')
    log_group.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Logging level'
    )
    log_group.add_argument(
        '--no-file-log',
        action='store_true',
        help='Disable logging to file'
    )
    log_group.add_argument(
        '--no-console-log',
        action='store_true',
        help='Disable logging to console'
    )
    log_group.add_argument(
        '--log-file',
        default='maven_scraper.log',
        metavar='FILENAME',
        help='Log file name'
    )
    
    # Scraper behavior arguments
    scraper_group = parser.add_argument_group('Scraper Behavior Settings')
    scraper_group.add_argument(
        '--max-retries',
        type=int,
        default=3,
        metavar='N',
        help='Maximum number of retry attempts for downloads'
    )
    scraper_group.add_argument(
        '--retry-delay',
        type=float,
        default=2.0,
        metavar='SECONDS',
        help='Delay between retry attempts'
    )
    scraper_group.add_argument(
        '--timeout',
        type=int,
        default=300,
        metavar='SECONDS',
        help='Download timeout in seconds'
    )
    scraper_group.add_argument(
        '--max-depth',
        type=int,
        default=100,
        metavar='N',
        help='Maximum dependency resolution depth'
    )
    scraper_group.add_argument(
        '--min-jar-size',
        type=int,
        default=5120,
        metavar='BYTES',
        help='Minimum valid JAR file size in bytes (default: 5120 = 5KB)'
    )
    
    # Utility arguments
    util_group = parser.add_argument_group('Utility Options')
    util_group.add_argument(
        '--save-config',
        metavar='PATH',
        help='Save current configuration to a JSON file and exit'
    )
    util_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually downloading'
    )
    util_group.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    
    return parser


def build_config_from_args(args: argparse.Namespace, script_dir: str) -> ScraperConfig:
    """Build a ScraperConfig from parsed command-line arguments."""
    
    # Load from config file if specified
    config_dict = {}
    if hasattr(args, 'config_file') and args.config_file:
        config_dict = load_config_from_file(args.config_file)
    
    # Build repositories list
    repositories = []
    
    # Add default repositories
    default_repos = [
        "https://repository.mulesoft.org/nexus/#browse/browse:releases",
        "https://repo1.maven.org/maven2/"
    ]
    
    # Start with config file repositories or defaults
    if 'repositories' in config_dict:
        for repo_dict in config_dict['repositories']:
            repositories.append(RepositoryConfig(**repo_dict))
    else:
        for url in default_repos:
            repositories.append(parse_repository_url(url))
    
    # Add command-line repositories
    if args.repositories:
        for url in args.repositories:
            repo = parse_repository_url(url)
            if repo.url not in [r.url for r in repositories]:
                repositories.append(repo)
    
    # Build XML validation config
    xml_validation = XMLValidationConfig(
        validation_mode=args.xml_validation,
        xsd_filename=args.xsd_file,
        xsd_url=args.xsd_url,
        xsd_directory=args.xsd_dir if args.xsd_dir else script_dir
    )
    
    # Build output config
    output = OutputConfig(
        output_directory=args.output_dir if args.output_dir else script_dir,
        tree_directory_name=args.tree_dir_name
    )
    
    # Build logging config
    logging_config = LoggingConfig(
        log_to_file=not args.no_file_log,
        log_to_console=not args.no_console_log,
        log_file_name=args.log_file,
        log_directory=script_dir,
        log_level=args.log_level
    )
    
    # Build main config
    config = ScraperConfig(
        repositories=repositories,
        local_repository=args.local_repo if args.local_repo else get_default_m2_repository(),
        xml_validation=xml_validation,
        output=output,
        logging=logging_config,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        download_timeout=args.timeout,
        max_dependency_depth=args.max_depth,
        min_jar_size_bytes=args.min_jar_size
    )
    
    return config


def get_config(script_dir: str = None, argv: list = None) -> ScraperConfig:
    """
    Main entry point for getting configuration.
    
    Args:
        script_dir: Directory where the script is located
        argv: Command-line arguments (uses sys.argv if not provided)
    
    Returns:
        ScraperConfig object with all settings configured
    """
    if script_dir is None:
        script_dir = os.getcwd()
    
    parser = create_argument_parser()
    args = parser.parse_args(argv)
    
    config = build_config_from_args(args, script_dir)
    
    # Save config if requested
    if args.save_config:
        save_config_to_file(config, args.save_config)
        print(f"Configuration saved to {args.save_config}")
        exit(0)
    
    return config


if __name__ == "__main__":
    # Test the configuration
    config = get_config()
    print(f"Local repository: {config.local_repository}")
    print(f"Repositories: {[r.url for r in config.repositories]}")
    print(f"XML validation mode: {config.xml_validation.validation_mode}")