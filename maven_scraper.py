#!/usr/bin/env python3
"""
Maven Repository Scraper and Maintenance Tool - CLI Entry Point

This is the main command-line interface for the Maven repository scraper.

Usage:
    python maven_scraper.py [options]
    
Examples:
    # Basic usage with default settings
    python maven_scraper.py
    
    # Add custom repositories
    python maven_scraper.py --add-repo https://my.repo.com/maven2
    
    # Use simple XML validation instead of XSD
    python maven_scraper.py --xml-validation simple
    
    # Custom output directory
    python maven_scraper.py --output-dir /path/to/output
    
    # Save configuration for later use
    python maven_scraper.py --save-config config.json
    
    # Dry run (show what would be done without downloading)
    python maven_scraper.py --dry-run

For more information:
    python maven_scraper.py --help
"""

import sys
import os

# Add the package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maven_repo_scraper.main import main

if __name__ == "__main__":
    main()