"""
Dependency security audit script for Model Router.

Checks all installed dependencies against known CVE databases.
Run manually:  python scripts/security_audit.py
Run in CI:     python scripts/security_audit.py --ci

Tools used:
  - pip-audit: checks against OSV / PyPI advisory database
  - safety:    another CVE checker
  - bandit:    static security analysis for source code
"""

import subprocess
import sys
import json
from datetime import datetime


def run_cmd(cmd: list[str], description: str) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] Exit code: {result.returncode}")
        if output.strip():
            print(output[:2000])
        return success, output
    except FileNotFoundError:
        msg = f"Tool not found: {cmd[0]}. Install with: pip install {' '.join(cmd)}"
        print(f"  [SKIP] {msg}")
        return False, msg
    except subprocess.TimeoutExpired:
        msg = f"Command timed out after 120s"
        print(f"  [TIMEOUT] {msg}")
        return False, msg


def main():
    """Run all security checks."""
    print(f"Model Router — Security Audit")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Python: {sys.version}")
    
    ci_mode = "--ci" in sys.argv
    results = {}
    
    # 1. pip-audit: check installed packages for known CVEs
    success, output = run_cmd(
        [sys.executable, "-m", "pip_audit", "--format", "json", "--progress-spinner", "off"],
        "pip-audit: CVE check for installed packages"
    )
    results["pip-audit"] = {"passed": success, "output": output}
    
    # 2. safety check: another CVE database
    success, output = run_cmd(
        [sys.executable, "-m", "safety", "check", "--output", "text"],
        "safety: CVE check (alternative database)"
    )
    results["safety"] = {"passed": success, "output": output}
    
    # 3. bandit: static security analysis for source code
    success, output = run_cmd(
        [sys.executable, "-m", "bandit", "-r", "model_router/", "-f", "screen", "-q"],
        "bandit: Static security analysis for source code"
    )
    results["bandit"] = {"passed": success, "output": output}
    
    # Summary
    print(f"\n{'='*60}")
    print(f"  SECURITY AUDIT SUMMARY")
    print(f"{'='*60}")
    
    all_passed = True
    for tool, result in results.items():
        status = "PASS" if result["passed"] else "FAIL"
        icon = "+" if result["passed"] else "!"
        print(f"  [{icon}] {tool}: {status}")
        if not result["passed"]:
            all_passed = False
    
    print(f"\n{'='*60}")
    if all_passed:
        print("  ALL CHECKS PASSED")
    else:
        print("  SOME CHECKS FAILED — review output above")
        if ci_mode:
            print("  CI mode: failing the build")
            sys.exit(1)
        else:
            print("  Run 'pip install -e \".[security]\"' to install audit tools")
    print(f"{'='*60}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
