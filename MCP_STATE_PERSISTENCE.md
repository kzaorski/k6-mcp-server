# MCP State Persistence - Rozwiązanie Problemu Utraty Stanu

## Problem

Claude Desktop wywołuje narzędzia MCP jako oddzielne wywołania. Każde wywołanie `confirm_test` i następne `execute_confirmed_test` to nowe instancje, które nie zachowują lokalnego stanu między wywołaniami.

**Rezultat:** 
```
confirm_test("y") → ✅ Test confirmed
execute_confirmed_test() → ❌ "No confirmed test ready for execution"
```

## Rozwiązanie: Global State Persistence

Wprowadzono mechanizm **global_state** który przechowuje stan potwierdzonych testów między wywołaniami MCP na poziomie procesu serwera.

### Implementacja

#### 1. **Global State Storage**
```python
# W server.py na poziomie modułu
global_state = {
    'confirmed_test': None,      # Potwierdzony test K6
    'confirmed_workflow': None,  # Potwierdzony workflow
    'last_confirmation_time': None  # Timestamp potwierdzenia
}
```

#### 2. **Zapisywanie Stanu w confirm_test**
```python
elif name == "confirm_test":
    result = await k6_runner.confirm_test(response)
    
    # Save to global state for MCP persistence  
    if "confirmed and ready" in result:
        global_state['confirmed_test'] = k6_runner.confirmed_config
        global_state['last_confirmation_time'] = time.time()
        logger.info("Test confirmed and saved to global state")
```

#### 3. **Przywracanie Stanu w execute_confirmed_test**
```python
elif name == "execute_confirmed_test":
    # Check global state first (for MCP persistence)
    if global_state['confirmed_test'] is not None:
        # Restore test state and execute
        k6_runner.confirmed_config = global_state['confirmed_test']
        result = await k6_runner.execute_confirmed_test()
        # Clear global state after execution
        global_state['confirmed_test'] = None
        global_state['last_confirmation_time'] = None
```

## Przepływ Pracy

### **Bez Global State (poprzedni problem):**
```
MCP Call 1: confirm_test("y")
├─ Local instance: confirmed_config = {...}
└─ Return: "✅ Test confirmed"

MCP Call 2: execute_confirmed_test() 
├─ NEW instance: confirmed_config = None  ❌
└─ Return: "No confirmed test ready"
```

### **Z Global State (nowe rozwiązanie):**
```
MCP Call 1: confirm_test("y")
├─ Local: confirmed_config = {...}
├─ Global: global_state['confirmed_test'] = {...} ✅
└─ Return: "✅ Test confirmed"

MCP Call 2: execute_confirmed_test()
├─ NEW instance: confirmed_config = None
├─ Restore: confirmed_config = global_state['confirmed_test'] ✅
├─ Execute test
├─ Clear: global_state['confirmed_test'] = None
└─ Return: "✅ Test executed"
```

## Nowe Narzędzia MCP

### `check_confirmation_state`
**Cel:** Debug tool do sprawdzenia stanu potwierdzenia

**Użycie:**
```json
{
  "tool": "check_confirmation_state",
  "arguments": {}
}
```

**Przykładowy Output:**
```
🔍 **Confirmation State Debug Report**

**Global State (MCP Persistence):**
• Confirmed Test: Yes
• Confirmed Workflow: None  
• Last Confirmation: 14:30:25

**Local State (Instance):**
• Confirmed Test: None
• Confirmed Workflow: None
• Pending Test: None 
• Pending Workflow: None

**Ready for Execution:**
• Global Ready: Yes
• Local Ready: No

**Next Steps:**
• Use execute_confirmed_test to run the confirmed test
```

## Obsługiwane Scenariusze

### 1. **Single Test**
```
run_k6_test → confirm_test("y") → execute_confirmed_test
```

### 2. **Multi-Request Workflow**  
```
run_k6_multi_request_test → confirm_test("y") → execute_confirmed_test
```

### 3. **Anulowanie**
```
run_k6_test → confirm_test("n") → [global state cleared]
```

### 4. **Debugging**
```
run_k6_test → confirm_test("y") → check_confirmation_state → execute_confirmed_test
```

## Backup Mechanisms

### 1. **Fallback do Local State**
```python
# Primary: Global state
if global_state['confirmed_test'] is not None:
    # Use global state
    
# Fallback: Local state (backward compatibility)
elif k6_runner.confirmed_config is not None:
    # Use local state
```

### 2. **State Cleanup**
- Global state jest czyszczony po wykonaniu testu
- Timeout można dodać w przyszłości dla expiry
- Local state pozostaje niezmieniony dla kompatybilności

### 3. **Logging**
```python
logger.info("Test confirmed and saved to global state")
logger.info("Test executed from global state") 
logger.info("Workflow executed from global state")
```

## Korzyści

✅ **Persistence Between MCP Calls** - Stan zachowuje się między wywołaniami  
✅ **Backward Compatibility** - Stary kod nadal działa  
✅ **Debug Support** - `check_confirmation_state` dla troubleshooting  
✅ **Automatic Cleanup** - Stan się czyści po wykonaniu  
✅ **Dual Support** - Obsługuje testy i workflows  
✅ **Fallback Safety** - Multiple mechanizmy zapewniające działanie

## Claude Desktop Experience

### **Poprzednio (nie działało):**
```
User: "Przetestuj stronę X"
Claude: [prepare test] "Czy chcesz uruchomić test?"
User: "tak" 
Claude: [confirm_test] "✅ Potwierdzono"
Claude: [execute_confirmed_test] "❌ No confirmed test ready"
```

### **Teraz (działa):**
```
User: "Przetestuj stronę X"  
Claude: [prepare test] "Czy chcesz uruchomić test?"
User: "tak"
Claude: [confirm_test] "✅ Potwierdzono" + [save to global_state]
Claude: [execute_confirmed_test] "✅ Test wykonany" + [restore from global_state]
```

Ta implementacja rozwiązuje podstawowy problem persistence stanu w architekturze MCP i umożliwia prawidłowe działanie interakcyjnego potwierdzania testów.