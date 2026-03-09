"""
HTTP client for Maven repository access.
Handles browsing, downloading, and scraping Maven repositories.
"""

import os
import re
import time
import hashlib
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Generator, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .logger import MavenScraperLogger, get_logger
from .config import RepositoryConfig


@dataclass
class LibraryInfo:
    """
    Information about a Maven library.
    
    Attributes:
        group_id: The group ID
        artifact_id: The artifact ID
        version: The version
        repository: The repository this library was found in
        url: The base URL for this library in the repository
        local_path: The local path where this library is stored
        has_pom: Whether a POM file exists
        has_jar: Whether a JAR file exists
        files: List of files available for this library
    """
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    repository: str = ""
    url: str = ""
    local_path: str = ""
    has_pom: bool = False
    has_jar: bool = False
    files: List[str] = field(default_factory=list)
    
    @property
    def coordinate(self) -> str:
        """Get the Maven coordinate string."""
        return f"{self.group_id}:{self.artifact_id}:{self.version}"
    
    @property
    def relative_path(self) -> str:
        """Get the relative path in a Maven repository."""
        group_path = self.group_id.replace('.', '/')
        return f"{group_path}/{self.artifact_id}/{self.version}"
    
    @classmethod
    def from_path(cls, path: str, repository: str = "", url: str = "") -> 'LibraryInfo':
        """
        Create a LibraryInfo from a repository path.
        
        Args:
            path: Path like "com/anypoint/java/clients/api_designer/0.3"
            repository: Repository name
            url: Base URL for the library
        
        Returns:
            LibraryInfo object
        """
        parts = path.strip('/').split('/')
        
        if len(parts) < 3:
            return cls()
        
        version = parts[-1]
        artifact_id = parts[-2]
        group_id = '.'.join(parts[:-2])
        
        return cls(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            repository=repository,
            url=url
        )


class RepositoryClient:
    """
    Client for accessing Maven repositories.
    Handles browsing, downloading, and scraping operations.
    """
    
    def __init__(
        self,
        config: RepositoryConfig,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        timeout: int = 300,
        max_concurrent: int = 5,
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the repository client.
        
        Args:
            config: Repository configuration
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            timeout: Request timeout in seconds
            max_concurrent: Maximum concurrent downloads
            logger: Logger instance
        """
        self.config = config
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.logger = logger or get_logger()
        
        # Create session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Maven-Repository-Scraper/1.0',
            'Accept': '*/*'
        })
        
        # Lock for thread-safe operations
        self._lock = threading.Lock()
        
        # Cache for directory listings
        self._listing_cache: Dict[str, List[str]] = {}
    
    def _make_request(self, url: str, method: str = "GET", **kwargs) -> Optional[requests.Response]:
        """
        Make an HTTP request with retry logic.
        
        Args:
            url: The URL to request
            method: HTTP method (GET, HEAD, etc.)
            **kwargs: Additional arguments for requests
        
        Returns:
            Response object or None if failed
        """
        kwargs.setdefault('timeout', self.timeout)
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    self.logger.warning(
                        f"Request failed for {url} (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.logger.error(f"Request failed for {url} after {self.max_retries} attempts: {e}")
                    return None
        
        return None
    
    def _is_mulesoft_browse_url(self) -> bool:
        """Check if this is a MuleSoft browse URL."""
        return "mulesoft.org" in self.config.url and "#browse" in self.config.url
    
    def _get_mulesoft_api_url(self) -> str:
        """
        Convert MuleSoft browse URL to API URL.
        
        The browse URL is like:
        https://repository.mulesoft.org/nexus/#browse/browse:releases
        
        The API URL is:
        https://repository.mulesoft.org/nexus/service/local/repositories/releases/content/
        """
        # Extract repository name from browse URL
        match = re.search(r'browse:([^/]+)', self.config.url)
        if match:
            repo_name = match.group(1)
            return f"https://repository.mulesoft.org/nexus/service/local/repositories/{repo_name}/content/"
        return self.config.url
    
    def list_directory(self, path: str = "") -> List[str]:
        """
        List the contents of a directory in the repository.
        
        Args:
            path: The path to list (relative to repository root)
        
        Returns:
            List of item names in the directory
        """
        cache_key = f"{self.config.name}:{path}"
        
        with self._lock:
            if cache_key in self._listing_cache:
                return self._listing_cache[cache_key]
        
        items = []
        
        try:
            if self._is_mulesoft_browse_url():
                items = self._list_mulesoft_directory(path)
            else:
                items = self._list_standard_directory(path)
        except Exception as e:
            self.logger.error(f"Error listing directory {path} in {self.config.name}: {e}")
        
        with self._lock:
            self._listing_cache[cache_key] = items
        
        return items
    
    def _list_standard_directory(self, path: str) -> List[str]:
        """
        List directory contents from a standard Maven repository.
        
        Args:
            path: The path to list
        
        Returns:
            List of item names
        """
        base_url = self.config.url.rstrip('/')
        url = f"{base_url}/{path}" if path else base_url
        
        response = self._make_request(url)
        if not response:
            return []
        
        items = []
        content = response.text
        
        # Parse HTML to find links
        # Look for href attributes in anchor tags
        href_pattern = r'href=["\']([^"\']+)["\']'
        hrefs = re.findall(href_pattern, content, re.IGNORECASE)
        
        for href in hrefs:
            # Clean up the href
            href = href.strip()
            
            # Skip parent directory and special links
            if href in ('../', '..') or href.startswith('?') or href.startswith('#'):
                continue
            
            # Remove query strings
            href = href.split('?')[0]
            
            # Check if it's a directory (ends with /) or a file
            is_directory = href.endswith('/')
            name = href.rstrip('/')
            
            # Only include if it's a valid Maven path component
            if name and '/' not in name:
                items.append(name if is_directory else name)
        
        # Also try to parse with regex for directory listing format
        # Many Maven repos use a simple format like:
        # <a href="name/">name/</a>
        dir_pattern = r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
        matches = re.findall(dir_pattern, content, re.IGNORECASE)
        
        for href, text in matches:
            href = href.strip().rstrip('/')
            text = text.strip().rstrip('/')
            
            if href and '/' not in href and href not in items:
                if not href.startswith('?') and href not in ('..', '../'):
                    items.append(href)
        
        return list(set(items))
    
    def _list_mulesoft_directory(self, path: str) -> List[str]:
        """
        List directory contents from MuleSoft Nexus repository.
        
        Uses the Nexus REST API for more reliable listing.
        
        Args:
            path: The path to list
        
        Returns:
            List of item names
        """
        api_url = self._get_mulesoft_api_url()
        url = f"{api_url}{path}"
        
        # Nexus uses a specific content type for directory listings
        headers = {'Accept': 'application/json'}
        
        response = self._make_request(url, headers=headers)
        if not response:
            # Fallback to HTML parsing
            return self._list_standard_directory(path)
        
        items = []
        
        try:
            # Try to parse as JSON (Nexus REST API response)
            data = response.json()
            if isinstance(data, dict):
                # Nexus API returns items in various formats
                if 'data' in data:
                    for item in data['data']:
                        if isinstance(item, dict) and 'text' in item:
                            items.append(item['text'])
                        elif isinstance(item, str):
                            items.append(item)
                elif 'items' in data:
                    for item in data['items']:
                        if isinstance(item, dict) and 'name' in item:
                            items.append(item['name'])
                        elif isinstance(item, str):
                            items.append(item)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'name' in item:
                        items.append(item['name'])
                    elif isinstance(item, str):
                        items.append(item)
        except ValueError:
            # Not JSON, parse HTML
            items = self._list_standard_directory(path)
        
        return list(set(items))
    
    def discover_libraries(
        self,
        progress_callback=None
    ) -> Generator[LibraryInfo, None, None]:
        """
        Discover all libraries in the repository.
        
        This is a generator that yields LibraryInfo objects as they are discovered.
        Traverses the repository directory structure to find all libraries.
        
        Args:
            progress_callback: Optional callback function for progress updates
        
        Yields:
            LibraryInfo objects for each discovered library
        """
        self.logger.info(f"Starting library discovery in {self.config.name}")
        
        if self._is_mulesoft_browse_url():
            yield from self._discover_mulesoft_libraries(progress_callback)
        else:
            yield from self._discover_standard_libraries(progress_callback)
    
    def _discover_standard_libraries(
        self,
        progress_callback=None,
        current_path: str = "",
        depth: int = 0
    ) -> Generator[LibraryInfo, None, None]:
        """
        Discover libraries in a standard Maven repository.
        
        Args:
            progress_callback: Progress callback
            current_path: Current path being explored
            depth: Current depth in the directory tree
        
        Yields:
            LibraryInfo objects
        """
        items = self.list_directory(current_path)
        
        # Check if this looks like a version directory
        # Version directories typically contain .pom or .jar files
        is_version_dir = False
        has_artifact_files = False
        
        for item in items:
            if item.endswith('.pom') or item.endswith('.jar'):
                has_artifact_files = True
                break
        
        if has_artifact_files and current_path:
            # This is a version directory - we found a library
            lib_info = LibraryInfo.from_path(
                current_path,
                repository=self.config.name,
                url=f"{self.config.url.rstrip('/')}/{current_path}"
            )
            
            if lib_info.group_id and lib_info.artifact_id and lib_info.version:
                lib_info.files = items
                lib_info.has_pom = any(f.endswith('.pom') for f in items)
                lib_info.has_jar = any(f.endswith('.jar') for f in items)
                
                if progress_callback:
                    progress_callback(lib_info)
                
                yield lib_info
                return
        
        # Recurse into subdirectories
        for item in items:
            if item.endswith('.pom') or item.endswith('.jar') or item.startswith('.'):
                continue
            
            new_path = f"{current_path}/{item}" if current_path else item
            yield from self._discover_standard_libraries(
                progress_callback,
                new_path,
                depth + 1
            )
    
    def _discover_mulesoft_libraries(
        self,
        progress_callback=None
    ) -> Generator[LibraryInfo, None, None]:
        """
        Discover libraries in MuleSoft Nexus repository.
        
        Uses the Nexus API for efficient discovery.
        
        Args:
            progress_callback: Progress callback
        
        Yields:
            LibraryInfo objects
        """
        # Start from the root and traverse
        yield from self._discover_standard_libraries(progress_callback)
    
    def download_file(
        self,
        library: LibraryInfo,
        filename: str,
        local_dir: Path,
        overwrite: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Download a file from the repository.
        
        Args:
            library: The library to download from
            filename: The filename to download
            local_dir: Local directory to save to
            overwrite: Whether to overwrite existing files
        
        Returns:
            Tuple of (success, error_message)
        """
        local_file = local_dir / filename
        
        # Check if file already exists
        if local_file.exists() and not overwrite:
            self.logger.debug(f"File already exists: {local_file}")
            return True, None
        
        # Build URL
        if self._is_mulesoft_browse_url():
            api_url = self._get_mulesoft_api_url()
            url = f"{api_url}{library.relative_path}/{filename}"
        else:
            url = f"{self.config.url.rstrip('/')}/{library.relative_path}/{filename}"
        
        self.logger.debug(f"Downloading {url}")
        
        response = self._make_request(url, stream=True)
        if not response:
            return False, f"Failed to download {url}"
        
        try:
            local_dir.mkdir(parents=True, exist_ok=True)
            
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            self.logger.debug(f"Downloaded {filename} to {local_file}")
            return True, None
            
        except Exception as e:
            self.logger.error(f"Error saving file {local_file}: {e}")
            if local_file.exists():
                local_file.unlink()
            return False, str(e)
    
    def download_library(
        self,
        library: LibraryInfo,
        local_repo: Path,
        files: List[str] = None,
        overwrite: bool = False
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Download all files for a library.
        
        Args:
            library: The library to download
            local_repo: Local repository root
            files: Specific files to download (default: all)
            overwrite: Whether to overwrite existing files
        
        Returns:
            Tuple of (overall_success, list of downloaded files, list of errors)
        """
        local_dir = local_repo / library.relative_path
        
        if files is None:
            # Download common Maven files
            files = [
                f"{library.artifactId}-{library.version}.pom",
                f"{library.artifactId}-{library.version}.jar",
                f"{library.artifactId}-{library.version}-sources.jar",
                f"{library.artifactId}-{library.version}-javadoc.jar",
            ]
        
        downloaded = []
        errors = []
        
        for filename in files:
            success, error = self.download_file(library, filename, local_dir, overwrite)
            if success:
                downloaded.append(filename)
            else:
                errors.append(f"{filename}: {error}")
        
        overall_success = len(downloaded) > 0
        return overall_success, downloaded, errors
    
    def get_file_content(self, library: LibraryInfo, filename: str) -> Optional[str]:
        """
        Get the content of a file without saving it locally.
        
        Args:
            library: The library containing the file
            filename: The filename to get
        
        Returns:
            File content or None if not found
        """
        if self._is_mulesoft_browse_url():
            api_url = self._get_mulesoft_api_url()
            url = f"{api_url}{library.relative_path}/{filename}"
        else:
            url = f"{self.config.url.rstrip('/')}/{library.relative_path}/{filename}"
        
        response = self._make_request(url)
        if response:
            return response.text
        return None
    
    def check_file_exists(self, library: LibraryInfo, filename: str) -> bool:
        """
        Check if a file exists in the repository.
        
        Args:
            library: The library to check
            filename: The filename to check
        
        Returns:
            True if the file exists, False otherwise
        """
        if self._is_mulesoft_browse_url():
            api_url = self._get_mulesoft_api_url()
            url = f"{api_url}{library.relative_path}/{filename}"
        else:
            url = f"{self.config.url.rstrip('/')}/{library.relative_path}/{filename}"
        
        response = self._make_request(url, method="HEAD")
        return response is not None
    
    def close(self):
        """Close the session."""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class MultiRepositoryClient:
    """
    Client for accessing multiple Maven repositories.
    Coordinates library discovery and downloads across multiple repositories.
    """
    
    def __init__(
        self,
        repositories: List[RepositoryConfig],
        max_retries: int = 3,
        retry_delay: float = 2.0,
        timeout: int = 300,
        max_concurrent: int = 5,
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the multi-repository client.
        
        Args:
            repositories: List of repository configurations
            max_retries: Maximum retry attempts
            retry_delay: Delay between retries
            timeout: Request timeout
            max_concurrent: Maximum concurrent downloads
            logger: Logger instance
        """
        self.repositories = repositories
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self.logger = logger or get_logger()
        
        # Create individual clients
        self.clients: Dict[str, RepositoryClient] = {}
        for repo in repositories:
            self.clients[repo.name] = RepositoryClient(
                config=repo,
                max_retries=max_retries,
                retry_delay=retry_delay,
                timeout=timeout,
                max_concurrent=max_concurrent,
                logger=logger
            )
    
    def discover_all_libraries(
        self,
        progress_callback=None
    ) -> Dict[str, LibraryInfo]:
        """
        Discover all libraries across all repositories.
        
        Deduplicates libraries that exist in multiple repositories.
        
        Args:
            progress_callback: Progress callback
        
        Returns:
            Dictionary mapping library coordinates to LibraryInfo
        """
        libraries: Dict[str, LibraryInfo] = {}
        
        for name, client in self.clients.items():
            self.logger.info(f"Discovering libraries in {name}")
            
            try:
                for lib_info in client.discover_libraries(progress_callback):
                    coord = lib_info.coordinate
                    
                    if coord not in libraries:
                        libraries[coord] = lib_info
                    else:
                        # Library exists in multiple repos - keep first found
                        self.logger.debug(
                            f"Library {coord} found in multiple repositories, "
                            f"keeping {libraries[coord].repository}"
                        )
            except Exception as e:
                self.logger.error(f"Error discovering libraries in {name}: {e}")
        
        self.logger.info(f"Discovered {len(libraries)} unique libraries")
        return libraries
    
    def download_library(
        self,
        library: LibraryInfo,
        local_repo: Path,
        files: List[str] = None,
        overwrite: bool = False
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Download a library from the appropriate repository.
        
        Args:
            library: The library to download
            local_repo: Local repository root
            files: Files to download
            overwrite: Whether to overwrite
        
        Returns:
            Tuple of (success, downloaded files, errors)
        """
        repo_name = library.repository
        
        if repo_name not in self.clients:
            # Try each repository
            for name, client in self.clients.items():
                success, downloaded, errors = client.download_library(
                    library, local_repo, files, overwrite
                )
                if success:
                    return success, downloaded, errors
            
            return False, [], ["Library not found in any repository"]
        
        return self.clients[repo_name].download_library(
            library, local_repo, files, overwrite
        )
    
    def get_file_content(self, library: LibraryInfo, filename: str) -> Optional[str]:
        """
        Get file content from the appropriate repository.
        
        Args:
            library: The library
            filename: The filename
        
        Returns:
            File content or None
        """
        repo_name = library.repository
        
        if repo_name in self.clients:
            return self.clients[repo_name].get_file_content(library, filename)
        
        # Try all repositories
        for client in self.clients.values():
            content = client.get_file_content(library, filename)
            if content:
                return content
        
        return None
    
    def close_all(self):
        """Close all client sessions."""
        for client in self.clients.values():
            client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()
        return False


if __name__ == "__main__":
    # Test the repository client
    from config import RepositoryConfig, ScraperConfig
    from logger import setup_logger
    
    config = ScraperConfig()
    logger = setup_logger(config)
    
    # Test with Maven Central
    repo_config = RepositoryConfig(
        url="https://repo1.maven.org/maven2/",
        name="maven-central"
    )
    
    client = RepositoryClient(repo_config, logger=logger)
    
    # List root directory
    print("Listing root directory...")
    items = client.list_directory("")
    print(f"Found {len(items)} items")
    print(f"Sample: {items[:10]}")
    
    client.close()