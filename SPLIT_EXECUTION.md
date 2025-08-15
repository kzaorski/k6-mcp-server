# Split Execution: Confirm and Execute Test

## Przegląd

System K6 MCP Server został zmodyfikowany w celu rozdzielenia procesu potwierdzania i wykonania testów na dwie oddzielne operacje dla lepszej kontroli i bezpieczeństwa.

## Nowe Narzędzia MCP

### 1. `confirm_test`
**Opis:** Potwierdza oczekujący test z odpowiedzią y/n  
**Parametry:**
- `response`: "y", "n", "yes", lub "no"

**Działanie:**
- Sprawdza czy istnieje test oczekujący na potwierdzenie
- Przy "y/yes": przenosi test do stanu potwierdzonego
- Przy "n/no": anuluje test i czyści stan oczekujący  
- Zwraca instrukcje dla następnego kroku

### 2. `execute_confirmed_test`
**Opis:** Wykonuje wcześniej potwierdzony test  
**Parametry:** Brak

**Działanie:**
- Sprawdza czy istnieje potwierdzony test gotowy do wykonania
- Wykonuje test K6 lub workflow
- Czyści stan potwierdzonego testu po wykonaniu
- Zwraca wyniki testu

## Przepływ Pracy

### Stary sposób (wciąż obsługiwany):
```
1. run_k6_test → przygotowuje test
2. confirm_and_execute_test → potwierdza I wykonuje w jednym kroku
```

### Nowy sposób (zalecany):
```
1. run_k6_test → przygotowuje test  
2. confirm_test → potwierdza test (tylko potwierdzenie)
3. execute_confirmed_test → wykonuje potwierdzony test
```

## Przykłady Użycia

### Test pojedynczego żądania:
```json
// Krok 1: Przygotowanie
{
  "tool": "run_k6_test",
  "arguments": {
    "url": "https://api.example.com/test",
    "method": "GET",
    "iterations": 1,
    "virtual_users": 1
  }
}

// Krok 2: Potwierdzenie  
{
  "tool": "confirm_test",
  "arguments": {
    "response": "y"
  }
}

// Krok 3: Wykonanie
{
  "tool": "execute_confirmed_test",
  "arguments": {}
}
```

### Test workflow:
```json
// Krok 1: Przygotowanie workflow
{
  "tool": "run_k6_multi_request_test", 
  "arguments": {
    "workflow_name": "user_journey",
    "steps": [...]
  }
}

// Krok 2: Potwierdzenie
{
  "tool": "confirm_test",
  "arguments": {
    "response": "y"  
  }
}

// Krok 3: Wykonanie
{
  "tool": "execute_confirmed_test",
  "arguments": {}
}
```

## Stany Zarządzania

### K6Runner:
- `pending_config`: Test oczekujący na potwierdzenie
- `confirmed_config`: Test potwierdzony i gotowy do wykonania  
- `last_result`: Wyniki ostatniego wykonanego testu

### WorkflowManager:
- `pending_workflow`: Workflow oczekujący na potwierdzenie
- `confirmed_workflow`: Workflow potwierdzony i gotowy do wykonania
- `workflow_results`: Wyniki wykonanych workflow

## Metody Sprawdzania Stanu

### K6Runner:
- `is_confirmed()` → bool: czy jest potwierdzony test
- `confirm_test(response)` → str: potwierdza test
- `execute_confirmed_test()` → str: wykonuje potwierdzony test

### WorkflowManager:  
- `is_confirmed()` → bool: czy jest potwierdzony workflow
- `confirm_workflow(response)` → str: potwierdza workflow
- `execute_confirmed_workflow()` → str: wykonuje potwierdzony workflow

## Bezpieczeństwo

### Zalety rozdzielenia:
1. **Wyraźne intencje:** Użytkownik musi jawnie potwierdzić i następnie wykonać
2. **Lepsza kontrola:** Możliwość anulowania przed wykonaniem
3. **Auditowanie:** Jasne ślady decyzji użytkownika  
4. **Elastyczność:** Można dodać dodatkowe kroki między potwierdzeniem a wykonaniem

### Zabezpieczenia:
- Testy nie są wykonywane automatycznie po potwierdzeniu
- Stan potwierdzonego testu jest tymczasowy
- Wykonanie wymaga oddzielnego wywołania narzędzia
- Wszystkie operacje są logowane

## Kompatybilność Wsteczna

### Legacy metoda `confirm_and_execute_test`:
- Wciąż dostępna dla zgodności z istniejącym kodem
- Wewnętrznie używa nowych metod split
- Auto-wykonuje po potwierdzeniu dla zachowania starego zachowania

### Legacy metody w klasach:
- `confirm_test_execution()` w K6Runner
- `confirm_workflow_execution()` w WorkflowManager  
- Przekierowują do nowych metod split

## Migracja

### Dla nowych implementacji:
Używaj nowych narzędzi `confirm_test` + `execute_confirmed_test`

### Dla istniejących implementacji:
Kod używający `confirm_and_execute_test` będzie działał bez zmian

## Przydatne Komendy

### Sprawdzenie stanu:
```python
# K6Runner
runner.is_confirmed()  # → True/False
runner.pending_config  # → dict lub None
runner.confirmed_config  # → dict lub None

# WorkflowManager  
workflow_manager.is_confirmed()  # → True/False
workflow_manager.pending_workflow  # → dict lub None
workflow_manager.confirmed_workflow  # → dict lub None
```

### Debugging:
```python
# Wyczyść wszystkie stany
runner.pending_config = None
runner.confirmed_config = None
workflow_manager.pending_workflow = None
workflow_manager.confirmed_workflow = None
```