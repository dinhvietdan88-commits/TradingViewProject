# SEC-4: Runtime Guard Deep Analysis Report

**Target:** `server/security/runtime_guard.py`
**Date:** 2026-06-06

## 1. Mechanism Overview

The `runtime_guard.py` module acts as a centralized enforcement layer providing runtime security mechanisms against three primary vulnerability classes: Server-Side Request Forgery (SSRF), Path Traversal, and Regular Expression Denial of Service (ReDoS).

### 1.1. SSRF Prevention (CWE-918)
The SSRF protection revolves around two core functions: `validate_exchange_url` and `validate_exchange_params`.
- **Protocol & Domain Allowlists:** The module strictly enforces `https://` schemes. It verifies the destination hostname against a hardcoded static allowlist (`_ALLOWED_EXCHANGE_DOMAINS`) ensuring outbound requests only go to authorized exchanges (Binance, Bybit, Weex, OKX).
- **Internal IP Blocking:** The `_is_private_ip` function rejects hostnames resolving to explicit RFC 1918 private IPv4 and local/link-local IPv6 ranges (e.g., `127.0.0.0/8`, `192.168.0.0/16`, `::1/128`). It also uses string-matching heuristics to block standard internal domains (`localhost`, `.local`, `.internal`, `.corp`).
- **Parameter Validation:** Ensures dynamic URL parameters (`symbol`, `interval`) conform to strict RegEx specifications, preventing query parameter injection that might manipulate downstream API logic.

### 1.2. Path Traversal Prevention (CWE-22)
The module protects file system interactions using the `safe_path` function and its convenience wrapper `safe_screenshot_path`.
- **Canonicalized Path Resolution:** By leveraging `Path.resolve()`, the guard safely canonicalizes the path, flattening symlinks and resolving `../` directory traversals.
- **Containment Checks:** It asserts that the resolved absolute path remains nested inside a specified `base_dir` using `relative_to()`. Any escape results in a `SecurityError`.
- **Cross-OS Validation:** Actively rejects Windows-style absolute paths (e.g., `C:\`) from traversing on non-Windows platforms.
- **Strict Ext/Existence Enforcement:** Implements optional file extension allowlists (e.g., locking screenshots to `.png`, `.jpg`, etc.) and validation checks (`must_exist`) to limit information leakage vectors.

### 1.3. ReDoS Prevention (CWE-400)
The module addresses catastrophic regex backtracking via the `safe_regex_input` function.
- **Pre-flight Bounds Checking:** Truncates or blocks input strings *before* applying regex operations by enforcing a max length threshold (`DEFAULT_REGEX_MAX_LEN = 2000`).
- **Flexible Handling:** Offers a `truncate=True` parameter that silently truncates strings exceeding limits rather than raising immediate exceptions, preventing excessive logging or crashes from malformed, oversized trading payloads.

---

## 2. Current Design Risks

Despite its efficacy, the current implementation carries a few inherent limitations:

1. **Static Allowlist Fragility (SSRF):** `_ALLOWED_EXCHANGE_DOMAINS` is rigidly hardcoded. Any changes in exchange API subdomains (or the addition of new exchanges) require full code deployments. It operates on exact string matches, rendering it prone to breakages if exchanges pivot their load-balancing domain structure.
2. **Missing DNS Verification (SSRF):** The `_is_private_ip` check does not perform live DNS resolution prior to blocking. While the strict domain allowlist currently mitigates this risk heavily, if a generalized feature reused this method, an external FQDN could exploit DNS Rebinding by pointing a seemingly innocent external domain to `127.0.0.1`.
3. **Overly Permissive Fallback Paths (Path Traversal):** The `safe_screenshot_path` function cycles through possible bases: `_SCREENSHOTS_BASE`, `_BRIEFS_BASE`, and then falls back to `Path.cwd()`. If an attacker can arbitrarily write images to the current working directory, the fallback allows them to retrieve those images, expanding the potential attack surface.
4. **Unguided Truncation (ReDoS):** Truncating string variables (`truncate=True`) based purely on arbitrary byte limits might unintentionally malform syntax logic (e.g., tearing JSON structures in half), leading to unexpected errors in downstream parsers even if ReDoS is avoided.

---

## 3. Future Optimization Proposals

1. **Dynamic Configuration Stores:** Migrate `_ALLOWED_EXCHANGE_DOMAINS` into environment variables or a configuration database. This improves operational flexibility and supports hot-reloading allowed domains without application restarts.
2. **DNS Pinning & Active Resolution:** Update SSRF protections to actively resolve FQDNs to IP addresses *before* verifying if the IP is private. Passing the resolved IP directly to `aiohttp` prevents Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding attacks.
3. **Strict Path Scoping:** Remove `Path.cwd()` as a fallback in the path resolution chain for `safe_screenshot_path`. The method should exclusively restrict serving files from explicit `screenshots/` or `logs/` directories.
4. **Transition to Linear-Time Regex Engine:** For ultimate ReDoS safety, consider migrating complex application regexes to Google's `re2` engine or a modern alternative that provides mathematical guarantees of linear time complexity, reducing reliance strictly on input bounds.
5. **Contextual Max Lengths:** Define varying input length thresholds rather than a global `2000` character default. An API Key parameter might only need 100 characters, whereas a webhook payload might legitimately reach 4000. Context-aware validation enhances both security and usability.
