# Windows Environment Fix - Rozwiązanie Problemów DNS w K6

## 🔍 Diagnoza Problemu

### Objawy:
- K6 test zwracał **czasy odpowiedzi 0.0ms**
- Logi K6 pokazywały **DNS lookup failures**:
  ```
  "error": "lookup clientconnector.pwc.pl: getaddrinfow: A non-recoverable error occurred during a database lookup."
  "error_code": "1100"
  "status": "0"
  ```
- K6 uruchamiany **bezpośrednio z Windows CMD działał perfectly** (94ms response time)

### Pierwotne Podejrzenia (błędne):
❌ Problem z DNS resolution  
❌ Problemy z template substitution  
❌ Błędy w parsing wyników K6  
❌ Problemy z K6 installation  

### Rzeczywista Przyczyna:
✅ **Hardcoded Linux environment variables** w `run_sandboxed_command()`:

```python
# ❌ PROBLEMATYCZNY KOD (tylko Linux):
env={
    'PATH': '/usr/local/bin:/usr/bin:/bin',  # Linux paths!
    'LANG': 'C.UTF-8',
    'HOME': '/tmp'
}
```

**Windows subprocess** otrzymywał Linux environment, co powodowało:
- Brak dostępu do Windows system libraries
- Nieprawidłowe DNS resolution
- Broken network stack dla subprocess

## 🔧 Rozwiązanie

### 1. **Nowa Function: `_get_safe_environment()`**

Cross-platform environment generation:

```python
def _get_safe_environment() -> Dict[str, str]:
    """Get a safe environment for subprocess execution that works cross-platform."""
    import platform
    import os
    
    # Base safe environment
    safe_env = {
        'LANG': 'C.UTF-8' if platform.system() != 'Windows' else 'en_US',
    }
    
    # Platform-specific PATH handling
    if platform.system() == 'Windows':
        # Windows-specific environment
        system_path = os.environ.get('PATH', '')
        safe_paths = [
            r'C:\Windows\system32',
            r'C:\Windows',
            r'C:\Windows\System32\Wbem',
            r'C:\Windows\System32\WindowsPowerShell\v1.0',
        ]
        
        # Add existing PATH but filter suspicious entries
        for path in system_path.split(';'):
            path = path.strip()
            if path and not any(suspicious in path.lower() 
                              for suspicious in ['temp', 'tmp', 'appdata']):
                safe_paths.append(path)
        
        safe_env['PATH'] = ';'.join(safe_paths)
        safe_env['SYSTEMROOT'] = os.environ.get('SYSTEMROOT', r'C:\Windows')
        safe_env['TEMP'] = os.environ.get('TEMP', r'C:\Windows\Temp')
        safe_env['TMP'] = os.environ.get('TMP', r'C:\Windows\Temp')
        
    else:
        # Linux/Unix (unchanged)
        safe_env.update({
            'PATH': '/usr/local/bin:/usr/bin:/bin',
            'HOME': '/tmp'
        })
    
    return safe_env
```

### 2. **Updated `run_sandboxed_command()`**

```python
# ✅ NAPRAWIONY KOD:
result = subprocess.run(
    safe_cmd,
    capture_output=True,
    text=True,
    timeout=timeout,
    check=False,
    cwd=working_dir,
    preexec_fn=limit_resources if RESOURCE_AVAILABLE and hasattr(resource, 'setrlimit') else None,
    env=_get_safe_environment()  # 🎯 Cross-platform environment
)
```

## ✅ Korzyści Naprawki

### **Windows:**
- ✅ **Proper PATH** z Windows system directories
- ✅ **SYSTEMROOT** for system libraries access  
- ✅ **TEMP/TMP** variables for proper temp access
- ✅ **DNS resolution** działa poprawnie
- ✅ **Network stack** ma dostęp do Windows libraries

### **Linux (unchanged):**
- ✅ **Security** zachowane (restricted PATH)
- ✅ **Sandboxing** nadal działa
- ✅ **Backward compatibility** 100%

### **Cross-platform:**
- ✅ **Automatic detection** platform type
- ✅ **Safe environment** dla obu systemów
- ✅ **Security filtering** suspicious PATH entries

## 📊 Oczekiwane Rezultaty

### **Przed naprawką (Windows):**
```json
{
  "http_req_duration": 0,
  "http_req_failed": 1,
  "error": "DNS lookup failure",
  "data_sent": 0,
  "data_received": 0
}
```

### **Po naprawce (Windows):**
```json
{
  "http_req_duration": 94.36,  # Rzeczywisty czas odpowiedzi
  "http_req_failed": 0,        # Brak błędów
  "data_sent": 581,            # Dane wysłane
  "data_received": 14000       # Dane otrzymane
}
```

## 🎯 Impact

### **Dla Claude Desktop użytkowników:**
- ✅ **Testy K6 będą działać** na Windows
- ✅ **Rzeczywiste czasy odpowiedzi** zamiast 0.0ms
- ✅ **Proper network testing** dla https://clientconnector.pwc.pl
- ✅ **Accurate performance metrics**

### **Dla systemu:**
- ✅ **Cross-platform compatibility**
- ✅ **Maintained security** (filtered PATH, safe environment)
- ✅ **No breaking changes** dla Linux users
- ✅ **Better error reporting** (real errors vs DNS failures)

## 🔐 Security Considerations

### **Windows Security:**
- ✅ PATH entries filtered (no temp/appdata directories)
- ✅ Essential system directories included
- ✅ User PATH preserved but sanitized
- ✅ Safe TEMP/TMP locations

### **Linux Security (unchanged):**
- ✅ Restricted PATH (/usr/local/bin:/usr/bin:/bin)
- ✅ Isolated HOME (/tmp)
- ✅ Resource limits still enforced

## 🧪 Testing

### **Test Case:**
```python
# Windows environment test
safe_env = _get_safe_environment()

# Should generate Windows-appropriate environment:
# PATH: C:\Windows\system32;C:\Windows;[existing PATH]
# SYSTEMROOT: C:\Windows
# TEMP: C:\Windows\Temp
# LANG: en_US
```

### **Production Test:**
Po wdrożeniu, test `https://clientconnector.pwc.pl` powinien:
- ✅ Zwrócić status 200
- ✅ Pokazać czas odpowiedzi ~94ms (nie 0.0ms)
- ✅ Przesłać/otrzymać dane
- ✅ Nie pokazywać DNS errors

Ta naprawka rozwiązuje fundamentalny problem cross-platform compatibility w systemie bezpieczeństwa subprocess execution, pozwalając K6 na Windows na proper access do network resources i DNS resolution.