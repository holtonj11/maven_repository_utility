"""
Maven Repository Scraper and Maintenance Tool

A comprehensive tool for scraping Maven repositories, resolving dependencies,
and maintaining a local Maven repository.

Usage:
    python -m maven_repo_scraper [options]
    
For more information:
    python -m maven_repo_scraper --help
"""

from .config import (
    ScraperConfig,
    RepositoryConfig,
    XMLValidationConfig,
    OutputConfig,
    LoggingConfig,
    get_config,
    get_default_m2_repository
)

from .logger import (
    MavenScraperLogger,
    setup_logger,
    init_logger,
    get_logger,
    Timer
)

from .pom_parser import (
    POMParser,
    POMInfo,
    Dependency,
    IssueType,
    XSDValidator,
    is_html_content,
    simple_xml_validation
)

from .repository_client import (
    RepositoryClient,
    MultiRepositoryClient,
    LibraryInfo
)

from .dependency_resolver import (
    DependencyResolver,
    DependencyTree,
    ResolvedLibrary
)

from .output_generator import (
    OutputGenerator,
    DependencyTreeWriter
)

from .local_repository import (
    LocalRepositoryManager,
    LocalLibrary
)

__version__ = "1.0.0"
__author__ = "Maven Repository Scraper Team"

__all__ = [
    # Config
    'ScraperConfig',
    'RepositoryConfig',
    'XMLValidationConfig',
    'OutputConfig',
    'LoggingConfig',
    'get_config',
    'get_default_m2_repository',
    
    # Logger
    'MavenScraperLogger',
    'setup_logger',
    'init_logger',
    'get_logger',
    'Timer',
    
    # POM Parser
    'POMParser',
    'POMInfo',
    'Dependency',
    'IssueType',
    'XSDValidator',
    'is_html_content',
    'simple_xml_validation',
    
    # Repository Client
    'RepositoryClient',
    'MultiRepositoryClient',
    'LibraryInfo',
    
    # Dependency Resolver
    'DependencyResolver',
    'DependencyTree',
    'ResolvedLibrary',
    
    # Output Generator
    'OutputGenerator',
    'DependencyTreeWriter',
    
    # Local Repository
    'LocalRepositoryManager',
    'LocalLibrary'
]