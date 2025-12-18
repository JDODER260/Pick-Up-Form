# Security Policy

## Supported Versions

The following versions of **Pick Up & Delivery** are currently supported with security updates:

| Version | Supported          | Support Ends     | Notes                           |
| ------- | ------------------ | ---------------- | ------------------------------- |
| 2.2.x   | ✅ Yes             | Active           | Current stable release          |
| 2.1.x   | ⚠️ Limited         | 2025-12-11       | Critical fixes only             |
| 1.3.0   | ⚠️ Limited         | 2025-12-10       | Critical fixes only             |
| 1.2.x   | ⚠️ Limited         | 2025-12-09       | Critical fixes only             |
| 1.1.x   | ❌ No              | 2025-12-04       | Not supported                   |
| < 1.1.6 | ❌ No              | 2025-05-24       | Not supported                   |

**Note:** Only the latest major version receives full security support. Users are strongly encouraged to update to the latest version.

## Reporting a Vulnerability

### 🚨 How to Report
If you discover a security vulnerability in **Pick Up & Delivery**, please report it privately to maintain security:

**Primary Contact:** Judah Yoder  
**Email:** judah@doublersharpening.com  
**PGP Key:** [Available upon request]  

**Alternative Contact:**  
- Email: jdoder@jdswebsites.xyz  
- **Do NOT create a public GitHub issue** for security vulnerabilities

### 📋 What to Include
When reporting a vulnerability, please provide:
1. **Description** of the vulnerability
2. **Steps to reproduce** (if applicable)
3. **Impact assessment** (potential damage/risk)
4. **Version** of the app affected
5. **Environment** details (Android version, device model)
6. **Suggested fix** (if any)

### 🔒 Responsible Disclosure
We follow a **90-day responsible disclosure policy**:
- You report the vulnerability privately
- We acknowledge receipt within **48 hours**
- We investigate and provide initial assessment within **7 days**
- We work on a fix and keep you updated
- After fix is released, we coordinate public disclosure (if appropriate)
- We credit reporters (unless requested otherwise)

### 🕒 Response Timeline
- **48 hours**: Initial acknowledgment
- **7 days**: Initial assessment and severity classification
- **30 days**: Progress update and expected timeline
- **90 days**: Target for fix release (may vary based on complexity)

### 📦 Security Update Process
1. **Assessment**: Vulnerability is triaged and prioritized
2. **Fix Development**: Patch is created and tested
3. **Internal Review**: Security review of the fix
4. **Release**: New version is published with security fix
5. **Disclosure**: Coordinated disclosure after users have had time to update

## Security Practices

### 🔐 Data Protection
- **Local Storage**: All local data (POs, company info) is stored in app-private directories
- **Network Communication**: HTTPS-only for all API calls
- **Credentials**: No password storage; uses driver IDs for tracking
- **Permissions**: Minimum required permissions (Internet, Storage)

### 📱 App Security Features
- **Input Validation**: All user inputs are validated
- **File Access**: Sandboxed file operations
- **Certificate Pinning**: Optional for enterprise deployments
- **Regular Updates**: Security patches via version updates

### 🛡️ Android-Specific Protections
- **Target API**: Current Android security standards
- **Permissions**: Runtime permission requests where applicable
- **Storage**: Uses scoped storage (Android 10+)
- **Signing**: APK/AAB signed with secure keys

## Security Updates

### 📅 Update Schedule
- **Critical vulnerabilities**: Patched within 30 days
- **High severity**: Patched within 60 days
- **Medium severity**: Addressed in next scheduled release
- **Low severity**: Evaluated for next major release

### 📢 Update Notifications
Security updates are announced through:
1. **GitHub Releases** page
2. **App update mechanism** (when distributed via stores)
3. **Email alerts** for registered enterprise users

## Vulnerability Types of Interest

We are particularly interested in reports of:
- Remote code execution
- Authentication bypass
- Data leakage
- Privilege escalation
- Cryptographic weaknesses
- API security issues
- Local file inclusion
- Injection attacks

## Out of Scope

The following are generally out of scope:
- UI/UX bugs
- Feature requests
- Issues in dependencies (report to upstream)
- Social engineering
- Physical attacks
- TLS configuration of servers (report to server admin)

## Recognition

Security researchers who responsibly disclose vulnerabilities may be:
- Listed in our Security Hall of Fame (with permission)
- Given credit in release notes
- Offered a bounty (case-by-case basis for critical issues)

## Legal

### 📜 Safe Harbor
We will not initiate legal action against security researchers who:
- Make a good faith effort to avoid privacy violations
- Do not access or modify other users' data
- Give us reasonable time to address issues before public disclosure
- Comply with this security policy

### ⚖️ Compliance
This application complies with:
- General Data Protection Regulation (GDPR) principles
- California Consumer Privacy Act (CCPA) principles
- Industry-standard security best practices

## Contact

### 🎯 Primary Security Contact
**Judah Yoder**  
Security Lead, Double R Sharpening  
Email: Judah@doublersharpening.com  

### 📞 Emergency Contact
For urgent security matters outside business hours:  
**Phone:** +1 (814) 333-1181 (Office - business hours only)  

### 🌐 Additional Resources
- [GitHub Security Advisories](https://github.com/JDODER260/Pick-Up-Form/security/advisories)
- [Release Notes](https://github.com/JDODER260/Pick-Up-Form/releases)
- [Privacy Policy](https://doublersharpening.com/privacy) (if applicable)

---

*Last Updated: 2025-01-18*  
*Policy Version: 1.0*
