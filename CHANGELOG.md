# Changelog

All notable changes to MAMFast will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Comprehensive configuration validation** - All required environment variables and configuration values are now validated at startup with helpful error messages
  - Validates URLs are well-formed
  - Checks that required paths exist
  - Validates numeric ranges for configuration values
  - Provides actionable troubleshooting guidance when validation fails

- **Enhanced error messages** - All error messages now include:
  - Context about what failed and why
  - Relevant configuration values
  - Step-by-step troubleshooting instructions
  - Command examples to diagnose and fix issues

- **Atomic state file writes** - State files are now written atomically using temporary files and atomic rename operations
  - Prevents corruption if the process crashes during write
  - Automatic cleanup of temporary files on error

- **Configurable discovery patterns** - Folder parsing patterns, ASIN validation, and metadata file suffixes are now configurable via `libation` section in `config.yaml`
  - `folder_pattern`: Regex for parsing Libation folder names
  - `metadata_file_suffix`: Filename suffix for metadata files
  - `asin_pattern`: Regex pattern for validating ASINs

- **Progress indicators** - Rich progress bars now display during long-running operations
  - Shows current release being processed
  - Displays progress percentage and estimated time remaining
  - Includes elapsed time tracking

- **Integration tests** - Comprehensive integration tests covering:
  - Full pipeline execution
  - Error handling and recovery
  - Configuration validation
  - Atomic state file writes

### Changed

- **Improved qBittorrent error handling** - Connection and authentication failures now provide specific troubleshooting steps
- **Better torrent creation errors** - mkbrr failures include Docker image verification steps and path mapping diagnostics

### Fixed

- Fixed race condition in state file writes by using atomic rename operations
- Fixed indentation issues in dry-run output

## [0.1.0] - 2025-11-30

### Added

- Initial release
- Libation integration for audiobook scanning
- Smart staging with MAM-compliant naming
- Japanese transliteration support
- Metadata enrichment from Audnex API and MediaInfo
- Torrent creation via mkbrr Docker integration
- qBittorrent upload automation
- State tracking to prevent reprocessing
- Retry logic with exponential backoff
- Comprehensive test suite (137 tests)
- CI/CD pipeline with GitHub Actions
- Pre-commit hooks for code quality
