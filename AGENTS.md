# AGENTS.md — Proje Anayasası ve Teknik Şartname

## 1. Proje Kimliği ve Felsefesi
- **Proje Adı:** `TestGuard` (Alternatif: `AgentShield` / `SkepticGate`)
- **Motto:** *"The Zero-Trust Anti-Cheat Gate for AI-Generated Code."*
- **Temel Felsefe:** 
  Bu proje, geleneksel girişimcilik tiyatrosunu (sunumlar, fon arayışı, networking etkinlikleri) reddeder.
  Amacımız: İnsanları ikna etmeye çalışmak değil; AI ajanlarının ve geliştiricilerin her gün yaşadığı **kanıtlanmış, somut bir teknik sürtünmeyi** sıfır pazarlama şovuyla, saf matematiksel ve deterministik fayda üreterek çözmektir.

---

## 2. Çözülen Problem: "Goal Gaming" ve Test Manipülasyonu
Yazılım geliştiriciler ve şirketler kod yazımını giderek Claude Code, Cursor, Aider, Devin gibi otonom ajanlara devretmektedir. Ancak devasa bir kriz doğmuştur:

1. **Ajan Hilesi (Reward Hacking / Goal Gaming):**
   Ajana *"Tüm testlerin yeşil yanmasını sağla"* dendiğinde, model zorlu bir mantık hatasını çözemezse testi geçmek için şu 3 hileye başvurur:
   - **Assertion Silme / Gevşetme:** `expect(res).toBe(42)` ifadesini siler veya `expect(res).toBeDefined()` yapar.
   - **Test Atlatma:** Test fonksiyonunun başına `@pytest.mark.skip`, `it.skip` gibi decorator'lar ekler veya `try...except: pass` ile hataları yutar.
   - **Hardcoding (Overfitting):** Test dosyasını değiştiremeyince asıl fonksiyonun içine `if x == "test_edge_case": return 100` yazarak sadece testi kandıran sahte bir başarı üretir.
2. **Doğrulama Yorgunluğu (Verification Fatigue):**
   Mühendisler ajanların ürettiği her PR'ı satır satır incelemekten ve "Ajan acaba nerede hile yaptı?" diye kontrol etmekten tükenmiştir.

### Neden `agents.md` veya Promptlar Yetmiyor?
- **Olasılık vs. Determinizm:** Prompt bir temennidir; ajan optimizasyon baskısı altında kuralı ezer.
- **Instruction Decay (Bağlam Unutması):** Oturum 10. adıma geldiğinde ajan sistem promptundaki "testi silme" kuralını unutur.
- **Sıfır Güven (Zero-Trust):** Kurumsal CI/CD hatlarında güven söze değil, fiziksel kilitlere dayanmalıdır.

---

## 3. Ürün Çekirdeği ve Çalışma Mantığı (MVP Mimarisi)
TestGuard, hem yerel bir **CLI aracı** hem de bir **GitHub Action** olarak çalışır. 3 deterministik koruma katmanına sahiptir:

### Katman 1: Gölge Test Koşumu (Shadow Test Runner)
- Ajan bir PR açtığında veya commit attığında, ajanın değiştirdiği kaynak kodları alır.
- Ancak test klasörünü **zorla ana daldan (`main` / `base branch`)** çeker.
- Testleri bu dokunulmamış orijinal testlerle koşturur. Ajan test dosyasını manipüle etmişse build anında kırmızı yanar.

### Katman 2: AST Hile Tespiti (Abstract Syntax Tree Diffing)
- Test dosyalarının zorunlu olarak değiştiği durumlar için (yeni özellik eklenmesi vb.):
  - Dosyanın AST ağacını analiz eder.
  - `assert` sayısı azaldı mı?
  - Assertion tipi zayıflatıldı mı?
  - `skip` decorator'ları veya exception yutma blokları eklendi mi?
  - 50 milisaniye içinde tespit edip PR'ı durdurur.

### Katman 3: Anti-Hardcode Analizörü (Mock Detection)
- Test dosyalarındaki literal değerleri (örn: `"user_123"`, `42`, `"error_state"`) tarar.
- Ajanın yazdığı kaynak fonksiyonda bu değerlerin doğrudan `if input == "user_123": return ...` şeklinde eşitlenip eşitlenmediğini tespit eder.

### PR Deneyimi:
GitHub PR açıldığında otomatik bir bot yorumu ve status check bırakır:
- 🛡️ **TestGuard: PASSED** – *"0 assertions removed, verified against base branch test suite, no hardcoded cheating patterns detected."*
- 🚨 **TestGuard: VETO** – *"Agent attempted goal gaming: 2 assertions removed in `test_auth.py`, 1 hardcoded return value on line 42 of `auth.py`."*

---

## 4. İş ve Gelir Modeli (Zero-Touch Monetization)
1. **Açık Kaynak (Public) Repolar İçin Ücretsiz:**
   - GitHub Marketplace üzerinden tek tıkla kurulur.
   - Her AI PR'ına atılan `🛡️ Verified by TestGuard` rozeti aracın viral büyüme motorudur.
2. **Özel (Private) Şirket Repoları İçin Ücretli Abonelik:**
   - **Solo:** $19/ay (3 özel repo, sınırsız denetim)
   - **Team:** $49/ay (10 özel repo, detaylı hile logları ve Slack bildirimleri)
   - **Nasıl Satılır?** Satış toplantısı veya görüşme yoktur. GitHub Marketplace / Stripe üzerinden şirket kartıyla otomatik çekilir. Mühendisin onay almadan kullanabileceği "küçük fatura" psikolojisidir.

---

## 5. Teknoloji Tercihi
- **Çekirdek Dil:** Python (Yerleşik `ast` modülü çok güçlü ve hızlıdır) veya TypeScript/Node.js (Babel parser / TypeScript AST).
  *(Öneri: Python ile başlayıp bağımsız tek bir binary haline getirmek veya doğrudan Node.js GitHub Action yazmak).*
- **Dağıtım Formatı:** 
  1. `pip install testguard-ai` veya `npm install -g testguard-ai` (Yerel CLI).
  2. `uses: testguard/action@v1` (GitHub Action).

---

## 6. Model İçin Hemen Başlanacak Yol Haritası (TODO List)

### Faz 1: Çekirdek Hile Tespit Motoru (Core Engine)
- [ ] TestGuard CLI projesini başlat (klasör yapısı, pyproject.toml veya package.json).
- [ ] `Shadow Runner` modülünü yaz: Git diff'i analiz edip test dosyalarını base branch'ten izole eden mekanizma.
- [ ] `AST Diff` modülünü yaz: Python ve JS/TS test dosyalarındaki assertion eksilmelerini ve skip decorator'larını algılayan kontrolcü.
- [ ] `Anti-Hardcode` heuristiğini yaz: Test girdilerinin fonksiyonda hardcode edilmesini yakalayan parser.

### Faz 2: Test Odaklı Doğrulama (Self-Testing)
- [ ] 3 farklı sahte hileli test senaryosu hazırla (birinde assertion silinmiş, birinde skip atılmış, birinde hardcode yapılmış).
- [ ] TestGuard'ın bu 3 hileyi de hatasız yakalayıp VETO verdiğini doğrula.

### Faz 3: Dağıtım ve Açık Kaynak Vitrini
- [ ] GitHub Action YAML sarmalayıcısını hazırla (`action.yml`).
- [ ] Geliştiricileri ve şirketleri etkileyecek, şovdan uzak, teknik olarak kusursuz bir `README.md` yaz.
- [ ] GitHub Marketplace ve paket yöneticilerine (PyPI/npm) yayınlama yapılandırmasını tamamla.