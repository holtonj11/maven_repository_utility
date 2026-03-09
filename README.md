# Maven Repository Scraper and Maintenance Tool

A comprehensive Python tool for scraping Maven repositories, resolving dependencies, and maintaining a local Maven repository.

## Features

- **Multi-Repository Support**: Scrape from multiple Maven repositories simultaneously
- **Dependency Resolution**: Full recursive dependency tree resolution following Maven's rules
- **Parent POM Resolution**: Correctly resolve parent POMs and inherit properties
- **Transitive Dependencies**: Resolve all transitive dependencies to n-levels deep
- **POM Validation**: Support for simple XML validation or full XSD schema validation
- **Issue Detection**: Detect and report various issues with libraries:
  - Missing POM files
  - Missing JAR files
  - Invalid JAR files (corrupted)
  - HTML-only content in POM files
  - Invalid XML in POM files
  - Missing required Maven elements
- **Output Generation**:
  - Text-based dependency tree with visual hierarchy
  - JSON dependency tree with full metadata
  - Issue-specific reports
- **Configurable**: Heavily configurable via command-line arguments or config files
- **Full Logging**: Comprehensive logging to both file and console

## Installation

### Prerequisites

- Python 3.11 or higher
- pip package manager

### Install Dependencies

```bash
pip install -r requirements.txt
```

For proper XSD validation (recommended):

```bash
pip install lxml
```

## Usage

### Basic Usage

```bash
# Full scrape from remote repositories
python maven_scraper.py
```

This will:
1. Scrape the default repositories (MuleSoft and Maven Central)
2. Download libraries to `~/.m2/repository`
3. Resolve all dependencies
4. Generate output files in `./directoryTree_output/`

### Local-Only Mode (No Remote Scraping)

If you already have a local `.m2/repository` and just want to generate the dependency tree without scraping remote repositories:

```bash
# Scan local repository only, generate dependency tree
python maven_scraper.py --local-only

# Scan and validate all local files
python maven_scraper.py --local-only --validate-local

# Specify a custom local repository path
python maven_scraper.py --local-only --local-repo /path/to/m2/repository
```

This is useful for:
- Auditing your existing local Maven repository
- Generating dependency trees without network access
- Validating all POM and JAR files locally
- Creating reports on issues in your local cache

### Command-Line Options

#### Repository Settings

```bash
# Add a custom repository
python maven_scraper.py --add-repo https://my.repo.com/maven2

# Set local repository path
python maven_scraper.py --local-repo /path/to/repo

# Load configuration from file
python maven_scraper.py --config-file config.json
```

#### XML Validation Settings

```bash
# Use simple XML validation (check for <?xml header)
python maven_scraper.py --xml-validation simple

# Use XSD validation (default)
python maven_scraper.py --xml-validation xsd

# Custom XSD file
python maven_scraper.py --xsd-file maven-4.1.0.xsd --xsd-url https://maven.apache.org/xsd/maven-4.1.0.xsd
```

#### Output Settings

```bash
# Set output directory
python maven_scraper.py --output-dir /path/to/output

# Custom tree directory name
python maven_scraper.py --tree-dir-name my_dependency_tree
```

#### Logging Settings

```bash
# Set log level
python maven_scraper.py --log-level DEBUG

# Disable file logging
python maven_scraper.py --no-file-log

# Disable console logging
python maven_scraper.py --no-console-log
```

#### Scraper Behavior Settings

```bash
# Set maximum retries
python maven_scraper.py --max-retries 5

# Set retry delay (seconds)
python maven_scraper.py --retry-delay 3.0

# Set download timeout (seconds)
python maven_scraper.py --timeout 600

# Set maximum dependency depth
python maven_scraper.py --max-depth 50

# Set minimum JAR size (bytes)
python maven_scraper.py --min-jar-size 10240
```

#### Utility Options

```bash
# Save current configuration to file
python maven_scraper.py --save-config my_config.json

# Dry run (don't actually download)
python maven_scraper.py --dry-run

# Verbose output
python maven_scraper.py --verbose
```

### Configuration File

You can save and load configurations using JSON files:

```bash
# Save configuration
python maven_scraper.py --save-config config.json

# Load configuration
python maven_scraper.py --config-file config.json
```

Example configuration file:

```json
{
  "repositories": [
    {
      "url": "https://repo1.maven.org/maven2/",
      "name": "maven-central"
    }
  ],
  "local_repository": "/Users/username/.m2/repository",
  "xml_validation": {
    "validation_mode": "xsd",
    "xsd_filename": "maven-4.0.0.xsd",
    "xsd_url": "https://maven.apache.org/xsd/maven-4.0.0.xsd"
  },
  "output": {
    "output_directory": "/path/to/output",
    "tree_directory_name": "directoryTree_output"
  },
  "logging": {
    "log_to_file": true,
    "log_to_console": true,
    "log_level": "INFO"
  },
  "max_retries": 3,
  "retry_delay": 2.0,
  "download_timeout": 300,
  "max_dependency_depth": 100
}
```

## Output Files

### Text Dependency Tree (`dependencyTree_YYYY-MM-DDTHH:MM:SS.FFF.txt`)

```
================================================================================
MAVEN DEPENDENCY TREE
Generated: 2024-01-15T10:30:45.123456
Total Libraries: 1500
Libraries with Issues: 5
================================================================================

|__ org.springframework:spring-core:5.3.0
    |__ org.springframework:spring-jcl:5.3.0
    |__ commons-logging:commons-logging:1.2
|__ com.anypoint.java.clients:api_designer:0.3 [ISSUES: JAR file is missing but POM file present]
    |__ com.anypoint:common:1.0
        |__ org.slf4j:slf4j-api:1.7.30
```

### JSON Dependency Tree (`dependencyTree_YYYY-MM-DDTHH:MM:SS.FFF.json`)

```json
{
  "metadata": {
    "generated": "2024-01-15T10:30:45.123456",
    "totalLibraries": 1500,
    "librariesWithIssues": 5
  },
  "rootLibraries": [
    {
      "library": "org.springframework:spring-core:5.3.0",
      "version": "5.3.0",
      "filePath": "/Users/username/.m2/repository/org/springframework/spring-core/5.3.0",
      "issues": [],
      "error": null,
      "parentLibrary": null,
      "transitiveLibraries": [...],
      "parentLibraryPath": "org.springframework:spring-core:5.3.0",
      "dependencies": [...]
    }
  ],
  "allLibraries": [...]
}
```

### Issue-Specific Files

For each detected issue type, a separate file is generated:

- `dependencyTree_POM_file_is_missing_YYYY-MM-DDTHH:MM:SS.FFF.txt`
- `dependencyTree_JAR_file_is_missing_but_POM_file_present_YYYY-MM-DDTHH:MM:SS.FFF.txt`
- `dependencyTree_HTML_only_content_YYYY-MM-DDTHH:MM:SS.FFF.txt`
- etc.

## Issue Types

The tool detects and reports the following issues:

| Issue | Description |
|-------|-------------|
| `POM file is missing` | No POM file found for the library |
| `JAR file is missing but POM file present` | POM exists but no JAR file (may be legitimate for POM-only packages) |
| `JAR file and POM file are missing` | Neither file exists |
| `HTML only content` | POM file contains HTML instead of XML |
| `Failed simple XML validation` | POM doesn't start with `<?xml` |
| `Failed XML XSD schema validation` | POM doesn't conform to Maven XSD schema |
| `JAR file is invalid` | JAR file is smaller than 5KB (likely corrupted) |
| `POM file is not valid Maven` | POM is valid XML but missing groupId, artifactId, or version |

## Architecture

The tool is organized into several modules:

```
maven_repo_scraper/
├── __init__.py          # Package initialization
├── config.py            # Configuration management
├── logger.py            # Logging system
├── pom_parser.py        # POM file parsing and validation
├── repository_client.py # HTTP client for repositories
├── dependency_resolver.py # Dependency resolution
├── output_generator.py  # Output file generation
├── local_repository.py  # Local repository management
└── main.py             # Main application logic
```

### Key Classes

- **ScraperConfig**: Manages all configuration settings
- **MavenScraperLogger**: Comprehensive logging with file and console output
- **POMParser**: Parses and validates POM files
- **RepositoryClient**: Handles HTTP communication with Maven repositories
- **MultiRepositoryClient**: Coordinates access to multiple repositories
- **DependencyResolver**: Resolves parent and transitive dependencies
- **OutputGenerator**: Generates text and JSON output files
- **LocalRepositoryManager**: Manages the local Maven repository

## Extending the Tool

### Adding a New Repository Type

1. Create a new `RepositoryClient` subclass
2. Override `list_directory()` and related methods
3. Register the repository in the configuration

### Adding a New Issue Type

1. Add the issue constant to `IssueType` class in `pom_parser.py`
2. Implement detection logic in `POMParser.check_library_issues()`
3. Update output generators to handle the new issue

### Customizing Output

1. Subclass `DependencyTreeWriter`
2. Override formatting methods
3. Register with `OutputGenerator`

## Troubleshooting

### Common Issues

**XSD validation fails**
- Ensure `lxml` is installed: `pip install lxml`
- Check internet connection (XSD is downloaded on first run)
- Try simple validation: `--xml-validation simple`

**Download timeouts**
- Increase timeout: `--timeout 600`
- Check network connectivity
- Check repository availability

**Memory issues with large repositories**
- Process in smaller batches
- Reduce `--max-depth`
- Use `--dry-run` first to estimate scope

**Permission denied errors**
- Check write permissions for local repository
- Check output directory permissions
- Run with appropriate user permissions

**Library discovery shows 0 libraries**
- Some Maven repositories require specific API access or have anti-scraping measures
- Use `--local-only` mode if you already have a local repository
- For Maven Central, consider using a mirror or specific library URLs
- The MuleSoft Nexus repository may require different authentication

**Note on Full Repository Scraping**: Scraping entire Maven Central or similar large repositories is resource-intensive and may take a very long time. The tool is best used for:
1. Scanning your existing local repository (`--local-only`)
2. Scraping specific smaller repositories
3. Maintaining an existing local repository cache

## License

MIT License

## Contributing

Contributions are welcome! Please read the contributing guidelines before submitting pull requests.

## Support

For issues and feature requests, please open an issue on the project repository.