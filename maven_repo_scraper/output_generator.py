"""
Output generator for Maven Repository Scraper.
Generates dependency tree output in text and JSON formats.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from collections import defaultdict

from .logger import MavenScraperLogger, get_logger
from .dependency_resolver import DependencyTree, ResolvedLibrary


class DependencyTreeWriter:
    """
    Writes dependency trees to various output formats.
    """
    
    def __init__(
        self,
        output_dir: Path,
        timestamp_format: str = "%Y-%m-%dT%H:%M:%S.%f",
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the output writer.
        
        Args:
            output_dir: Directory to write output files
            timestamp_format: Format for timestamps
            logger: Logger instance
        """
        self.output_dir = Path(output_dir)
        self.timestamp_format = timestamp_format
        self.logger = logger or get_logger()
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_timestamp(self) -> str:
        """Get current timestamp string."""
        return datetime.now().strftime(self.timestamp_format)
    
    def _format_tree_text(
        self,
        library: ResolvedLibrary,
        prefix: str = "",
        is_last: bool = True,
        visited: Set[str] = None
    ) -> List[str]:
        """
        Format a library and its dependencies as text tree.
        
        Args:
            library: The library to format
            prefix: Current line prefix
            is_last: Whether this is the last sibling
            visited: Set of visited coordinates (for cycle detection)
        
        Returns:
            List of text lines
        """
        if visited is None:
            visited = set()
        
        lines = []
        coord = library.coordinate
        
        # Build the tree structure
        connector = "|__ " if not is_last else "|__ "
        new_prefix = prefix + ("    " if is_last else "|   ")
        
        # Format the library line
        issues_str = ""
        if library.issues:
            issues_str = f" [ISSUES: {', '.join(library.issues)}]"
        
        error_str = ""
        if library.error:
            error_str = f" [ERROR: {library.error}]"
        
        line = f"{prefix}{connector}{coord}{issues_str}{error_str}"
        lines.append(line)
        
        # Check for cycles
        if coord in visited:
            lines.append(f"{new_prefix}(cycle detected)")
            return lines
        
        visited = visited | {coord}
        
        # Format dependencies
        all_deps = library.dependencies + library.transitive_dependencies
        
        for i, dep in enumerate(all_deps):
            is_last_dep = (i == len(all_deps) - 1)
            dep_lines = self._format_tree_text(dep, new_prefix, is_last_dep, visited)
            lines.extend(dep_lines)
        
        return lines
    
    def write_text_tree(
        self,
        tree: DependencyTree,
        filename: str = None
    ) -> Path:
        """
        Write the dependency tree as a text file.
        
        Args:
            tree: The dependency tree to write
            filename: Optional filename (default: auto-generated with timestamp)
        
        Returns:
            Path to the written file
        """
        timestamp = self._get_timestamp()
        if filename is None:
            filename = f"dependencyTree_{timestamp}.txt"
        
        filepath = self.output_dir / filename
        
        lines = [
            "=" * 80,
            "MAVEN DEPENDENCY TREE",
            f"Generated: {datetime.now().isoformat()}",
            f"Total Libraries: {tree.total_count}",
            f"Libraries with Issues: {tree.issue_count}",
            "=" * 80,
            ""
        ]
        
        # Track visited to avoid duplicates
        visited: Set[str] = set()
        
        # Write each root library and its tree
        for library in tree.root_libraries:
            if library.coordinate not in visited:
                tree_lines = self._format_tree_text(library, "", True, visited)
                lines.extend(tree_lines)
                lines.append("")
        
        # Add summary section
        lines.extend([
            "",
            "=" * 80,
            "SUMMARY",
            "=" * 80,
            f"Total unique libraries: {len(tree.libraries)}",
            f"Root libraries: {len(tree.root_libraries)}",
            f"Libraries with issues: {tree.issue_count}",
            ""
        ])
        
        # Add issues summary
        issues_map = tree.get_all_issues()
        if issues_map:
            lines.append("Issues by type:")
            for issue, libs in sorted(issues_map.items()):
                lines.append(f"  - {issue}: {len(libs)} libraries")
            lines.append("")
        
        # Write file
        filepath.write_text("\n".join(lines), encoding='utf-8')
        self.logger.info(f"Text dependency tree written to {filepath}")
        
        return filepath
    
    def _library_to_json(
        self,
        library: ResolvedLibrary,
        visited: Set[str] = None
    ) -> Dict[str, Any]:
        """
        Convert a ResolvedLibrary to JSON-serializable dictionary.
        
        Args:
            library: The library to convert
            visited: Set of visited coordinates (for cycle detection)
        
        Returns:
            Dictionary representation
        """
        if visited is None:
            visited = set()
        
        coord = library.coordinate
        
        # Check for cycles
        if coord in visited:
            return {
                "library": coord,
                "cycle": True
            }
        
        visited = visited | {coord}
        
        # Build transitive libraries list
        transitive = []
        for dep in library.transitive_dependencies:
            transitive.append(self._library_to_json(dep, visited))
        
        # Build dependencies list
        dependencies = []
        for dep in library.dependencies:
            dependencies.append(self._library_to_json(dep, visited))
        
        return {
            "library": coord,
            "version": library.version,
            "filePath": library.local_path,
            "issues": library.issues,
            "error": library.error,
            "parentLibrary": library.parent.coordinate if library.parent else None,
            "transitiveLibraries": transitive,
            "parentLibraryPath": library.get_parent_path(),
            "dependencies": dependencies
        }
    
    def write_json_tree(
        self,
        tree: DependencyTree,
        filename: str = None
    ) -> Path:
        """
        Write the dependency tree as a JSON file.
        
        Args:
            tree: The dependency tree to write
            filename: Optional filename (default: auto-generated with timestamp)
        
        Returns:
            Path to the written file
        """
        timestamp = self._get_timestamp()
        if filename is None:
            filename = f"dependencyTree_{timestamp}.json"
        
        filepath = self.output_dir / filename
        
        # Build JSON structure
        json_data = {
            "metadata": {
                "generated": datetime.now().isoformat(),
                "totalLibraries": tree.total_count,
                "librariesWithIssues": tree.issue_count
            },
            "rootLibraries": [],
            "allLibraries": []
        }
        
        # Track visited
        visited: Set[str] = set()
        
        # Process root libraries
        for library in tree.root_libraries:
            lib_json = self._library_to_json(library, visited)
            json_data["rootLibraries"].append(lib_json)
        
        # Process all libraries (flat list)
        for coord, library in sorted(tree.libraries.items()):
            lib_json = {
                "library": coord,
                "version": library.version,
                "filePath": library.local_path,
                "issues": library.issues,
                "error": library.error,
                "parentLibrary": library.parent.coordinate if library.parent else None,
                "parentLibraryPath": library.get_parent_path(),
                "dependencyCount": len(library.dependencies) + len(library.transitive_dependencies)
            }
            json_data["allLibraries"].append(lib_json)
        
        # Write file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"JSON dependency tree written to {filepath}")
        
        return filepath
    
    def write_issue_files(
        self,
        tree: DependencyTree,
        timestamp: str = None
    ) -> Dict[str, Path]:
        """
        Write separate files for each issue type.
        
        Args:
            tree: The dependency tree
            timestamp: Optional timestamp string
        
        Returns:
            Dictionary mapping issue types to file paths
        """
        if timestamp is None:
            timestamp = self._get_timestamp()
        
        issues_map = tree.get_all_issues()
        files = {}
        
        for issue, libraries in issues_map.items():
            # Create safe filename from issue
            safe_issue = issue.replace(" ", "_").replace("/", "_")
            filename = f"dependencyTree_{safe_issue}_{timestamp}.txt"
            filepath = self.output_dir / filename
            
            lines = [
                "=" * 80,
                f"DEPENDENCY TREE - {issue}",
                f"Generated: {datetime.now().isoformat()}",
                f"Libraries with this issue: {len(libraries)}",
                "=" * 80,
                ""
            ]
            
            visited: Set[str] = set()
            
            for library in libraries:
                if library.coordinate not in visited:
                    tree_lines = self._format_tree_text(library, "", True, visited)
                    lines.extend(tree_lines)
                    lines.append("")
                    lines.append("-" * 40)
                    lines.append("")
            
            filepath.write_text("\n".join(lines), encoding='utf-8')
            files[issue] = filepath
            self.logger.info(f"Issue file written to {filepath}")
        
        return files


class OutputGenerator:
    """
    Main output generator that coordinates all output writing.
    """
    
    def __init__(
        self,
        output_dir: Path,
        tree_dir_name: str = "directoryTree_output",
        timestamp_format: str = "%Y-%m-%dT%H:%M:%S.%f",
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the output generator.
        
        Args:
            output_dir: Base output directory
            tree_dir_name: Name of the dependency tree subdirectory
            timestamp_format: Format for timestamps
            logger: Logger instance
        """
        self.output_dir = Path(output_dir)
        self.tree_dir = self.output_dir / tree_dir_name
        self.timestamp_format = timestamp_format
        self.logger = logger or get_logger()
        
        # Create writer
        self.writer = DependencyTreeWriter(
            self.tree_dir,
            timestamp_format,
            logger
        )
    
    def generate_all_outputs(
        self,
        tree: DependencyTree,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Generate all output files.
        
        Args:
            tree: The dependency tree
            progress_callback: Progress callback
        
        Returns:
            Dictionary with paths to all generated files
        """
        results = {
            "text_file": None,
            "json_file": None,
            "issue_files": {}
        }
        
        # Get timestamp for consistency
        timestamp = datetime.now().strftime(self.timestamp_format)
        
        # Write text tree
        self.logger.info("Generating text dependency tree...")
        results["text_file"] = self.writer.write_text_tree(
            tree,
            f"dependencyTree_{timestamp}.txt"
        )
        
        if progress_callback:
            progress_callback("text", 1, 3)
        
        # Write JSON tree
        self.logger.info("Generating JSON dependency tree...")
        results["json_file"] = self.writer.write_json_tree(
            tree,
            f"dependencyTree_{timestamp}.json"
        )
        
        if progress_callback:
            progress_callback("json", 2, 3)
        
        # Write issue files
        self.logger.info("Generating issue-specific files...")
        results["issue_files"] = self.writer.write_issue_files(tree, timestamp)
        
        if progress_callback:
            progress_callback("issues", 3, 3)
        
        self.logger.info("All output files generated successfully")
        
        return results
    
    def generate_summary(self, tree: DependencyTree) -> str:
        """
        Generate a human-readable summary of the dependency tree.
        
        Args:
            tree: The dependency tree
        
        Returns:
            Summary string
        """
        lines = [
            "DEPENDENCY TREE SUMMARY",
            "=" * 40,
            f"Total libraries: {tree.total_count}",
            f"Libraries with issues: {tree.issue_count}",
            f"Root libraries: {len(tree.root_libraries)}",
            ""
        ]
        
        issues_map = tree.get_all_issues()
        if issues_map:
            lines.append("Issues breakdown:")
            for issue, libs in sorted(issues_map.items(), key=lambda x: -len(x[1])):
                lines.append(f"  {issue}: {len(libs)}")
            lines.append("")
        
        # Top-level dependencies
        if tree.root_libraries:
            lines.append("Sample root libraries:")
            for lib in tree.root_libraries[:10]:
                lines.append(f"  - {lib.coordinate}")
            if len(tree.root_libraries) > 10:
                lines.append(f"  ... and {len(tree.root_libraries) - 10} more")
        
        return "\n".join(lines)


if __name__ == "__main__":
    # Test the output generator
    print("Output generator module loaded successfully")