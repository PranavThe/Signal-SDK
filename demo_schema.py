"""
Demonstration of schema-first context normalization.

This shows how defining a schema upfront eliminates field naming ambiguity.
"""
import asyncio
from signalops import Signal, Field

# User defines their schema ONCE upfront
VULNERABILITY_SCHEMA = [
    # Vulnerability fields
    Field("vulnerability.cvss.score", type="number"),
    Field("vulnerability.severity", type="string"),
    Field("vulnerability.name", type="string"),
    Field("vulnerability.cves", type="array"),
    Field("vulnerability.cwes", type="array"),

    # Dependency fields
    Field("dependency.name", type="string"),
    Field("dependency.ecosystem", type="string"),
    Field("dependency.direct", type="boolean"),
    Field("dependency.scope", type="string"),
    Field("dependency.installed.version", type="string"),
    Field("dependency.fixed.versions", type="array"),

    # CISA KEV fields
    Field("cisa.kev.known.ransomware.campaign.use", type="boolean"),
    Field("cisa.kev.date.added", type="string"),
]


async def main():
    signal = Signal(
        api_key="test-key",
        base_url="http://localhost:8000",
        dev_mode=True,
        schema=VULNERABILITY_SCHEMA,  # Pass schema to Signal
    )

    print("=" * 80)
    print("DEMONSTRATION: Schema-First Context Normalization")
    print("=" * 80)
    print()

    # Example 1: Sloppy context from CVE-2021-44228
    print("Example 1: CVE-2021-44228 with sloppy field names")
    print("-" * 80)

    sloppy_context_1 = {
        "cves": "CVE-2021-44228",  # Missing "vulnerability." prefix
        "cwes": "['CWE-20', 'CWE-400', 'CWE-502']",  # Wrong format (string not array)
        "severity": "CRITICAL",
        "cvss.score": 10,  # Partial path
        "direct.dependency": "yes",  # Wrong order + string instead of boolean
        "installed.version": "2.14.1",
        "dependency.name": "org.apache.logging.log4j:log4j-core",
        "dependency.ecosystem": "Maven",
        "scope": "runtime",
        "known.ransomware.campaign.use": "Known",  # String instead of boolean
    }

    from signalops import normalize_context
    normalized_1, warnings_1 = normalize_context(sloppy_context_1, schema=VULNERABILITY_SCHEMA)

    print("Input (sloppy):")
    for key, value in sloppy_context_1.items():
        print(f"  {key}: {value} ({type(value).__name__})")

    print()
    print("Output (normalized):")
    for key, value in sorted(normalized_1.items()):
        print(f"  {key}: {value} ({type(value).__name__})")

    print()
    print(f"Warnings: {len(warnings_1)}")
    for warning in warnings_1:
        print(f"  - {warning}")

    print()
    print()

    # Example 2: Different sloppy variation for CVE-2021-45046
    print("Example 2: CVE-2021-45046 with different sloppy field names")
    print("-" * 80)

    sloppy_context_2 = {
        "vulnerability.cves": "CVE-2021-45046",  # Full path
        "vulnerability.cwes": "CWE-917",  # Full path but string not array
        "severity": "CRITICAL",
        "cvssScore": 9,  # CamelCase variation
        "directDependency": "yes",  # CamelCase variation
        "installedVersion": "2.14.1",  # CamelCase
        "dependencyName": "org.apache.logging.log4j:log4j-core",
        "ecosystem": "Maven",  # Partial path
        "scope": "runtime",
        "kev.known.ransomware.campaign.use": "Known",
    }

    normalized_2, warnings_2 = normalize_context(sloppy_context_2, schema=VULNERABILITY_SCHEMA)

    print("Input (sloppy):")
    for key, value in sloppy_context_2.items():
        print(f"  {key}: {value} ({type(value).__name__})")

    print()
    print("Output (normalized):")
    for key, value in sorted(normalized_2.items()):
        print(f"  {key}: {value} ({type(value).__name__})")

    print()
    print(f"Warnings: {len(warnings_2)}")

    print()
    print()

    # Example 3: Show that both normalize to THE SAME fields
    print("Example 3: Verification - Both contexts normalize to same field names")
    print("-" * 80)

    common_fields = set(normalized_1.keys()) & set(normalized_2.keys())
    print(f"Common fields between both examples: {len(common_fields)}")
    for field in sorted(common_fields):
        val1 = normalized_1[field]
        val2 = normalized_2[field]
        match = "✓" if type(val1) == type(val2) else "✗"
        print(f"  {match} {field}: {type(val1).__name__} vs {type(val2).__name__}")

    print()
    print("=" * 80)
    print("KEY INSIGHT: No matter how sloppy the input, all variations map to")
    print("the SAME canonical field names with the SAME types!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
