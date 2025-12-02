# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in MAMFast, please report it responsibly:

1. **Do NOT** open a public GitHub issue for security vulnerabilities
2. Email the maintainers directly or use GitHub's private vulnerability reporting feature
3. Include as much detail as possible:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a more detailed response within 7 days.

## Security Considerations

### Sensitive Data

MAMFast handles sensitive information that should **never** be committed to version control:

| Data | Location | Risk |
|------|----------|------|
| qBittorrent credentials | `config/.env` | Unauthorized access |
| API keys | `config/.env` | Service abuse |

### Best Practices

1. **Never commit `.env` files** - They are gitignored by default
2. **Use environment variables** in production/containerized deployments
3. **Restrict file permissions** on config files: `chmod 600 config/.env`
4. **Review `config.yaml`** before committing - ensure no secrets are embedded
5. **Use separate credentials** for MAMFast vs your main accounts when possible

### File Permissions

For Unraid/Linux deployments:

```bash
# Restrict access to secrets
chmod 600 config/.env
chmod 600 config/config.yaml

# Ensure proper ownership
chown $USER:$USER config/.env config/config.yaml
```

### Docker Security

If running in Docker:

- Mount config files as read-only when possible
- Use Docker secrets for sensitive values
- Don't expose qBittorrent WebUI to the internet without authentication

## Dependencies

We regularly update dependencies to patch known vulnerabilities. Run:

```bash
pip install --upgrade -e ".[dev]"
```

To check for known vulnerabilities in dependencies:

```bash
pip install pip-audit
pip-audit
```
