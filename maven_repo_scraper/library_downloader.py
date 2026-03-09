"""
Library downloader for Maven Repository Scraper.
Downloads specific libraries and their dependencies.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .logger import MavenScraperLogger, get_logger
from .pom_parser import POMParser, POMInfo, Dependency
from .repository_client import LibraryInfo, MultiRepositoryClient


@dataclass
class LibraryCoordinate:
    """
    Represents a Maven library coordinate.
    
    Attributes:
        group_id: The group ID
        artifact_id: The artifact ID
        version: The version (optional, will use latest if not specified)
        classifier: The classifier (optional)
        packaging: The packaging type (jar, pom, war, etc.)
    """
    group_id: str
    artifact_id: str
    version: Optional[str] = None
    classifier: Optional[str] = None
    packaging: str = "jar"
    
    @classmethod
    def parse(cls, coordinate: str) -> 'LibraryCoordinate':
        """
        Parse a Maven coordinate string.
        
        Supports formats:
        - groupId:artifactId
        - groupId:artifactId:version
        - groupId:artifactId:version:classifier
        - groupId:artifactId:packaging:version
        - groupId:artifactId:packaging:version:classifier
        
        Args:
            coordinate: Maven coordinate string
            
        Returns:
            LibraryCoordinate object
        """
        parts = coordinate.strip().split(':')
        
        if len(parts) < 2:
            raise ValueError(f"Invalid coordinate format: {coordinate}. Expected groupId:artifactId[:version]")
        
        group_id = parts[0]
        artifact_id = parts[1]
        version = None
        classifier = None
        packaging = "jar"
        
        if len(parts) >= 3:
            # Check if third part is version or packaging
            third = parts[2]
            if third in ('jar', 'pom', 'war', 'ear', 'aar'):
                packaging = third
                if len(parts) >= 4:
                    version = parts[3]
                if len(parts) >= 5:
                    classifier = parts[4]
            else:
                version = third
                if len(parts) >= 4:
                    # Fourth could be classifier or packaging
                    fourth = parts[3]
                    if fourth in ('jar', 'pom', 'war', 'ear', 'aar'):
                        packaging = fourth
                    else:
                        classifier = fourth
        
        return cls(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            classifier=classifier,
            packaging=packaging
        )
    
    def to_library_info(self, repository: str = "") -> LibraryInfo:
        """Convert to LibraryInfo object."""
        return LibraryInfo(
            group_id=self.group_id,
            artifact_id=self.artifact_id,
            version=self.version or "",
            repository=repository
        )
    
    @property
    def coordinate(self) -> str:
        """Get the full coordinate string."""
        coord = f"{self.group_id}:{self.artifact_id}"
        if self.version:
            coord += f":{self.version}"
        if self.classifier:
            coord += f":{self.classifier}"
        return coord
    
    @property
    def relative_path(self) -> str:
        """Get the relative path in Maven repository."""
        group_path = self.group_id.replace('.', '/')
        if self.version:
            return f"{group_path}/{self.artifact_id}/{self.version}"
        return f"{group_path}/{self.artifact_id}"


class LibraryDownloader:
    """
    Downloads specific Maven libraries and their dependencies.
    """
    
    def __init__(
        self,
        repository_client: MultiRepositoryClient,
        pom_parser: POMParser,
        local_repo: Path,
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the library downloader.
        
        Args:
            repository_client: Client for accessing repositories
            pom_parser: Parser for POM files
            local_repo: Local Maven repository path
            logger: Logger instance
        """
        self.repository_client = repository_client
        self.pom_parser = pom_parser
        self.local_repo = Path(local_repo)
        self.logger = logger or get_logger()
        
        # Track downloaded libraries
        self._downloaded: Set[str] = set()
        self._failed: Set[str] = set()
    
    def download_library(
        self,
        coordinate: LibraryCoordinate,
        download_dependencies: bool = True,
        overwrite: bool = False
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Download a single library.
        
        Args:
            coordinate: The library coordinate
            download_dependencies: Whether to download dependencies
            overwrite: Whether to overwrite existing files
            
        Returns:
            Tuple of (success, downloaded_files, errors)
        """
        # Check if version is specified
        if not coordinate.version:
            # Try to find latest version
            version = self._find_latest_version(coordinate)
            if version:
                coordinate.version = version
                self.logger.info(f"Found latest version: {coordinate.coordinate}")
            else:
                return False, [], [f"Could not determine version for {coordinate.group_id}:{coordinate.artifact_id}"]
        
        lib_info = coordinate.to_library_info()
        coord_str = lib_info.coordinate
        
        # Check if already downloaded
        if coord_str in self._downloaded and not overwrite:
            self.logger.debug(f"Already downloaded: {coord_str}")
            return True, [], []
        
        self.logger.info(f"Downloading library: {coord_str}")
        
        # Determine files to download
        files_to_download = self._get_files_to_download(coordinate)
        
        downloaded = []
        errors = []
        
        # Download from repositories
        for repo_name, client in self.repository_client.clients.items():
            lib_info.repository = repo_name
            
            success, downloaded_files, download_errors = client.download_library(
                lib_info,
                self.local_repo,
                files=files_to_download,
                overwrite=overwrite
            )
            
            if success:
                downloaded.extend(downloaded_files)
                lib_info.local_path = str(self.local_repo / lib_info.relative_path)
                break
            else:
                errors.extend(download_errors)
        
        if downloaded:
            self._downloaded.add(coord_str)
            
            # Download dependencies if requested
            if download_dependencies:
                dep_files, dep_errors = self._download_dependencies(lib_info)
                downloaded.extend(dep_files)
                errors.extend(dep_errors)
            
            return True, downloaded, errors
        
        self._failed.add(coord_str)
        return False, [], errors
    
    def _get_files_to_download(self, coordinate: LibraryCoordinate) -> List[str]:
        """
        Get list of files to download for a library.
        
        Args:
            coordinate: The library coordinate
            
        Returns:
            List of filenames to download
        """
        artifact = coordinate.artifact_id
        version = coordinate.version
        classifier = coordinate.classifier
        
        files = [
            f"{artifact}-{version}.pom",
            f"{artifact}-{version}.jar",
        ]
        
        if classifier:
            files.append(f"{artifact}-{version}-{classifier}.jar")
        
        # Add common additional files
        files.extend([
            f"{artifact}-{version}-sources.jar",
            f"{artifact}-{version}-javadoc.jar",
        ])
        
        return files
    
    def _find_latest_version(self, coordinate: LibraryCoordinate) -> Optional[str]:
        """
        Find the latest version of a library.
        
        Args:
            coordinate: The library coordinate (without version)
            
        Returns:
            Latest version string or None
        """
        group_path = coordinate.group_id.replace('.', '/')
        artifact_path = f"{group_path}/{coordinate.artifact_id}"
        
        for repo_name, client in self.repository_client.clients.items():
            # Try to get maven-metadata.xml
            metadata_url = f"{client.config.url.rstrip('/')}/{artifact_path}/maven-metadata.xml"
            
            try:
                content = client.get_file_content(
                    LibraryInfo(
                        group_id=coordinate.group_id,
                        artifact_id=coordinate.artifact_id,
                        version="",
                        repository=repo_name
                    ),
                    "maven-metadata.xml"
                )
                
                if content:
                    # Parse version from metadata
                    versions = self._parse_metadata_versions(content)
                    if versions:
                        return versions[-1]  # Return latest version
            except Exception as e:
                self.logger.debug(f"Could not get metadata for {coordinate.coordinate}: {e}")
        
        return None
    
    def _parse_metadata_versions(self, metadata_xml: str) -> List[str]:
        """
        Parse versions from maven-metadata.xml.
        
        Args:
            metadata_xml: The metadata XML content
            
        Returns:
            List of versions
        """
        import xml.etree.ElementTree as ET
        
        versions = []
        try:
            root = ET.fromstring(metadata_xml)
            versioning = root.find('.//versioning')
            if versioning is not None:
                versions_el = versioning.find('versions')
                if versions_el is not None:
                    for v in versions_el.findall('version'):
                        if v.text:
                            versions.append(v.text.strip())
        except Exception as e:
            self.logger.debug(f"Error parsing metadata: {e}")
        
        return versions
    
    def _download_dependencies(
        self,
        library: LibraryInfo
    ) -> Tuple[List[str], List[str]]:
        """
        Download all dependencies of a library.
        
        Args:
            library: The library whose dependencies to download
            
        Returns:
            Tuple of (downloaded_files, errors)
        """
        downloaded = []
        errors = []
        
        # Parse POM to get dependencies
        pom_path = self.local_repo / library.relative_path / f"{library.artifact_id}-{library.version}.pom"
        
        if not pom_path.exists():
            return downloaded, errors
        
        try:
            pom_content = pom_path.read_text(encoding='utf-8', errors='ignore')
            pom_info, issues = self.pom_parser.parse_pom(pom_content, str(pom_path))
            
            if issues:
                self.logger.warning(f"POM issues for {library.coordinate}: {issues}")
            
            # Download each dependency
            for dep in pom_info.dependencies:
                if dep.scope in ('test', 'provided', 'system'):
                    continue
                
                dep_coord = LibraryCoordinate(
                    group_id=dep.group_id,
                    artifact_id=dep.artifact_id,
                    version=dep.version,
                    classifier=dep.classifier,
                    packaging=dep.type
                )
                
                success, dep_files, dep_errors = self.download_library(dep_coord)
                downloaded.extend(dep_files)
                errors.extend(dep_errors)
        
        except Exception as e:
            self.logger.error(f"Error downloading dependencies for {library.coordinate}: {e}")
            errors.append(str(e))
        
        return downloaded, errors
    
    def download_libraries(
        self,
        coordinates: List[str],
        download_dependencies: bool = True,
        overwrite: bool = False,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Download multiple libraries.
        
        Args:
            coordinates: List of Maven coordinate strings
            download_dependencies: Whether to download dependencies
            overwrite: Whether to overwrite existing files
            progress_callback: Progress callback function
            
        Returns:
            Dictionary with results
        """
        results = {
            'total': len(coordinates),
            'successful': [],
            'failed': [],
            'files_downloaded': [],
            'errors': []
        }
        
        for i, coord_str in enumerate(coordinates):
            try:
                coordinate = LibraryCoordinate.parse(coord_str)
            except ValueError as e:
                results['failed'].append(coord_str)
                results['errors'].append(f"{coord_str}: {e}")
                continue
            
            success, files, errors = self.download_library(
                coordinate,
                download_dependencies=download_dependencies,
                overwrite=overwrite
            )
            
            if success:
                results['successful'].append(coordinate.coordinate)
                results['files_downloaded'].extend(files)
            else:
                results['failed'].append(coordinate.coordinate)
                results['errors'].extend(errors)
            
            if progress_callback:
                progress_callback(i + 1, len(coordinates), coordinate.coordinate, success)
        
        return results
    
    def get_downloaded_libraries(self) -> Dict[str, LibraryInfo]:
        """
        Get all downloaded libraries.
        
        Returns:
            Dictionary of coordinate to LibraryInfo
        """
        libraries = {}
        
        for coord in self._downloaded:
            parts = coord.split(':')
            if len(parts) >= 3:
                lib = LibraryInfo(
                    group_id=parts[0],
                    artifact_id=parts[1],
                    version=parts[2],
                    local_path=str(self.local_repo / f"{parts[0].replace('.', '/')}/{parts[1]}/{parts[2]}")
                )
                libraries[coord] = lib
        
        return libraries


if __name__ == "__main__":
    # Test the library downloader
    print("Library downloader module loaded successfully")