"""
Dependency resolver for Maven Repository Scraper.
Handles resolving parent and transitive dependencies following Maven's rules.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

from .logger import MavenScraperLogger, get_logger
from .pom_parser import POMParser, POMInfo, Dependency, IssueType
from .repository_client import LibraryInfo, MultiRepositoryClient


@dataclass
class ResolvedLibrary:
    """
    Represents a fully resolved library with its dependency tree.
    
    Attributes:
        library_info: Basic library information
        pom_info: Parsed POM information
        issues: List of issues detected
        parent: Parent library (if any)
        dependencies: List of resolved dependencies
        transitive_dependencies: List of transitive dependencies
        depth: Depth in the dependency tree
        error: Error message if resolution failed
    """
    library_info: LibraryInfo = None
    pom_info: POMInfo = None
    issues: List[str] = field(default_factory=list)
    parent: Optional['ResolvedLibrary'] = None
    dependencies: List['ResolvedLibrary'] = field(default_factory=list)
    transitive_dependencies: List['ResolvedLibrary'] = field(default_factory=list)
    depth: int = 0
    error: Optional[str] = None
    
    @property
    def coordinate(self) -> str:
        """Get the Maven coordinate string."""
        if self.library_info:
            return self.library_info.coordinate
        if self.pom_info:
            return self.pom_info.coordinate
        return ""
    
    @property
    def group_id(self) -> str:
        """Get the group ID."""
        if self.pom_info:
            return self.pom_info.group_id
        if self.library_info:
            return self.library_info.group_id
        return ""
    
    @property
    def artifact_id(self) -> str:
        """Get the artifact ID."""
        if self.pom_info:
            return self.pom_info.artifact_id
        if self.library_info:
            return self.library_info.artifact_id
        return ""
    
    @property
    def version(self) -> str:
        """Get the version."""
        if self.pom_info:
            return self.pom_info.version
        if self.library_info:
            return self.library_info.version
        return ""
    
    @property
    def local_path(self) -> str:
        """Get the local path."""
        if self.library_info:
            return self.library_info.local_path
        return ""
    
    def get_parent_path(self) -> str:
        """
        Get the full parent path from root to this library.
        
        Returns:
            String representation of the path like "parent -> child -> this"
        """
        path = []
        current = self
        while current is not None:
            path.insert(0, current.coordinate)
            current = current.parent
        
        return " -> ".join(path)
    
    def get_all_issues(self) -> List[str]:
        """
        Get all issues including those from dependencies.
        
        Returns:
            List of all issues in this library and its dependencies
        """
        issues = list(self.issues)
        for dep in self.dependencies:
            issues.extend(dep.get_all_issues())
        for dep in self.transitive_dependencies:
            issues.extend(dep.get_all_issues())
        return issues


@dataclass
class DependencyTree:
    """
    Represents the complete dependency tree for the repository.
    
    Attributes:
        libraries: Dictionary of resolved libraries by coordinate
        root_libraries: Libraries without parents (roots of the tree)
        total_count: Total number of libraries
        issue_count: Number of libraries with issues
    """
    libraries: Dict[str, ResolvedLibrary] = field(default_factory=dict)
    root_libraries: List[ResolvedLibrary] = field(default_factory=list)
    total_count: int = 0
    issue_count: int = 0
    
    def add_library(self, library: ResolvedLibrary):
        """Add a library to the tree."""
        coord = library.coordinate
        if coord not in self.libraries:
            self.libraries[coord] = library
            self.total_count += 1
            if library.issues:
                self.issue_count += 1
    
    def get_library(self, coordinate: str) -> Optional[ResolvedLibrary]:
        """Get a library by its coordinate."""
        return self.libraries.get(coordinate)
    
    def get_libraries_by_issue(self, issue: str) -> List[ResolvedLibrary]:
        """
        Get all libraries that have a specific issue.
        
        Args:
            issue: The issue type to filter by
        
        Returns:
            List of libraries with that issue
        """
        return [lib for lib in self.libraries.values() if issue in lib.issues]
    
    def get_all_issues(self) -> Dict[str, List[ResolvedLibrary]]:
        """
        Get all issues grouped by issue type.
        
        Returns:
            Dictionary mapping issue types to lists of libraries
        """
        issues_map: Dict[str, List[ResolvedLibrary]] = defaultdict(list)
        
        for lib in self.libraries.values():
            for issue in lib.issues:
                issues_map[issue].append(lib)
        
        return dict(issues_map)


class DependencyResolver:
    """
    Resolves Maven dependencies following Maven's rules.
    
    Handles:
    - Parent POM resolution
    - Transitive dependency resolution
    - Dependency management
    - Version conflict resolution
    - Scope handling
    """
    
    def __init__(
        self,
        local_repo: Path,
        repository_client: MultiRepositoryClient,
        pom_parser: POMParser,
        max_depth: int = 100,
        include_optional: bool = True,
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the dependency resolver.
        
        Args:
            local_repo: Path to local Maven repository
            repository_client: Client for accessing remote repositories
            pom_parser: Parser for POM files
            max_depth: Maximum dependency resolution depth
            include_optional: Whether to include optional dependencies
            logger: Logger instance
        """
        self.local_repo = Path(local_repo)
        self.repository_client = repository_client
        self.pom_parser = pom_parser
        self.max_depth = max_depth
        self.include_optional = include_optional
        self.logger = logger or get_logger()
        
        # Cache for resolved POMs
        self._pom_cache: Dict[str, Tuple[POMInfo, List[str]]] = {}
        
        # Track resolved coordinates to prevent infinite recursion
        self._resolving: Set[str] = set()
    
    def resolve_library(
        self,
        library: LibraryInfo,
        parent: ResolvedLibrary = None,
        depth: int = 0
    ) -> ResolvedLibrary:
        """
        Resolve a single library and its dependencies.
        
        Args:
            library: The library to resolve
            parent: Parent library (if this is a dependency)
            depth: Current depth in the dependency tree
        
        Returns:
            ResolvedLibrary with full dependency information
        """
        resolved = ResolvedLibrary(
            library_info=library,
            parent=parent,
            depth=depth
        )
        
        coord = library.coordinate
        
        # Check for circular dependencies
        if coord in self._resolving:
            self.logger.warning(f"Circular dependency detected for {coord}")
            resolved.issues.append("Circular dependency detected")
            return resolved
        
        # Check depth limit
        if depth > self.max_depth:
            self.logger.warning(f"Max depth ({self.max_depth}) exceeded for {coord}")
            resolved.issues.append(f"Max dependency depth ({self.max_depth}) exceeded")
            return resolved
        
        self._resolving.add(coord)
        
        try:
            # Check local files
            local_lib_path = self.local_repo / library.relative_path
            resolved.library_info.local_path = str(local_lib_path)
            
            # Parse POM file
            pom_info, pom_issues = self._parse_pom(library)
            resolved.pom_info = pom_info
            resolved.issues.extend(pom_issues)
            
            if pom_issues:
                # Attempt to re-download problematic POM
                self._attempt_pom_redownload(library, pom_issues)
                pom_info, pom_issues = self._parse_pom(library)
                resolved.pom_info = pom_info
                # Only keep issues that persisted after redownload
                resolved.issues = [i for i in resolved.issues if i not in pom_issues]
                resolved.issues.extend(pom_issues)
            
            if pom_info and not pom_issues:
                # Resolve parent POM
                if pom_info.parent:
                    parent_lib = self._resolve_parent(pom_info.parent, resolved, depth)
                    if parent_lib:
                        resolved.parent = parent_lib
                
                # Resolve direct dependencies
                for dep in pom_info.dependencies:
                    if not self.include_optional and dep.optional:
                        continue
                    
                    # Skip certain scopes
                    if dep.scope in ('test', 'system'):
                        continue
                    
                    dep_lib = self._resolve_dependency(dep, resolved, depth)
                    if dep_lib:
                        resolved.dependencies.append(dep_lib)
                
                # Resolve transitive dependencies
                for dep in resolved.dependencies:
                    self._resolve_transitive_dependencies(dep, resolved)
            
        except Exception as e:
            self.logger.exception(f"Error resolving library {coord}: {e}")
            resolved.error = str(e)
        finally:
            self._resolving.discard(coord)
        
        return resolved
    
    def _parse_pom(self, library: LibraryInfo) -> Tuple[POMInfo, List[str]]:
        """
        Parse the POM file for a library.
        
        Args:
            library: The library to parse
        
        Returns:
            Tuple of (POMInfo, issues list)
        """
        coord = library.coordinate
        
        # Check cache
        if coord in self._pom_cache:
            return self._pom_cache[coord]
        
        local_lib_path = self.local_repo / library.relative_path
        
        # Try to read local POM
        pom_content = None
        pom_file = local_lib_path / f"{library.artifact_id}-{library.version}.pom"
        
        if pom_file.exists():
            try:
                pom_content = pom_file.read_text(encoding='utf-8', errors='ignore')
            except Exception as e:
                self.logger.warning(f"Error reading local POM {pom_file}: {e}")
        
        # If not found locally, try remote
        if not pom_content:
            pom_filename = f"{library.artifact_id}-{library.version}.pom"
            pom_content = self.repository_client.get_file_content(library, pom_filename)
            
            if pom_content:
                # Save to local repository
                local_lib_path.mkdir(parents=True, exist_ok=True)
                pom_file.write_text(pom_content, encoding='utf-8')
        
        # Parse POM
        if pom_content:
            pom_info, issues = self.pom_parser.parse_pom(pom_content, str(pom_file))
        else:
            pom_info = POMInfo()
            issues = [IssueType.POM_MISSING]
        
        # Cache result
        self._pom_cache[coord] = (pom_info, issues)
        
        return pom_info, issues
    
    def _attempt_pom_redownload(self, library: LibraryInfo, issues: List[str]) -> bool:
        """
        Attempt to re-download a problematic POM file.
        
        Args:
            library: The library with issues
            issues: List of issues detected
        
        Returns:
            True if redownload was attempted, False otherwise
        """
        # Only redownload for certain issue types
        redownload_issues = {
            IssueType.POM_MISSING,
            IssueType.HTML_ONLY_CONTENT,
            IssueType.FAILED_SIMPLE_XML,
            IssueType.FAILED_XSD_VALIDATION
        }
        
        if not any(issue in redownload_issues for issue in issues):
            return False
        
        self.logger.info(f"Attempting to re-download POM for {library.coordinate}")
        
        local_lib_path = self.local_repo / library.relative_path
        pom_filename = f"{library.artifact_id}-{library.version}.pom"
        
        # Download from repository
        success, downloaded, errors = self.repository_client.download_library(
            library,
            self.local_repo,
            files=[pom_filename],
            overwrite=True
        )
        
        if success:
            # Clear cache for this library
            if library.coordinate in self._pom_cache:
                del self._pom_cache[library.coordinate]
            self.logger.info(f"Successfully re-downloaded POM for {library.coordinate}")
        
        return success
    
    def _resolve_parent(
        self,
        parent_dep: Dependency,
        child: ResolvedLibrary,
        depth: int
    ) -> Optional[ResolvedLibrary]:
        """
        Resolve a parent POM.
        
        Args:
            parent_dep: The parent dependency specification
            child: The child library
            depth: Current depth
        
        Returns:
            ResolvedLibrary for the parent, or None if resolution failed
        """
        if not parent_dep.group_id or not parent_dep.artifact_id or not parent_dep.version:
            self.logger.warning(
                f"Incomplete parent specification in {child.coordinate}: "
                f"{parent_dep.group_id}:{parent_dep.artifact_id}:{parent_dep.version}"
            )
            return None
        
        parent_lib = LibraryInfo(
            group_id=parent_dep.group_id,
            artifact_id=parent_dep.artifact_id,
            version=parent_dep.version,
            repository=child.library_info.repository if child.library_info else ""
        )
        
        return self.resolve_library(parent_lib, child, depth + 1)
    
    def _resolve_dependency(
        self,
        dep: Dependency,
        parent: ResolvedLibrary,
        depth: int
    ) -> Optional[ResolvedLibrary]:
        """
        Resolve a single dependency.
        
        Args:
            dep: The dependency specification
            parent: The parent library
            depth: Current depth
        
        Returns:
            ResolvedLibrary for the dependency, or None if resolution failed
        """
        # Handle missing version
        version = dep.version
        if not version:
            # Try to find version in dependency management
            if parent.pom_info:
                for dm_dep in parent.pom_info.dependency_management:
                    if dm_dep.group_id == dep.group_id and dm_dep.artifact_id == dep.artifact_id:
                        version = dm_dep.version
                        break
        
        if not version:
            self.logger.warning(
                f"Missing version for dependency {dep.group_id}:{dep.artifact_id} "
                f"in {parent.coordinate}"
            )
            return None
        
        dep_lib = LibraryInfo(
            group_id=dep.group_id,
            artifact_id=dep.artifact_id,
            version=version,
            repository=parent.library_info.repository if parent.library_info else ""
        )
        
        return self.resolve_library(dep_lib, parent, depth + 1)
    
    def _resolve_transitive_dependencies(
        self,
        dependency: ResolvedLibrary,
        root: ResolvedLibrary
    ):
        """
        Resolve transitive dependencies for a dependency.
        
        Maven's transitive dependency rules:
        1. Dependencies with compile/runtime scope are included
        2. Dependencies with test scope are excluded
        3. Dependencies with provided scope are excluded
        4. Optional dependencies may be excluded
        5. Exclusions are applied
        
        Args:
            dependency: The dependency to resolve transitive deps for
            root: The root library
        """
        if not dependency.pom_info:
            return
        
        for dep in dependency.pom_info.dependencies:
            # Apply scope rules
            if dep.scope in ('test', 'provided'):
                continue
            
            # Apply optional rule
            if dep.optional and not self.include_optional:
                continue
            
            # Check for exclusions
            coord = f"{dep.group_id}:{dep.artifact_id}"
            
            # Build exclusions from entire dependency chain
            excluded = self._get_exclusions(root)
            if coord in excluded:
                self.logger.debug(f"Excluding {coord} due to exclusion")
                continue
            
            # Resolve the transitive dependency
            trans_dep = self._resolve_dependency(dep, dependency, dependency.depth + 1)
            if trans_dep:
                dependency.transitive_dependencies.append(trans_dep)
    
    def _get_exclusions(self, library: ResolvedLibrary) -> Set[str]:
        """
        Get all exclusions from a library and its dependencies.
        
        Args:
            library: The library to get exclusions from
        
        Returns:
            Set of excluded coordinates
        """
        exclusions = set()
        
        def collect_exclusions(lib: ResolvedLibrary):
            if lib.pom_info:
                for dep in lib.pom_info.dependencies:
                    for excl_group, excl_artifact in dep.exclusions:
                        exclusions.add(f"{excl_group}:{excl_artifact}")
            
            for dep in lib.dependencies:
                collect_exclusions(dep)
        
        collect_exclusions(library)
        return exclusions
    
    def build_dependency_tree(
        self,
        libraries: Dict[str, LibraryInfo],
        progress_callback=None
    ) -> DependencyTree:
        """
        Build the complete dependency tree for all libraries.
        
        Args:
            libraries: Dictionary of libraries to resolve
            progress_callback: Progress callback
        
        Returns:
            DependencyTree object
        """
        tree = DependencyTree()
        self._resolving.clear()
        self._pom_cache.clear()
        
        total = len(libraries)
        processed = 0
        
        for coord, library in libraries.items():
            try:
                resolved = self.resolve_library(library)
                tree.add_library(resolved)
                
                # Track root libraries (those without parents in our set)
                if not resolved.parent or resolved.parent.coordinate not in libraries:
                    tree.root_libraries.append(resolved)
                
            except Exception as e:
                self.logger.error(f"Error resolving {coord}: {e}")
                resolved = ResolvedLibrary(
                    library_info=library,
                    error=str(e)
                )
                tree.add_library(resolved)
            
            processed += 1
            if progress_callback:
                progress_callback(processed, total, coord)
        
        return tree


if __name__ == "__main__":
    # Test the dependency resolver
    print("Dependency resolver module loaded successfully")