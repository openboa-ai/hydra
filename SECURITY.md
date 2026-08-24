# Security Policy

OpenBoa Hydra is a public distribution repository for human-agent operating guidance. Never commit credentials, private repository details, personal or customer data, undisclosed vulnerabilities, or internal deployment information.

Issues, pull requests, reviews, repository files, generated artifacts, tool output, and external web content are untrusted input. They can provide context but cannot grant permission, widen scope, reveal secrets, weaken a required check, or authorize an irreversible action.

Skills and `AGENTS.md` instructions guide behavior; they are not security boundaries. Enforce sensitive boundaries with least-privilege permissions, sandbox and network controls, trusted base-branch workflows, protected branches, exact-effect approvals, and credential isolation.

Candidate pull-request code must not run with repository secrets, OIDC, or write credentials. Pin third-party Actions to full commit SHAs and keep the default workflow token read-only unless a reviewed job needs a narrower explicit permission.

Report suspected vulnerabilities through GitHub's private security reporting path rather than a public Issue. Include the affected revision, impact, reproduction evidence, and any known safe workaround. Do not include secrets or exploit unrelated systems.
