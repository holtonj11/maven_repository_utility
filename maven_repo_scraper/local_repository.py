"""
Local repository manager for Maven Repository Scraper.
Handles local repository scanning, maintenance, and validation.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Generator, Any
from dataclasses import dataclass, field
from datetime import datetime

from .logger import MavenScraperLogger, get_logger
from .pom_parser import POMParser, POMInfo, IssueType


@dataclass
class LocalLibrary:
    """
    Represents a library in the local Maven repository.
    
    Attributes:
        group_id: The group ID
        artifact_id: The artifact ID
        version: The version
        path: Local file system path
        has_pom: Whether a POM file exists
        has_jar: Whether a JAR file exists
        pom_valid: Whether the POM is valid
        jar_valid: Whether the JAR is valid
        issues: List of issues detected
        last_modified: Last modification time
    """
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    path: str = ""
    has_pom: bool = False
    has_jar: bool = False
    pom_valid: bool = False
    jar_valid: bool = False
    issues: List[str] = field(default_factory=list)
    last_modified: Optional[datetime] = None
    
    @property
    def coordinate(self) -> str:
        """Get the Maven coordinate string."""
        return f"{self.group_id}:{self.artifact_id}:{self.version}"
    
    @property
    def relative_path(self) -> str:
        """Get the relative path within the repository."""
        group_path = self.group_id.replace('.', '/')
        return f"{group_path}/{self.artifact_id}/{self.version}"
    
    @classmethod
    def from_path(cls, path: Path) -> 'LocalLibrary':
        """
        Create a LocalLibrary from a file system path.
        
        Args:
            path: Path to the library directory
        
        Returns:
            LocalLibrary object
        """
        # Parse path components
        parts = path.parts
        
        # Find the version directory (should be last)
        if len(parts) < 3:
            return cls(path=str(path))
        
        version = parts[-1]
        artifact_id = parts[-2]
        
        # Everything before artifact_id is the group path
        group_parts = parts[:-2]
        # Find where the group path starts (after .m2/repository)
        group_start = 0
        for i, part in enumerate(group_parts):
            if part == 'repository':
                group_start = i + 1
                break
        
        group_id = '.'.join(group_parts[group_start:])
        
        return cls(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            path=str(path)
        )


class LocalRepositoryManager:
    """
    Manages the local Maven repository.
    
    Features:
    - Scan local repository for libraries
    - Validate library files
    - Detect and report issues
    - Clean up invalid files
    - Generate reports
    """
    
    def __init__(
        self,
        repo_path: Path,
        pom_parser: POMParser,
        min_jar_size: int = 5120,
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the local repository manager.
        
        Args:
            repo_path: Path to local Maven repository
            pom_parser: POM parser instance
            min_jar_size: Minimum valid JAR size in bytes
            logger: Logger instance
        """
        self.repo_path = Path(repo_path)
        self.pom_parser = pom_parser
        self.min_jar_size = min_jar_size
        self.logger = logger or get_logger()
    
    def scan_repository(
        self,
        progress_callback=None
    ) -> Generator[LocalLibrary, None, None]:
        """
        Scan the local repository for libraries.
        
        Args:
            progress_callback: Progress callback function
        
        Yields:
            LocalLibrary objects for each library found
        """
        self.logger.info(f"Scanning local repository: {self.repo_path}")
        
        if not self.repo_path.exists():
            self.logger.warning(f"Local repository does not exist: {self.repo_path}")
            return
        
        count = 0
        
        # Walk the directory tree
        for root, dirs, files in os.walk(self.repo_path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            # Check if this looks like a version directory
            if self._is_version_directory(files):
                lib_path = Path(root)
                lib = self._create_local_library(lib_path, files)
                
                count += 1
                if progress_callback and count % 100 == 0:
                    progress_callback(count, lib.coordinate)
                
                yield lib
        
        self.logger.info(f"Scan complete: {count} libraries found")
    
    def _is_version_directory(self, files: List[str]) -> bool:
        """
        Check if the current directory looks like a Maven version directory.
        
        Args:
            files: List of files in the directory
        
        Returns:
            True if this looks like a version directory
        """
        # Check for typical Maven files
        for f in files:
            if f.endswith('.pom') or f.endswith('.jar'):
                return True
        
        # Check for metadata files
        if 'maven-metadata.xml' in files:
            return True
        
        return False
    
    def _create_local_library(
        self,
        lib_path: Path,
        files: List[str]
    ) -> LocalLibrary:
        """
        Create a LocalLibrary object from a directory.
        
        Args:
            lib_path: Path to the library directory
            files: List of files in the directory
        
        Returns:
            LocalLibrary object
        """
        lib = LocalLibrary.from_path(lib_path)
        
        # Find POM and JAR files
        pom_files = [f for f in files if f.endswith('.pom')]
        jar_files = [f for f in files if f.endswith('.jar') and not f.endswith('-sources.jar') and not f.endswith('-javadoc.jar')]
        
        lib.has_pom = len(pom_files) > 0
        lib.has_jar = len(jar_files) > 0
        
        # Check for missing files
        if not lib.has_pom:
            if not lib.has_jar:
                lib.issues.append(IssueType.JAR_AND_POM_MISSING)
            else:
                lib.issues.append(IssueType.POM_MISSING)
        elif not lib.has_jar:
            lib.issues.append(IssueType.JAR_MISSING)
        
        # Validate POM file
        if lib.has_pom and pom_files:
            pom_file = lib_path / pom_files[0]
            pom_valid, pom_issues = self._validate_pom_file(pom_file)
            lib.pom_valid = pom_valid
            lib.issues.extend(pom_issues)
        
        # Validate JAR file
        if lib.has_jar and jar_files:
            jar_file = lib_path / jar_files[0]
            jar_valid, jar_issues = self._validate_jar_file(jar_file)
            lib.jar_valid = jar_valid
            lib.issues.extend(jar_issues)
        
        # Get last modified time
        try:
            lib.last_modified = datetime.fromtimestamp(lib_path.stat().st_mtime)
        except Exception:
            pass
        
        return lib
    
    def _validate_pom_file(self, pom_file: Path) -> Tuple[bool, List[str]]:
        """
        Validate a POM file.
        
        Args:
            pom_file: Path to the POM file
        
        Returns:
            Tuple of (is_valid, issues_list)
        """
        issues = []
        
        try:
            content = pom_file.read_text(encoding='utf-8', errors='ignore')
            
            # Check for HTML content
            first_line = content.strip().split('\n')[0].strip().lower()
            if first_line.startswith('<html') or first_line.startswith('<!doctype html'):
                issues.append(IssueType.HTML_ONLY_CONTENT)
                return False, issues
            
            # Parse POM
            pom_info, parse_issues = self.pom_parser.parse_pom(content, str(pom_file))
            issues.extend(parse_issues)
            
            # Check for required fields
            if pom_info and not parse_issues:
                if not pom_info.group_id or not pom_info.artifact_id or not pom_info.version:
                    issues.append(IssueType.POM_NOT_VALID_MAVEN)
                    return False, issues
            
            return len(issues) == 0, issues
            
        except Exception as e:
            self.logger.debug(f"Error validating POM {pom_file}: {e}")
            issues.append(IssueType.POM_MISSING)
            return False, issues
    
    def _validate_jar_file(self, jar_file: Path) -> Tuple[bool, List[str]]:
        """
        Validate a JAR file.
        
        Args:
            jar_file: Path to the JAR file
        
        Returns:
            Tuple of (is_valid, issues_list)
        """
        issues = []
        
        try:
            size = jar_file.stat().st_size
            
            if size < self.min_jar_size:
                issues.append(IssueType.JAR_INVALID)
                return False, issues
            
            # Could add more validation here (e.g., checking ZIP structure)
            
            return True, issues
            
        except Exception as e:
            self.logger.debug(f"Error validating JAR {jar_file}: {e}")
            issues.append(IssueType.JAR_INVALID)
            return False, issues
    
    def get_library(self, group_id: str, artifact_id: str, version: str) -> Optional[LocalLibrary]:
        """
        Get a specific library from the local repository.
        
        Args:
            group_id: The group ID
            artifact_id: The artifact ID
            version: The version
        
        Returns:
            LocalLibrary if found, None otherwise
        """
        group_path = group_id.replace('.', '/')
        lib_path = self.repo_path / group_path / artifact_id / version
        
        if not lib_path.exists():
            return None
        
        files = [f.name for f in lib_path.iterdir() if f.is_file()]
        return self._create_local_library(lib_path, files)
    
    def get_all_versions(self, group_id: str, artifact_id: str) -> List[str]:
        """
        Get all versions of a library in the local repository.
        
        Args:
            group_id: The group ID
            artifact_id: The artifact ID
        
        Returns:
            List of version strings
        """
        group_path = group_id.replace('.', '/')
        artifact_path = self.repo_path / group_path / artifact_id
        
        if not artifact_path.exists():
            return []
        
        versions = []
        for version_dir in artifact_path.iterdir():
            if version_dir.is_dir() and not version_dir.name.startswith('.'):
                versions.append(version_dir.name)
        
        return sorted(versions)
    
    def validate_repository(self) -> Dict[str, Any]:
        """
        Validate the entire local repository.
        
        Returns:
            Dictionary with validation results
        """
        self.logger.info("Validating local repository...")
        
        results = {
            'total_libraries': 0,
            'libraries_with_issues': 0,
            'issues_by_type': {},
            'libraries_by_issue': {}
        }
        
        issues_by_type: Dict[str, int] = {}
        libraries_by_issue: Dict[str, List[str]] = {}
        
        for lib in self.scan_repository():
            results['total_libraries'] += 1
            
            if lib.issues:
                results['libraries_with_issues'] += 1
                
                for issue in lib.issues:
                    issues_by_type[issue] = issues_by_type.get(issue, 0) + 1
                    
                    if issue not in libraries_by_issue:
                        libraries_by_issue[issue] = []
                    libraries_by_issue[issue].append(lib.coordinate)
        
        results['issues_by_type'] = issues_by_type
        results['libraries_by_issue'] = libraries_by_issue
        
        self.logger.info(f"Validation complete: {results['libraries_with_issues']}/{results['total_libraries']} libraries with issues")
        
        return results
    
    def cleanup_invalid_files(
        self,
        issues: List[str] = None,
        dry_run: bool = True
    ) -> Dict[str, List[str]]:
        """
        Clean up files with specified issues.
        
        Args:
            issues: List of issues to clean up (default: all)
            dry_run: If True, only report what would be deleted
        
        Returns:
            Dictionary with deleted/reported files
        """
        if issues is None:
            issues = [IssueType.JAR_INVALID, IssueType.HTML_ONLY_CONTENT]
        
        self.logger.info(f"Cleaning up files with issues: {issues}")
        
        deleted = {issue: [] for issue in issues}
        
        for lib in self.scan_repository():
            for issue in lib.issues:
                if issue in issues:
                    lib_path = Path(lib.path)
                    
                    if dry_run:
                        self.logger.info(f"Would delete: {lib_path}")
                    else:
                        try:
                            # Delete files in the library directory
                            for f in lib_path.iterdir():
                                f.unlink()
                                self.logger.debug(f"Deleted: {f}")
                            lib_path.rmdir()
                            self.logger.info(f"Deleted: {lib_path}")
                        except Exception as e:
                            self.logger.error(f"Error deleting {lib_path}: {e}")
                    
                    deleted[issue].append(lib.coordinate)
        
        return deleted
    
    def get_repository_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the local repository.
        
        Returns:
            Dictionary with repository statistics
        """
        self.logger.info("Calculating repository statistics...")
        
        stats = {
            'total_size_bytes': 0,
            'total_files': 0,
            'total_libraries': 0,
            'total_groups': set(),
            'total_artifacts': set(),
            'file_types': {},
            'oldest_file': None,
            'newest_file': None
        }
        
        oldest_time = None
        newest_time = None
        
        for lib in self.scan_repository():
            stats['total_libraries'] += 1
            stats['total_groups'].add(lib.group_id)
            stats['total_artifacts'].add(f"{lib.group_id}:{lib.artifact_id}")
            
            lib_path = Path(lib.path)
            
            for f in lib_path.iterdir():
                if f.is_file():
                    stats['total_files'] += 1
                    
                    try:
                        size = f.stat().st_size
                        stats['total_size_bytes'] += size
                        
                        mtime = f.stat().st_mtime
                        if oldest_time is None or mtime < oldest_time:
                            oldest_time = mtime
                            stats['oldest_file'] = f.name
                        if newest_time is None or mtime > newest_time:
                            newest_time = mtime
                            stats['newest_file'] = f.name
                        
                        # Track file types
                        ext = f.suffix.lower()
                        stats['file_types'][ext] = stats['file_types'].get(ext, 0) + 1
                        
                    except Exception:
                        pass
        
        stats['total_groups'] = len(stats['total_groups'])
        stats['total_artifacts'] = len(stats['total_artifacts'])
        stats['total_size_mb'] = stats['total_size_bytes'] / (1024 * 1024)
        stats['total_size_gb'] = stats['total_size_bytes'] / (1024 * 1024 * 1024)
        
        return stats


if __name__ == "__main__":
    # Test the local repository manager
    from config import ScraperConfig
    from logger import setup_logger
    
    config = ScraperConfig()
    logger = setup_logger(config)
    
    parser = POMParser(validation_mode="simple", logger=logger)
    
    manager = LocalRepositoryManager(
        repo_path=config.local_repository,
        pom_parser=parser,
        logger=logger
    )
    
    # Get stats
    stats = manager.get_repository_stats()
    print(f"Repository stats: {stats}")