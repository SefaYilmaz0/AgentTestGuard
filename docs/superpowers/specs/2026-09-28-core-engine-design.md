# TestGuard Faz 1: Çekirdek Hile Tespit Motoru Şartnamesi (Spec)

## 1. Genel Bakış ve Amaç
TestGuard, otonom yapay zeka ajanlarının (Claude Code, Cursor, Aider, Devin vb.) "tüm testleri geçirme" hedefi doğrultusunda uyguladığı hileleri (Goal Gaming / Reward Hacking) deterministik olarak tespit eden ve engelleyen bir güvenlik kapısıdır.

Faz 1'in amacı; harici ağır bağımlılıklara ihtiyaç duymadan, Python'un yerleşik `ast` modülünü ve Git analizini kullanarak hileleri 50ms altında yakalayan modüler CLI çekirdeğini inşa etmektir.

---

## 2. Modüler Mimari

Proje yapısı aşağıdaki gibi yapılandırılacaktır:

```
Agent-Testguard/
├── testguard/
│   ├── __init__.py
│   ├── models.py            # Veri modelleri (Violation, Verdict, CheckResult)
│   ├── ast_diff.py          # Katman 2: AST Diffing & Hile Analizi
│   ├── anti_hardcode.py     # Katman 3: Test Literalleri & Hardcode Analizörü
│   ├── shadow.py            # Katman 1: Git Diff & Shadow Test İzolasyonu
│   ├── verdict.py           # Raporlama ve VETO/PASS karar motoru
│   └── cli.py               # CLI arayüzü (argparse tabanlı)
├── tests/
│   ├── test_ast_diff.py
│   ├── test_anti_hardcode.py
│   ├── test_shadow.py
│   └── test_cli.py
├── pyproject.toml
└── AGENTS.md
```

---

## 3. Bileşen Detayları

### 3.1. `models.py`
Deterministik sonuç yapıları:
- `ViolationType` (Enum):
  - `ASSERTION_REMOVED`: Base test dosyasına göre assertion sayısının azalması veya silinmesi.
  - `TEST_SKIPPED`: `@pytest.mark.skip`, `@unittest.skip` gibi atlatma dekoratörlerinin eklenmesi.
  - `EXCEPTION_SWALLOWED`: Test içinde `try...except: pass` veya hatayı yutan blok eklenmesi.
  - `HARDCODED_CHEAT`: Testteki sabit girdinin doğrudan fonksiyonda `if x == 'val': return ...` olarak hileli yazılması.
- `Violation` (Dataclass):
  - `type: ViolationType`
  - `file_path: str`
  - `line_number: int | None`
  - `symbol_name: str | None` (fonksiyon/metot adı)
  - `message: str`
  - `details: dict`
- `Verdict` (Enum): `PASS`, `VETO`
- `Report` (Dataclass):
  - `verdict: Verdict`
  - `violations: list[Violation]`
  - `summary: str`
  - `execution_time_ms: float`

### 3.2. `ast_diff.py` (AST Hile Analizörü)
- **Girdi:** Orijinal (base) test kodu string'i ve yeni (head) test kodu string'i.
- **İşleyiş:**
  1. Her iki kodu `ast.parse` ile AST ağacına dönüştürür.
  2. Fonksiyon bazında (`test_*` veya `TestCase` metotları):
     - `assert` ifadeleri, `self.assert*` çağrıları sayılır ve karşılaştırılır.
     - Assertion sayısı azalmışsa `ASSERTION_REMOVED` üretilir.
  3. Yeni eklenen dekoratörler taranır: `skip`, `skipIf`, `xfail` vb. eklenmişse `TEST_SKIPPED` üretilir.
  4. Test gövdesi taranır: `ast.Try` bloklarında `handler.body` yalnızca `ast.Pass` içeriyorsa veya boşsa `EXCEPTION_SWALLOWED` üretilir.

### 3.3. `anti_hardcode.py` (Anti-Hardcode / Mock Tespiti)
- **Girdi:** Test AST'si ve kaynak kod AST'si.
- **İşleyiş:**
  1. Test AST'sinden `ast.Constant` (string, int, float) literalleri toplanır (boş string, 0, 1, True, False, docstring'ler filtrelenir).
  2. Kaynak kod AST'si taranır:
     - `ast.If`: Koşulda testten gelen bir literal (`param == "special_token"`) ve gövdesinde sabit bir dönüş (`return 42`) var mı?
     - `ast.Match`: Case pattern'larında test literaliyle birebir örtüşen hileli dallanma var mı?
  3. Eşleşme tespit edildiğinde satır numarası ile `HARDCODED_CHEAT` ihlali üretilir.

### 3.4. `shadow.py` (Gölge Test Koşumu & Git İzolasyonu)
- **İşleyiş:**
  1. `git diff --name-only <base_ref>` ile değişen dosyaları listeler.
  2. Değiştirilmiş test dosyalarını tespit eder.
  3. `git show <base_ref>:<path>` ile test dosyalarının base içeriğini okur ve `ast_diff` modülüne aktarır.
  4. Test koşumu modunda: Test klasörünü geçici olarak base versiyonuna çeker veya gölge dizinde kaynak kod + base testleri eşleştirip test çalıştırıcıyı (pytest vb.) koşturur.

### 3.5. `verdict.py` & `cli.py`
- Komut: `testguard check [--base origin/main] [--target <path>] [--format json|text]`
- Çıktı:
  - İhlal yoksa: `🛡️ TestGuard: PASSED` (Exit code 0)
  - İhlal varsa: `🚨 TestGuard: VETO` + İhlal listesi (Exit code 1)
  - GitHub Actions ortamında PR bot çıktısına uygun markdown / step summary çıktısı.

---

## 4. Hata Yönetimi ve Sınır Durumlar
- Geçersiz Python sözdizimi: AST ayrıştırma hatası durumunda çökmeden net hata mesajı ve VETO üretilir.
- Sıfırdan eklenen yeni test dosyaları: Base versiyonu olmadığı için assertion eksilmesi aranmaz; ancak skip veya exception yutma kontrolü head üzerinde yine çalıştırılır.
- Git deposu olmayan dizin: Yerel iki dosya veya klasör karşılaştırması (`testguard diff file_base.py file_head.py`) doğrudan desteklenir.

---

## 5. Doğrulama Stratejisi (Test Driven)
1. `tests/test_ast_diff.py`:
   - Assertion silme testi.
   - `@pytest.mark.skip` ekleme testi.
   - `try...except: pass` ekleme testi.
2. `tests/test_anti_hardcode.py`:
   - `if x == "secret_test_value": return 999` hardcode tespiti.
   - Meşru kodların yanlış pozitif (false positive) vermediğinin doğrulanması.
3. `tests/test_shadow.py`:
   - Git diff üzerinden test dosyasının base ve head versiyonlarının çekilip analiz edilmesi.
4. `tests/test_cli.py`:
   - CLI argümanları ve exit code (0 / 1) çıktılarının doğrulanması.
