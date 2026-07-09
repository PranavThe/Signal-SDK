# Semantic Matching Bug Fix - Critical

## Date: 2026-07-09

## The Bug

**Severity:** CRITICAL
**Impact:** Escalations were being auto-resolved by rules that didn't actually match their structured conditions

### What Happened

A user escalated with action: `waive_or_reverse_customer_fee`

Signal auto-resolved it with a rule that had the condition:
```
action.slug eq check_account_for_unauthorized_transactions
```

**These are completely different actions!** The rule should NOT have matched.

### Root Cause

The semantic matching system was finding rules with similar *overall context* (banking, unauthorized transactions, etc.) but **NOT validating that the structured field conditions actually matched**.

#### The Problematic Code

**File:** `api/routers/escalations.py:157-158` (before fix)
```python
if semantic_match is not None:
    matched_rule, semantic_similarity = semantic_match  # ← Just accepted it!
```

**File:** `api/routers/check.py:87-88` (before fix)
```python
if semantic_match is not None:
    matched_rule, semantic_similarity = semantic_match  # ← Same bug
```

The system would:
1. Find a semantically similar rule (45% in this case, threshold is 35%)
2. **Immediately accept it without validating structured conditions**
3. Auto-resolve the escalation incorrectly

---

## The Fix

Added validation to ensure semantically matched rules actually have matching structured conditions:

### File: `api/routers/escalations.py`

```python
if semantic_match is not None:
    candidate_rule, semantic_similarity = semantic_match
    # CRITICAL: Validate that the semantically matched rule's structured conditions
    # actually match the context. Semantic matching finds similar *situations*,
    # but we must verify the exact field conditions (especially action fields).
    from api.rule_engine import rule_matches
    if rule_matches(candidate_rule, context_result.normalized):
        matched_rule = candidate_rule
    else:
        # Log that semantic match was rejected due to condition mismatch
        logger.info(
            f"Semantic match rejected: Rule {candidate_rule.id} matched semantically "
            f"({semantic_similarity * 100:.0f}%) but structured conditions don't match. "
            f"Rule conditions: {candidate_rule.structured_conditions}"
        )
        semantic_similarity = None  # Clear semantic similarity since we rejected it
```

### File: `api/routers/check.py`

Same fix applied to the `/check` endpoint.

---

## How It Works Now

1. **Semantic matching finds a candidate** (e.g., 45% similarity)
2. **Validate structured conditions** using `rule_matches()`
   - Check ALL conditions: `action.slug`, `risk.level`, `channel`, etc.
   - ALL must match exactly per the rule's operators (`eq`, `gt`, `contains`, etc.)
3. **Only if validation passes**, accept the semantic match
4. **If validation fails**, log rejection and continue (escalation goes to human)

---

## Why This Happened

Semantic matching was designed to find similar **situations** (questions, contexts, patterns), but it should have ALWAYS validated structured conditions before auto-resolving.

The bug was introduced because the semantic match flow bypassed the normal `rule_matches()` validation that exact matches go through.

---

## Impact

### Before Fix:
- ❌ Rules could auto-resolve escalations with **different action fields**
- ❌ 35% semantic similarity was enough to bypass structured validation
- ❌ Users saw confusing auto-resolutions like the reported case
- ❌ Rules meant for specific actions were matching unrelated actions

### After Fix:
- ✅ Semantic matches must ALSO pass structured condition validation
- ✅ Action fields must match exactly (per the rule's operator)
- ✅ All rule conditions validated before auto-resolving
- ✅ Rejected semantic matches are logged for debugging

---

## Testing

### Test Case: The Reported Bug

**Escalation:**
```json
{
  "action": "waive_or_reverse_customer_fee",
  "context": {
    "banking.support.intent": "cards",
    "risk.level": "high",
    "channel": "local-chat-ui"
  }
}
```

**Rule Conditions:**
```json
[
  {"field": "banking.support.intent", "operator": "eq", "value": "cards"},
  {"field": "risk.level", "operator": "eq", "value": "high"},
  {"field": "action.slug", "operator": "eq", "value": "check_account_for_unauthorized_transactions"},
  {"field": "channel", "operator": "eq", "value": "local-chat-ui"}
]
```

**Before Fix:**
- Semantic similarity: 45%
- Result: ✅ **Auto-resolved** (WRONG!)
- Reason: First 2 conditions matched, semantic similarity > 35%, so it was accepted

**After Fix:**
- Semantic similarity: 45%
- Structured validation: ❌ FAIL (action.slug doesn't match)
- Result: ⏸️ **Escalated to human** (CORRECT!)
- Log: "Semantic match rejected: Rule {id} matched semantically (45%) but structured conditions don't match"

---

## Files Changed

1. `/Users/pranavpuranik/Signal/api/routers/escalations.py:144-178`
2. `/Users/pranavpuranik/Signal/api/routers/check.py:77-104`

---

## Deployment

**Status:** ✅ Fixed in development
**Next Step:** Deploy to production immediately

This is a critical bug fix that prevents incorrect auto-resolutions. It should be deployed ASAP.

---

## Lessons Learned

1. **All matching paths must validate structured conditions** - Whether exact or semantic, structured conditions must be validated
2. **Semantic matching is for discovery, not decision** - It finds similar situations, but exact validation is still required
3. **Action fields are critical** - Different actions should NEVER match, even with high semantic similarity
4. **Low thresholds are dangerous** - 35% semantic similarity is too low without proper validation

---

## Recommendations

### Short Term:
1. ✅ Deploy this fix immediately
2. Review recent auto-resolved escalations for incorrect matches
3. Consider raising `SEMANTIC_RULE_MATCH_THRESHOLD` from 0.35 to 0.42+ (strong match threshold)

### Long Term:
1. Add integration tests for semantic matching with mismatched actions
2. Add dashboard alert for rejected semantic matches
3. Consider making semantic matching opt-in per rule (flag: `allow_semantic_match`)
4. Add telemetry to track semantic match accept/reject rates
