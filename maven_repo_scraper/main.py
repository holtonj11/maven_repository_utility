#!/usr/bin/env python3
"""
Maven Repository Scraper and Maintenance Tool - Main Entry Point

This script provides comprehensive Maven repository scraping, dependency resolution,
and local repository maintenance capabilities.

Features:
- Scrape multiple Maven repositories
- Download libraries to local Maven repository
- Parse and validate POM files (simple or XSD validation)
- Resolve parent and transitive dependencies
- Detect and report issues with libraries
- Generate dependency tree outputs (text and JSON)
- Generate issue-specific reports
- Maintain an up-to-date local repository

Usage:
    python main.py [options]
    
Examples:
    # Basic usage with default settings
    python main.py
    
    # Add custom repositories
    python main.py --add-repo https://my.repo.com/maven2
    
    # Use simple XML validation
    python main.py --xml-validation simple
    
    # Custom output directory
    python main.py --output-dir /path/to/output
    
    # Save configuration for later use
    python main.py --save-config config.json
"""

import os
import sys
import json
import time
import signal
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from maven_repo_scraper.config import (
    ScraperConfig,
    RepositoryConfig,
    get_config,
    save_config_to_file,
    get_default_m2_repository
)
from maven_repo_scraper.logger import init_logger, get_logger, Timer
from maven_repo_scraper.pom_parser import POMParser, IssueType
from maven_repo_scraper.repository_client import MultiRepositoryClient, LibraryInfo
from maven_repo_scraper.dependency_resolver import DependencyResolver, DependencyTree
from maven_repo_scraper.output_generator import OutputGenerator


class MavenScraperApp:
    """
    Main application class for the Maven Repository Scraper.
    
    Coordinates all components and manages the scraping workflow.
    """
    
    def __init__(self, config: ScraperConfig):
        """
        Initialize the application.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.logger = None
        self.repository_client = None
        self.pom_parser = None
        self.dependency_resolver = None
        self.output_generator = None
        
        # Tracking
        self.known_libraries: Dict[str, LibraryInfo] = {}
        self.downloaded_count = 0
        self.error_count = 0
        self.start_time = None
        
        # Interrupt handling
        self._interrupted = False
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_interrupt)
    
    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signals gracefully."""
        self._interrupted = True
        if self.logger:
            self.logger.warning("Interrupt received, shutting down gracefully...")
    
    def initialize(self):
        """Initialize all components."""
        # Initialize logger
        self.logger = init_logger(self.config)
        self.logger.info("Initializing Maven Repository Scraper")
        
        # Log configuration
        self._log_configuration()
        
        # Initialize repository client
        self.logger.info("Initializing repository client...")
        self.repository_client = MultiRepositoryClient(
            repositories=self.config.repositories,
            max_retries=self.config.max_retries,
            retry_delay=self.config.retry_delay,
            timeout=self.config.download_timeout,
            max_concurrent=self.config.max_concurrent_downloads,
            logger=self.logger
        )
        
        # Initialize POM parser
        self.logger.info("Initializing POM parser...")
        self.pom_parser = POMParser(
            validation_mode=self.config.xml_validation.validation_mode,
            xsd_path=self.config.xml_validation.get_xsd_path(),
            xsd_url=self.config.xml_validation.xsd_url,
            min_jar_size=self.config.min_jar_size_bytes,
            logger=self.logger
        )
        
        # Initialize dependency resolver
        self.logger.info("Initializing dependency resolver...")
        self.dependency_resolver = DependencyResolver(
            local_repo=Path(self.config.local_repository),
            repository_client=self.repository_client,
            pom_parser=self.pom_parser,
            max_depth=self.config.max_dependency_depth,
            include_optional=self.config.include_optional_dependencies,
            logger=self.logger
        )
        
        # Initialize output generator
        self.output_generator = OutputGenerator(
            output_dir=self.config.output.output_directory,
            tree_dir_name=self.config.output.tree_directory_name,
            timestamp_format=self.config.output.timestamp_format,
            logger=self.logger
        )
        
        # Load known libraries
        self._load_known_libraries()
        
        # Create local repository directory
        repo_path = Path(self.config.local_repository)
        repo_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Local repository: {repo_path}")
        
        self.logger.info("Initialization complete")
    
    def _log_configuration(self):
        """Log the current configuration."""
        self.logger.info("=" * 60)
        self.logger.info("CONFIGURATION")
        self.logger.info("=" * 60)
        self.logger.info(f"Local repository: {self.config.local_repository}")
        self.logger.info(f"Output directory: {self.config.output.output_directory}")
        self.logger.info(f"XML validation mode: {self.config.xml_validation.validation_mode}")
        
        self.logger.info("Repositories:")
        for repo in self.config.repositories:
            self.logger.info(f"  - {repo.name}: {repo.url}")
        
        self.logger.info(f"Max retries: {self.config.max_retries}")
        self.logger.info(f"Retry delay: {self.config.retry_delay}s")
        self.logger.info(f"Download timeout: {self.config.download_timeout}s")
        self.logger.info(f"Max dependency depth: {self.config.max_dependency_depth}")
        self.logger.info(f"Min JAR size: {self.config.min_jar_size_bytes} bytes")
        self.logger.info("=" * 60)
    
    def _load_known_libraries(self):
        """Load known libraries from tracking file."""
        known_file = self.config.get_known_libraries_path()
        
        if known_file.exists():
            try:
                with open(known_file, 'r') as f:
                    data = json.load(f)
                
                for coord, lib_data in data.items():
                    lib = LibraryInfo(
                        group_id=lib_data.get('group_id', ''),
                        artifact_id=lib_data.get('artifact_id', ''),
                        version=lib_data.get('version', ''),
                        repository=lib_data.get('repository', ''),
                        url=lib_data.get('url', '')
                    )
                    self.known_libraries[coord] = lib
                
                self.logger.info(f"Loaded {len(self.known_libraries)} known libraries")
            except Exception as e:
                self.logger.warning(f"Error loading known libraries: {e}")
    
    def _save_known_libraries(self):
        """Save known libraries to tracking file."""
        known_file = self.config.get_known_libraries_path()
        
        try:
            known_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {}
            for coord, lib in self.known_libraries.items():
                data[coord] = {
                    'group_id': lib.group_id,
                    'artifact_id': lib.artifact_id,
                    'version': lib.version,
                    'repository': lib.repository,
                    'url': lib.url
                }
            
            with open(known_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.logger.info(f"Saved {len(self.known_libraries)} known libraries")
        except Exception as e:
            self.logger.error(f"Error saving known libraries: {e}")
    
    def discover_libraries(self) -> Dict[str, LibraryInfo]:
        """
        Discover all libraries from configured repositories.
        
        Returns:
            Dictionary of discovered libraries
        """
        self.logger.info("Starting library discovery...")
        
        all_libraries = {}
        
        def progress_callback(lib: LibraryInfo):
            if len(all_libraries) % 100 == 0:
                self.logger.info(f"Discovered {len(all_libraries)} libraries...")
        
        all_libraries = self.repository_client.discover_all_libraries(progress_callback)
        
        self.logger.info(f"Discovery complete: {len(all_libraries)} unique libraries found")
        
        return all_libraries
    
    def download_libraries(
        self,
        libraries: Dict[str, LibraryInfo],
        overwrite: bool = False
    ) -> int:
        """
        Download all libraries to local repository.
        
        Args:
            libraries: Libraries to download
            overwrite: Whether to overwrite existing files
        
        Returns:
            Number of successfully downloaded libraries
        """
        self.logger.info(f"Starting download of {len(libraries)} libraries...")
        
        success_count = 0
        error_count = 0
        total = len(libraries)
        
        for i, (coord, library) in enumerate(libraries.items()):
            if self._interrupted:
                break
            
            if (i + 1) % 50 == 0 or i == 0:
                self.logger.info(f"Downloading library {i + 1}/{total}: {coord}")
            
            try:
                # Check if already downloaded
                local_path = Path(self.config.local_repository) / library.relative_path
                
                if not overwrite and local_path.exists():
                    # Check for POM file
                    pom_file = local_path / f"{library.artifact_id}-{library.version}.pom"
                    if pom_file.exists():
                        self.logger.debug(f"Library already exists: {coord}")
                        success_count += 1
                        continue
                
                # Download library
                success, downloaded, errors = self.repository_client.download_library(
                    library,
                    Path(self.config.local_repository),
                    overwrite=overwrite
                )
                
                if success:
                    success_count += 1
                    self.downloaded_count += 1
                else:
                    error_count += 1
                    self.logger.warning(f"Failed to download {coord}: {errors}")
                
            except Exception as e:
                error_count += 1
                self.logger.error(f"Error downloading {coord}: {e}")
        
        self.error_count = error_count
        self.logger.info(f"Download complete: {success_count} successful, {error_count} errors")
        
        return success_count
    
    def resolve_dependencies(
        self,
        libraries: Dict[str, LibraryInfo]
    ) -> DependencyTree:
        """
        Resolve dependencies for all libraries.
        
        Args:
            libraries: Libraries to resolve
        
        Returns:
            DependencyTree object
        """
        self.logger.info(f"Resolving dependencies for {len(libraries)} libraries...")
        
        def progress_callback(processed: int, total: int, coord: str):
            if processed % 50 == 0 or processed == total:
                self.logger.info(f"Resolving {processed}/{total}: {coord}")
        
        tree = self.dependency_resolver.build_dependency_tree(
            libraries,
            progress_callback
        )
        
        self.logger.info(f"Dependency resolution complete")
        self.logger.info(f"Total libraries: {tree.total_count}")
        self.logger.info(f"Libraries with issues: {tree.issue_count}")
        
        return tree
    
    def generate_outputs(self, tree: DependencyTree) -> Dict[str, Any]:
        """
        Generate output files.
        
        Args:
            tree: Dependency tree to output
        
        Returns:
            Dictionary with paths to generated files
        """
        self.logger.info("Generating output files...")
        
        def progress_callback(stage: str, current: int, total: int):
            self.logger.info(f"Generating {stage} output ({current}/{total})")
        
        results = self.output_generator.generate_all_outputs(
            tree,
            progress_callback
        )
        
        # Generate and print summary
        summary = self.output_generator.generate_summary(tree)
        self.logger.info("\n" + summary)
        
        return results
    
    def run_local_only(self, validate: bool = False) -> int:
        """
        Run in local-only mode - scan local repository without scraping remote.
        
        Args:
            validate: Whether to validate all local files
        
        Returns:
            Exit code (0 for success, non-zero for errors)
        """
        from .local_repository import LocalRepositoryManager
        
        self.start_time = time.time()
        
        try:
            # Initialize minimal components
            self.logger = init_logger(self.config)
            self.logger.info("Running in LOCAL-ONLY mode - scanning local repository")
            self.logger.info(f"Local repository: {self.config.local_repository}")
            
            # Check if local repository exists
            repo_path = Path(self.config.local_repository)
            if not repo_path.exists():
                self.logger.error(f"Local repository does not exist: {repo_path}")
                self.logger.info("Creating directory structure...")
                repo_path.mkdir(parents=True, exist_ok=True)
                return 0
            
            # Initialize POM parser for validation
            self.pom_parser = POMParser(
                validation_mode=self.config.xml_validation.validation_mode,
                xsd_path=self.config.xml_validation.get_xsd_path(),
                xsd_url=self.config.xml_validation.xsd_url,
                min_jar_size=self.config.min_jar_size_bytes,
                logger=self.logger
            )
            
            # Initialize local repository manager
            local_manager = LocalRepositoryManager(
                repo_path=repo_path,
                pom_parser=self.pom_parser,
                min_jar_size=self.config.min_jar_size_bytes,
                logger=self.logger
            )
            
            # Scan local repository
            self.logger.info("Scanning local repository...")
            libraries: Dict[str, LibraryInfo] = {}
            
            def scan_progress(count: int, coord: str):
                if count % 100 == 0:
                    self.logger.info(f"Scanned {count} libraries...")
            
            for local_lib in local_manager.scan_repository(scan_progress):
                lib_info = LibraryInfo(
                    group_id=local_lib.group_id,
                    artifact_id=local_lib.artifact_id,
                    version=local_lib.version,
                    repository="local",
                    url="",
                    local_path=local_lib.path,
                    has_pom=local_lib.has_pom,
                    has_jar=local_lib.has_jar
                )
                libraries[lib_info.coordinate] = lib_info
            
            self.logger.info(f"Found {len(libraries)} libraries in local repository")
            
            if not libraries:
                self.logger.warning("No libraries found in local repository")
                return 0
            
            # Validate if requested
            if validate:
                self.logger.info("Validating local repository...")
                validation_results = local_manager.validate_repository()
                
                self.logger.info("=" * 60)
                self.logger.info("VALIDATION RESULTS")
                self.logger.info("=" * 60)
                self.logger.info(f"Total libraries: {validation_results['total_libraries']}")
                self.logger.info(f"Libraries with issues: {validation_results['libraries_with_issues']}")
                
                if validation_results['issues_by_type']:
                    self.logger.info("\nIssues by type:")
                    for issue, count in sorted(validation_results['issues_by_type'].items()):
                        self.logger.info(f"  {issue}: {count}")
                else:
                    self.logger.info("\nNo issues found!")
            
            # Initialize minimal dependency resolver (without remote access)
            self.dependency_resolver = DependencyResolver(
                local_repo=repo_path,
                repository_client=None,  # No remote access needed
                pom_parser=self.pom_parser,
                max_depth=self.config.max_dependency_depth,
                include_optional=self.config.include_optional_dependencies,
                logger=self.logger
            )
            
            # Resolve dependencies from local POMs only
            self.logger.info("Resolving dependencies from local POM files...")
            tree = DependencyTree()
            
            for coord, lib_info in libraries.items():
                try:
                    resolved = self.dependency_resolver.resolve_library(lib_info)
                    tree.add_library(resolved)
                    
                    if not resolved.parent or resolved.parent.coordinate not in libraries:
                        tree.root_libraries.append(resolved)
                        
                except Exception as e:
                    self.logger.error(f"Error resolving {coord}: {e}")
            
            self.logger.info(f"Dependency resolution complete: {tree.total_count} libraries")
            
            # Initialize output generator
            self.output_generator = OutputGenerator(
                output_dir=self.config.output.output_directory,
                tree_dir_name=self.config.output.tree_directory_name,
                timestamp_format=self.config.output.timestamp_format,
                logger=self.logger
            )
            
            # Generate outputs
            with Timer(self.logger, "Output generation"):
                output_results = self.generate_outputs(tree)
            
            # Print final summary
            elapsed = time.time() - self.start_time
            self.logger.info("=" * 60)
            self.logger.info("LOCAL-ONLY SCAN COMPLETE")
            self.logger.info("=" * 60)
            self.logger.info(f"Total time: {elapsed:.2f} seconds")
            self.logger.info(f"Libraries found: {len(libraries)}")
            self.logger.info(f"Libraries with issues: {tree.issue_count}")
            
            if output_results.get("text_file"):
                self.logger.info(f"Text output: {output_results['text_file']}")
            if output_results.get("json_file"):
                self.logger.info(f"JSON output: {output_results['json_file']}")
            
            self.logger.info("=" * 60)
            
            return 0
            
        except Exception as e:
            if self.logger:
                self.logger.exception(f"Fatal error: {e}")
            else:
                print(f"Fatal error: {e}", file=sys.stderr)
            return 1
    
    def run(self, dry_run: bool = False, local_only: bool = False, validate_local: bool = False) -> int:
        """
        Run the complete scraping workflow.
        
        Args:
            dry_run: If True, only show what would be done
            local_only: If True, skip remote scraping and only scan local repository
            validate_local: If True, validate all local files (used with local_only)
        
        Returns:
            Exit code (0 for success, non-zero for errors)
        """
        # Handle local-only mode
        if local_only:
            return self.run_local_only(validate=validate_local)
        
        self.start_time = time.time()
        
        try:
            # Initialize
            self.initialize()
            
            if dry_run:
                self.logger.info("DRY RUN MODE - No files will be downloaded")
            
            # Discover libraries
            with Timer(self.logger, "Library discovery"):
                libraries = self.discover_libraries()
            
            if self._interrupted:
                self.logger.warning("Scraping interrupted during discovery")
                return 130  # Standard interrupt exit code
            
            if not libraries:
                self.logger.warning("No libraries discovered")
                return 0
            
            # Update known libraries
            self.known_libraries.update(libraries)
            
            if not dry_run:
                # Download libraries
                with Timer(self.logger, "Library download"):
                    self.download_libraries(libraries)
                
                if self._interrupted:
                    self.logger.warning("Scraping interrupted during download")
                    self._save_known_libraries()
                    return 130
                
                # Save known libraries
                self._save_known_libraries()
            
            # Resolve dependencies
            with Timer(self.logger, "Dependency resolution"):
                tree = self.resolve_dependencies(libraries)
            
            if self._interrupted:
                self.logger.warning("Scraping interrupted during resolution")
                return 130
            
            # Generate outputs
            with Timer(self.logger, "Output generation"):
                output_results = self.generate_outputs(tree)
            
            # Print final summary
            elapsed = time.time() - self.start_time
            self.logger.info("=" * 60)
            self.logger.info("SCRAPING COMPLETE")
            self.logger.info("=" * 60)
            self.logger.info(f"Total time: {elapsed:.2f} seconds")
            self.logger.info(f"Libraries discovered: {len(libraries)}")
            self.logger.info(f"Libraries downloaded: {self.downloaded_count}")
            self.logger.info(f"Errors encountered: {self.error_count}")
            
            if output_results.get("text_file"):
                self.logger.info(f"Text output: {output_results['text_file']}")
            if output_results.get("json_file"):
                self.logger.info(f"JSON output: {output_results['json_file']}")
            
            self.logger.info("=" * 60)
            
            return 0 if self.error_count == 0 else 1
            
        except Exception as e:
            if self.logger:
                self.logger.exception(f"Fatal error: {e}")
            else:
                print(f"Fatal error: {e}", file=sys.stderr)
            return 1
        
        finally:
            # Cleanup
            if self.repository_client:
                self.repository_client.close_all()


def main():
    """Main entry point."""
    # Get script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Parse configuration
    config = get_config(script_dir)
    
    # Create and run application
    app = MavenScraperApp(config)
    
    # Get mode flags from sys.argv (not passed to config)
    dry_run = '--dry-run' in sys.argv
    local_only = '--local-only' in sys.argv
    validate_local = '--validate-local' in sys.argv
    
    # Run the application
    exit_code = app.run(
        dry_run=dry_run,
        local_only=local_only,
        validate_local=validate_local
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()