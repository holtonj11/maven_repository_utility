"""
POM file parser for Maven Repository Scraper.
Handles parsing, validation, and dependency extraction from Maven POM files.
"""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from urllib.parse import urljoin
import requests

from .logger import MavenScraperLogger, get_logger


# Issue type constants
class IssueType:
    """Constants for issue types."""
    POM_MISSING = "POM file is missing"
    JAR_MISSING = "JAR file is missing but POM file present"
    JAR_AND_POM_MISSING = "JAR file and POM file are missing"
    HTML_ONLY_CONTENT = "HTML only content"
    FAILED_SIMPLE_XML = "Failed simple XML validation"
    FAILED_XSD_VALIDATION = "Failed XML XSD schema validation"
    JAR_INVALID = "JAR file is invalid"
    POM_NOT_VALID_MAVEN = "POM file is not valid Maven"


@dataclass
class Dependency:
    """
    Represents a Maven dependency.
    
    Attributes:
        group_id: The group ID of the dependency
        artifact_id: The artifact ID of the dependency
        version: The version of the dependency
        scope: The scope of the dependency (compile, test, provided, runtime, etc.)
        optional: Whether the dependency is optional
        type: The type of the dependency (jar, pom, etc.)
        classifier: The classifier of the dependency
        exclusions: List of exclusions for this dependency
    """
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    scope: str = "compile"
    optional: bool = False
    type: str = "jar"
    classifier: Optional[str] = None
    exclusions: List[Tuple[str, str]] = field(default_factory=list)
    
    def __hash__(self):
        return hash((self.group_id, self.artifact_id, self.version, self.classifier))
    
    def __eq__(self, other):
        if not isinstance(other, Dependency):
            return False
        return (
            self.group_id == other.group_id and
            self.artifact_id == other.artifact_id and
            self.version == other.version and
            self.classifier == other.classifier
        )
    
    @property
    def coordinate(self) -> str:
        """Get the Maven coordinate string (groupId:artifactId:version)."""
        coord = f"{self.group_id}:{self.artifact_id}"
        if self.version:
            coord += f":{self.version}"
        if self.classifier:
            coord += f":{self.classifier}"
        return coord
    
    @property
    def path(self) -> str:
        """Get the relative path for this dependency in a Maven repository."""
        group_path = self.group_id.replace('.', '/')
        return f"{group_path}/{self.artifact_id}/{self.version}"
    
    @classmethod
    def from_element(cls, element: ET.Element, ns: Dict[str, str]) -> 'Dependency':
        """
        Create a Dependency from an XML element.
        
        Args:
            element: The XML element representing the dependency
            ns: Namespace dictionary for XML parsing
        
        Returns:
            A Dependency object
        """
        def get_text(tag: str) -> str:
            el = element.find(f'.//{tag}', ns)
            return el.text.strip() if el is not None and el.text else ""
        
        dep = cls(
            group_id=get_text('groupId'),
            artifact_id=get_text('artifactId'),
            version=get_text('version'),
            scope=get_text('scope') or 'compile',
            optional=get_text('optional').lower() == 'true',
            type=get_text('type') or 'jar',
            classifier=get_text('classifier') or None
        )
        
        # Parse exclusions
        exclusions_el = element.find('.//exclusions', ns)
        if exclusions_el is not None:
            for excl in exclusions_el.findall('.//exclusion', ns):
                excl_group = excl.find('groupId', ns)
                excl_artifact = excl.find('artifactId', ns)
                if excl_group is not None and excl_artifact is not None:
                    dep.exclusions.append((
                        excl_group.text.strip() if excl_group.text else "",
                        excl_artifact.text.strip() if excl_artifact.text else ""
                    ))
        
        return dep


@dataclass
class POMInfo:
    """
    Represents parsed information from a POM file.
    
    Attributes:
        group_id: The group ID
        artifact_id: The artifact ID
        version: The version
        packaging: The packaging type (jar, pom, war, etc.)
        name: The project name
        description: The project description
        url: The project URL
        parent: The parent POM dependency
        dependencies: List of dependencies
        dependency_management: Dependency management section
        properties: Properties defined in the POM
        modules: For multi-module projects
        repositories: Additional repositories
        issues: List of issues detected
        raw_content: Raw XML content
        file_path: Path to the POM file
    """
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    packaging: str = "jar"
    name: str = ""
    description: str = ""
    url: str = ""
    parent: Optional[Dependency] = None
    dependencies: List[Dependency] = field(default_factory=list)
    dependency_management: List[Dependency] = field(default_factory=list)
    properties: Dict[str, str] = field(default_factory=dict)
    modules: List[str] = field(default_factory=list)
    repositories: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    raw_content: str = ""
    file_path: str = ""
    
    @property
    def coordinate(self) -> str:
        """Get the Maven coordinate string."""
        return f"{self.group_id}:{self.artifact_id}:{self.version}"
    
    @property
    def path(self) -> str:
        """Get the relative path in a Maven repository."""
        group_path = self.group_id.replace('.', '/')
        return f"{group_path}/{self.artifact_id}/{self.version}"


class XSDValidator:
    """
    Validates XML against an XSD schema.
    Downloads and caches the XSD schema file.
    """
    
    def __init__(self, xsd_path: Path, xsd_url: str, logger: MavenScraperLogger):
        """
        Initialize the XSD validator.
        
        Args:
            xsd_path: Path to the local XSD file
            xsd_url: URL to download the XSD from if not present
            logger: Logger instance
        """
        self.xsd_path = Path(xsd_path)
        self.xsd_url = xsd_url
        self.logger = logger
        self._schema = None
    
    def _download_xsd(self) -> bool:
        """
        Download the XSD schema file.
        
        Returns:
            True if download succeeded, False otherwise
        """
        try:
            self.logger.info(f"Downloading XSD schema from {self.xsd_url}")
            response = requests.get(self.xsd_url, timeout=30)
            response.raise_for_status()
            
            self.xsd_path.parent.mkdir(parents=True, exist_ok=True)
            self.xsd_path.write_bytes(response.content)
            self.logger.info(f"XSD schema saved to {self.xsd_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to download XSD schema: {e}")
            return False
    
    def _load_schema(self):
        """Load the XSD schema for validation."""
        if self._schema is not None:
            return self._schema
        
        # Check if XSD file exists
        if not self.xsd_path.exists():
            if not self._download_xsd():
                return None
        
        try:
            # Use lxml for proper XSD validation if available
            try:
                from lxml import etree
                xsd_doc = etree.parse(str(self.xsd_path))
                self._schema = etree.XMLSchema(xsd_doc)
                return self._schema
            except ImportError:
                self.logger.warning(
                    "lxml not available, falling back to simple validation. "
                    "Install lxml for proper XSD validation: pip install lxml"
                )
                return None
        except Exception as e:
            self.logger.error(f"Failed to load XSD schema: {e}")
            return None
    
    def validate(self, xml_content: str) -> Tuple[bool, Optional[str]]:
        """
        Validate XML content against the XSD schema.
        
        Args:
            xml_content: The XML content to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        schema = self._load_schema()
        
        if schema is None:
            # Fall back to simple validation if schema not available
            return simple_xml_validation(xml_content)
        
        try:
            from lxml import etree
            doc = etree.fromstring(xml_content.encode('utf-8'))
            is_valid = schema.validate(doc)
            
            if is_valid:
                return True, None
            else:
                errors = schema.error_log
                error_msg = str(errors)
                return False, error_msg
        except ImportError:
            return simple_xml_validation(xml_content)
        except Exception as e:
            return False, str(e)


def simple_xml_validation(content: str) -> Tuple[bool, Optional[str]]:
    """
    Perform simple XML validation by checking for XML declaration.
    
    Args:
        content: The XML content to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not content or not content.strip():
        return False, "Empty content"
    
    first_line = content.strip().split('\n')[0].strip()
    
    if first_line.startswith('<?xml'):
        try:
            ET.fromstring(content)
            return True, None
        except ET.ParseError as e:
            return False, str(e)
    
    return False, "Missing XML declaration"


def is_html_content(content: str) -> bool:
    """
    Check if content is HTML instead of XML.
    
    Args:
        content: The content to check
    
    Returns:
        True if content appears to be HTML, False otherwise
    """
    if not content:
        return False
    
    first_line = content.strip().split('\n')[0].strip().lower()
    
    return first_line.startswith('<html') or first_line.startswith('<!doctype html')


class POMParser:
    """
    Parser for Maven POM files.
    Handles parsing, validation, and dependency extraction.
    """
    
    # Maven POM namespace
    MAVEN_NS = "http://maven.apache.org/POM/4.0.0"
    
    def __init__(
        self,
        validation_mode: str = "xsd",
        xsd_path: Path = None,
        xsd_url: str = "https://maven.apache.org/xsd/maven-4.0.0.xsd",
        min_jar_size: int = 5120,
        logger: MavenScraperLogger = None
    ):
        """
        Initialize the POM parser.
        
        Args:
            validation_mode: XML validation mode ('simple' or 'xsd')
            xsd_path: Path to the XSD file
            xsd_url: URL to download XSD from
            min_jar_size: Minimum valid JAR file size in bytes
            logger: Logger instance
        """
        self.validation_mode = validation_mode
        self.min_jar_size = min_jar_size
        self.logger = logger or get_logger()
        
        self._xsd_validator = None
        if validation_mode == "xsd" and xsd_path:
            self._xsd_validator = XSDValidator(xsd_path, xsd_url, self.logger)
    
    def _get_namespace(self, root: ET.Element) -> Dict[str, str]:
        """
        Get the namespace dictionary for XML parsing.
        
        Args:
            root: The root element of the XML document
        
        Returns:
            Namespace dictionary
        """
        ns = {'m': self.MAVEN_NS}
        return ns
    
    def _resolve_property(self, value: str, properties: Dict[str, str], pom_info: POMInfo) -> str:
        """
        Resolve property references in a string value.
        
        Properties can be referenced as ${property} or ${project.property}.
        
        Args:
            value: The string value with potential property references
            properties: Dictionary of properties
            pom_info: POM info for default values
        
        Returns:
            The resolved string value
        """
        if not value:
            return value
        
        # Pattern to match ${property} references
        pattern = r'\$\{([^}]+)\}'
        
        def replace_property(match):
            prop_name = match.group(1)
            
            # Handle special project properties
            if prop_name == 'project.version':
                return pom_info.version
            elif prop_name == 'project.groupId':
                return pom_info.group_id
            elif prop_name == 'project.artifactId':
                return pom_info.artifact_id
            elif prop_name.startswith('project.'):
                # Remove 'project.' prefix
                prop_name = prop_name[8:]
            
            # Check properties dictionary
            if prop_name in properties:
                return properties[prop_name]
            
            # Return original if not found
            return match.group(0)
        
        # Resolve recursively until no more changes
        previous = None
        resolved = value
        max_iterations = 10
        iteration = 0
        
        while resolved != previous and iteration < max_iterations:
            previous = resolved
            resolved = re.sub(pattern, replace_property, resolved)
            iteration += 1
        
        return resolved
    
    def _parse_element_text(self, element: ET.Element, tag: str, ns: Dict[str, str]) -> str:
        """
        Parse text content from an element's child tag.
        
        Args:
            element: Parent element
            tag: Tag name to find
            ns: Namespace dictionary
        
        Returns:
            Text content or empty string
        """
        child = element.find(f'.//m:{tag}', ns)
        if child is not None and child.text:
            return child.text.strip()
        return ""
    
    def parse_pom(self, content: str, file_path: str = "") -> Tuple[POMInfo, List[str]]:
        """
        Parse a POM file content.
        
        Args:
            content: The POM file content
            file_path: Path to the POM file (for reference)
        
        Returns:
            Tuple of (POMInfo object, list of issues)
        """
        pom_info = POMInfo(raw_content=content, file_path=file_path)
        issues = []
        
        # Check if content is empty
        if not content or not content.strip():
            issues.append(IssueType.POM_MISSING)
            return pom_info, issues
        
        # Check for HTML content
        if is_html_content(content):
            issues.append(IssueType.HTML_ONLY_CONTENT)
            return pom_info, issues
        
        # Validate XML
        if self.validation_mode == "xsd" and self._xsd_validator:
            is_valid, error = self._xsd_validator.validate(content)
            if not is_valid:
                issues.append(IssueType.FAILED_XSD_VALIDATION)
                self.logger.warning(f"XSD validation failed for {file_path}: {error}")
        else:
            is_valid, error = simple_xml_validation(content)
            if not is_valid:
                issues.append(IssueType.FAILED_SIMPLE_XML)
                self.logger.warning(f"Simple XML validation failed for {file_path}: {error}")
        
        if issues:
            return pom_info, issues
        
        # Parse XML
        try:
            root = ET.fromstring(content)
            ns = self._get_namespace(root)
            
            # Parse basic information
            pom_info.group_id = self._parse_element_text(root, 'groupId', ns)
            pom_info.artifact_id = self._parse_element_text(root, 'artifactId', ns)
            pom_info.version = self._parse_element_text(root, 'version', ns)
            pom_info.packaging = self._parse_element_text(root, 'packaging', ns) or 'jar'
            pom_info.name = self._parse_element_text(root, 'name', ns)
            pom_info.description = self._parse_element_text(root, 'description', ns)
            pom_info.url = self._parse_element_text(root, 'url', ns)
            
            # Parse properties
            properties_el = root.find('.//m:properties', ns)
            if properties_el is not None:
                for child in properties_el:
                    tag = child.tag.replace(f'{{{self.MAVEN_NS}}}', '')
                    if child.text:
                        pom_info.properties[tag] = child.text.strip()
            
            # Resolve properties in basic info
            pom_info.group_id = self._resolve_property(pom_info.group_id, pom_info.properties, pom_info)
            pom_info.artifact_id = self._resolve_property(pom_info.artifact_id, pom_info.properties, pom_info)
            pom_info.version = self._resolve_property(pom_info.version, pom_info.properties, pom_info)
            
            # Parse parent
            parent_el = root.find('.//m:parent', ns)
            if parent_el is not None:
                parent = Dependency.from_element(parent_el, ns)
                # Resolve properties in parent
                parent.group_id = self._resolve_property(parent.group_id, pom_info.properties, pom_info)
                parent.artifact_id = self._resolve_property(parent.artifact_id, pom_info.properties, pom_info)
                parent.version = self._resolve_property(parent.version, pom_info.properties, pom_info)
                pom_info.parent = parent
            
            # Inherit from parent if values are missing
            if pom_info.parent:
                if not pom_info.group_id:
                    pom_info.group_id = pom_info.parent.group_id
                if not pom_info.version:
                    pom_info.version = pom_info.parent.version
            
            # Check for required Maven elements
            if not pom_info.group_id or not pom_info.artifact_id or not pom_info.version:
                issues.append(IssueType.POM_NOT_VALID_MAVEN)
                self.logger.warning(
                    f"POM missing required elements in {file_path}: "
                    f"groupId={pom_info.group_id}, artifactId={pom_info.artifact_id}, "
                    f"version={pom_info.version}"
                )
            
            # Parse dependencies
            dependencies_el = root.find('.//m:dependencies', ns)
            if dependencies_el is not None:
                for dep_el in dependencies_el.findall('.//m:dependency', ns):
                    dep = Dependency.from_element(dep_el, ns)
                    # Resolve properties
                    dep.group_id = self._resolve_property(dep.group_id, pom_info.properties, pom_info)
                    dep.artifact_id = self._resolve_property(dep.artifact_id, pom_info.properties, pom_info)
                    dep.version = self._resolve_property(dep.version, pom_info.properties, pom_info)
                    pom_info.dependencies.append(dep)
            
            # Parse dependency management
            dep_mgmt_el = root.find('.//m:dependencyManagement', ns)
            if dep_mgmt_el is not None:
                deps_el = dep_mgmt_el.find('.//m:dependencies', ns)
                if deps_el is not None:
                    for dep_el in deps_el.findall('.//m:dependency', ns):
                        dep = Dependency.from_element(dep_el, ns)
                        dep.group_id = self._resolve_property(dep.group_id, pom_info.properties, pom_info)
                        dep.artifact_id = self._resolve_property(dep.artifact_id, pom_info.properties, pom_info)
                        dep.version = self._resolve_property(dep.version, pom_info.properties, pom_info)
                        pom_info.dependency_management.append(dep)
            
            # Parse modules (for multi-module projects)
            modules_el = root.find('.//m:modules', ns)
            if modules_el is not None:
                for module_el in modules_el.findall('.//m:module', ns):
                    if module_el.text:
                        pom_info.modules.append(module_el.text.strip())
            
            # Parse repositories
            repos_el = root.find('.//m:repositories', ns)
            if repos_el is not None:
                for repo_el in repos_el.findall('.//m:repository', ns):
                    url_el = repo_el.find('.//m:url', ns)
                    if url_el is not None and url_el.text:
                        pom_info.repositories.append(url_el.text.strip())
            
        except ET.ParseError as e:
            issues.append(IssueType.FAILED_SIMPLE_XML)
            self.logger.error(f"Failed to parse POM XML in {file_path}: {e}")
        
        pom_info.issues = issues
        return pom_info, issues
    
    def check_library_issues(
        self,
        library_path: Path,
        pom_content: Optional[str] = None
    ) -> Tuple[List[str], Optional[POMInfo]]:
        """
        Check a library for issues.
        
        Args:
            library_path: Path to the library directory
            pom_content: Optional POM content (if already downloaded)
        
        Returns:
            Tuple of (list of issues, POMInfo if parsed successfully)
        """
        issues = []
        pom_info = None
        
        library_path = Path(library_path)
        
        # Find POM file
        pom_files = list(library_path.glob("*.pom"))
        pom_file = pom_files[0] if pom_files else None
        
        # Find JAR file
        jar_files = list(library_path.glob("*.jar"))
        jar_file = jar_files[0] if jar_files else None
        
        # Check for missing files
        if pom_file is None:
            if jar_file is None:
                issues.append(IssueType.JAR_AND_POM_MISSING)
            else:
                issues.append(IssueType.POM_MISSING)
                # Check JAR size
                if jar_file.stat().st_size < self.min_jar_size:
                    issues.append(IssueType.JAR_INVALID)
            return issues, None
        
        if jar_file is None:
            issues.append(IssueType.JAR_MISSING)
        else:
            # Check JAR size
            if jar_file.stat().st_size < self.min_jar_size:
                issues.append(IssueType.JAR_INVALID)
        
        # Parse POM file
        try:
            if pom_content:
                content = pom_content
            else:
                content = pom_file.read_text(encoding='utf-8', errors='ignore')
            
            pom_info, parse_issues = self.parse_pom(content, str(pom_file))
            issues.extend(parse_issues)
            
        except Exception as e:
            self.logger.error(f"Error reading POM file {pom_file}: {e}")
            issues.append(IssueType.POM_MISSING)
        
        return issues, pom_info


if __name__ == "__main__":
    # Test the POM parser
    from config import ScraperConfig, XMLValidationConfig
    from logger import setup_logger
    
    config = ScraperConfig(
        xml_validation=XMLValidationConfig(validation_mode="simple")
    )
    logger = setup_logger(config)
    
    parser = POMParser(
        validation_mode="simple",
        logger=logger
    )
    
    # Test with a sample POM
    sample_pom = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test-lib</artifactId>
    <version>1.0.0</version>
    <dependencies>
        <dependency>
            <groupId>org.springframework</groupId>
            <artifactId>spring-core</artifactId>
            <version>5.3.0</version>
        </dependency>
    </dependencies>
</project>
"""
    
    pom_info, issues = parser.parse_pom(sample_pom)
    print(f"Parsed: {pom_info.coordinate}")
    print(f"Dependencies: {[d.coordinate for d in pom_info.dependencies]}")
    print(f"Issues: {issues}")