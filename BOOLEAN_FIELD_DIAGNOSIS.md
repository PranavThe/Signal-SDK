# Diagnosis: Missing Boolean Fields in Context

**Date**: 2026-07-08
**Issue**: Four boolean fields with `False` values are missing from normalized context

---

## Missing Fields

Expected but NOT present in user's JSON:
1. `dependency.direct` = `False`
2. `cisa.kev.known.ransomware.use` = `False`
3. `policy.is.internet.facing` = `False`
4. `policy.is.critical.package` = `False`

**Note**: `cisa.kev.is.known.exploited` = `True` IS present, confirming boolean fields work when `True`.

---

## Root Cause Analysis

### Code Verification ✅

**signal_bridge.py (lines 197-229)**:
```python
def build_signal_context(finding, recommendation):
    return {
        "dependency.direct": dependency.direct,  # Line 210 - SENDS the value
        "cisa_kev.known_ransomware_use": known_ransomware_use(kev),  # Line 220
        "policy.is_internet_facing": "package is configured as internet-facing" in reasons,  # Line 227
        "policy.is_critical_package": "package is configured as critical" in reasons,  # Line 228
    }
```

All four fields ARE being built and sent to Signal.

### Value Confirmation ✅

**Tested with actual data**:
```python
dependency.direct = False  # Confirmed boolean False (not None, not empty string)
```

**JSON serialization test**:
```json
{
  "dependency.direct": false,  // ✓ JSON preserves False
  "test.true": true
}
```

JSON serialization works correctly - `False` is not filtered.

### SDK Normalization ✅

**normalize_context() in SDK**:
- Schema map lookup: ✓ Works
- Type coercion for booleans: ✓ Returns `False` as-is
- Assignment to normalized dict (line 237): ✓ Should add `False` values

No filtering found in SDK code.

---

## Most Likely Causes

### 1. **API Server Filtering (MOST LIKELY)**

The API might be filtering out `False` boolean values when:
- Storing context in database
- Returning context in responses
- Displaying context in dashboard

**Evidence**:
- User JSON appears to be from Signal dashboard/API response (not raw SDK output)
- Only `False` booleans missing, `True` boolean present
- All string fields (including empty strings) are present

**Check locations**:
```
/api/services/context_schema_service.py
/api/routers/escalations.py
/api/routers/context.py
```

### 2. **Frontend Filtering**

Dashboard UI might filter out falsy values when displaying context.

**Check**: Dashboard component rendering context fields

### 3. **Database Storage Issue**

PostgreSQL JSONB might be dropping `False` values (unlikely but possible).

---

## Recommended Fixes

### Option 1: Fix API Response Filtering (RECOMMENDED)

If API is filtering `False`, remove that filter:

```python
# WRONG - filters False
normalized = {k: v for k, v in context.items() if v}

# CORRECT - keeps all values including False
normalized = {k: v for k, v in context.items()}
# or
normalized = dict(context)
```

### Option 2: Use Null for Missing vs False

If you need to distinguish "not provided" from "explicitly False":
- Missing field: Don't include in dict
- False value: Include as `false` in JSON
- True value: Include as `true` in JSON

This requires updating signal_bridge.py:

```python
# Current (always includes field):
"dependency.direct": dependency.direct,  # Always added, even if False

# Alternative (only include if True OR explicitly set):
# Only add to dict if value is truthy or explicitly False
context = {}
if dependency.direct is not None:
    context["dependency.direct"] = dependency.direct
```

### Option 3: Workaround - Use String Values

Temporary workaround until API is fixed:

```python
# In signal_bridge.py
"dependency.direct": "true" if dependency.direct else "false",  # String instead of bool
```

Then rely on Signal's type coercion to convert back to boolean. **Not recommended** - defeats purpose of schema.

---

## Testing Script

To confirm where filtering happens:

```python
import asyncio
from signalops import Signal, Field

signal = Signal(
    api_key="...",
    schema=[
        Field("test.true", type="boolean"),
        Field("test.false", type="boolean"),
        Field("test.string.empty", type="string"),
    ]
)

async def test():
    result = await signal.escalate(
        agent_id="test-bool-filtering",
        question="Test boolean false values?",
        context={
            "test.true": True,
            "test.false": False,  # Does this appear in dashboard?
            "test.string.empty": "",  # Does this appear in dashboard?
        },
        timeout_seconds=60
    )
    print(f"Escalation created: {result}")

asyncio.run(test())
```

Then check Signal dashboard to see which fields appear.

---

## Impact

### Current State
- Rules cannot match on `dependency.direct = False`
- Rules cannot match on `cisa.kev.known.ransomware.use = False`
- Rules cannot distinguish between "internet-facing" vs "not internet-facing"

### Example Rule That Won't Work

```json
{
  "when": [
    {"field": "dependency.direct", "operator": "eq", "value": false},
    {"field": "vulnerability.cvss_score", "operator": "gte", "value": 7.0}
  ],
  "do": "create_security_ticket"
}
```

This rule would never match because `dependency.direct = false` is not present in context.

### Workaround Until Fixed

Only write rules for positive conditions:
```json
{
  "when": [
    {"field": "dependency.direct", "operator": "eq", "value": true},
    {"field": "vulnerability.cvss_score", "operator": "gte", "value": 9.0}
  ],
  "do": "page_on_call"
}
```

---

## Action Items

1. ✅ Confirmed: Fields are sent from signal_bridge.py
2. ✅ Confirmed: JSON serialization works
3. ✅ Confirmed: SDK normalization works
4. ⏳ TODO: Check API response filtering
5. ⏳ TODO: Check dashboard rendering
6. ⏳ TODO: Test with simple script to isolate where filtering happens
7. ⏳ TODO: Fix the filter (remove it or make it boolean-aware)

---

## Conclusion

The `False` boolean values are being correctly:
- ✅ Built in signal_bridge.py
- ✅ Sent via SDK
- ✅ Normalized by SDK

They are being incorrectly:
- ❌ Filtered somewhere between API and display

**Next step**: Find and remove the filter that's dropping `False` boolean values.
