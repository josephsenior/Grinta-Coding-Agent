# Confirmation Dialog Autonomy Fix - Architectural Summary

## Problem Statement

Users reported that the confirmation dialog was appearing intermittently even when autonomy mode was set to "full" in the TUI. This was a persistent bug that previous fixes failed to resolve.

## Root Cause Analysis

The system had **two independent confirmation layers** that could both set `AWAITING_CONFIRMATION`:

### Layer 1: Orchestration (SafetyService)
- **Location**: `backend/orchestration/services/safety_service.py`
- **Responsibility**: Policy decision layer
- **Behavior**: Correctly checks autonomy level and sets confirmation state
- **Status**: ✅ Working correctly

### Layer 2: Runtime (SecurityEnforcementMixin)
- **Location**: `backend/execution/security_enforcement.py`
- **Responsibility**: Execution + safety enforcement
- **Behavior**: Independently re-evaluated risk and could override Layer 1's decision
- **Status**: ❌ **BUG** - Did not check autonomy level, causing intermittent confirmation dialogs

### Why Intermittent?

The event stream serializes/deserializes actions (`event_to_dict` → `event_from_dict`), creating a NEW object. Layer 1 set `CONFIRMED` on the original object, but Layer 2 could override this on the deserialized copy, especially under race conditions between:
- Autonomy level changes
- Action evaluation
- Serialization/deserialization
- Runtime processing

## Architectural Fix

### Design Principle: Single Source of Truth

**Confirmation policy should be decided in ONE place only.**

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: Orchestration (Policy Decision)                  │
│ - ONLY place that sets confirmation state                 │
│ - Checks autonomy, action type, risk                      │
│ - Decides: CONFIRMED, AWAITING_CONFIRMATION, or proceed   │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: Runtime (Execution + Safety Net)                 │
│ - Reads confirmation state (never sets AWAITING_CONFIRMATION) │
│ - Can BLOCK dangerous actions (ErrorObservation)          │
│ - Can execute or skip based on confirmation state         │
│ - NEVER makes confirmation policy decisions               │
└─────────────────────────────────────────────────────────┘
```

### Changes Made

#### 1. Removed Confirmation Policy from Runtime
**File**: `backend/execution/security_enforcement.py`

- **Removed**: `require_confirmation` field from `SecurityPolicyDecision` dataclass
- **Removed**: `_is_full_autonomy()` helper method (no longer needed)
- **Simplified**: `_enforce_security()` to only handle blocking, not confirmation
- **Removed**: Logic that set `action.confirmation_state = AWAITING_CONFIRMATION`
- **Kept**: Hardcoded safety blocks that are active in runtime security policy (critical commands, hardened-local sensitive paths)
- **Kept**: Configurable blocking (`block_high_risk`)
- **Kept**: `_check_action_confirmation()` that reads state and blocks execution

#### 2. Updated Tests
**File**: `backend/tests/unit/execution/test_security_enforcement.py`

- **Updated**: `test_high_risk_requires_confirmation` → `test_high_risk_not_blocked_when_block_high_disabled`
- **New behavior**: Verifies that high-risk actions proceed when `block_high_risk=False`
- **Removed**: Assertions about `AWAITING_CONFIRMATION` being set by runtime

### What's Preserved

✅ **All safety guarantees remain intact:**
- Hardcoded blocks (critical commands, hardened-local sensitive paths like `.env`, `.ssh`)
- Configurable blocking (`block_high_risk` config)
- Execution gating (reads confirmation state, blocks if `AWAITING_CONFIRMATION`)
- Security risk analysis (shared analyzer used by both layers)

✅ **Autonomy mode works correctly:**
- Full autonomy: No confirmation dialogs (Layer 1 sets CONFIRMED, Layer 2 doesn't override)
- Conservative/Balanced: Confirmation dialogs as configured (Layer 1 sets AWAITING_CONFIRMATION)

### Benefits

1. **Single Responsibility**: Orchestration owns policy, Runtime owns execution
2. **No Race Conditions**: No sync issues between layers
3. **Simpler Mental Model**: "Orchestration decides, Runtime enforces"
4. **Easier to Test**: One place to verify confirmation logic
5. **Future-Proof**: Adding new autonomy levels or confirmation rules only requires updating Layer 1

## Test Results

All related tests pass:
- ✅ 21 security enforcement tests
- ✅ 306 orchestration/confirmation/autonomy tests
- ✅ 1366 execution tests

## Files Modified

1. `backend/execution/security_enforcement.py` - Removed confirmation policy logic
2. `backend/tests/unit/execution/test_security_enforcement.py` - Updated test to reflect new architecture

## Migration Notes

No migration needed. This is a pure architectural refactor with no API changes.

## Verification

To verify the fix works:
1. Set autonomy to "full" in TUI
2. Execute high-risk actions (e.g., `rm -rf /tmp/test`)
3. Confirm no confirmation dialog appears
4. Verify action executes successfully

To verify safety is preserved:
1. Enable `block_high_risk` in config
2. Execute high-risk actions
3. Confirm actions are blocked with `ErrorObservation`
4. Verify hardcoded blocks still work (e.g., critical command refusal and hardened-local sensitive paths)
