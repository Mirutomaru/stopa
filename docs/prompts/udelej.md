# MASTER PROMPT – STOPA ULTIMATE FORENSIC PLATFORM

Strategický rozvoj, technický audit a implementace nové generace digitální forenzní platformy

Role: Senior Software Architect, Digital Forensics Engineer, AI/ML Engineer, Security Engineer a Technical Lead.

Projekt: STOPA – Unified Forensic Workbench
Výchozí commit: "ae73ad0"
Technologie: Python 3.11+, FastAPI, SQLite FTS5, Pydantic v2, vanilla JavaScript, The Sleuth Kit, LM Studio.

---

## 1. HLAVNÍ CÍL

Tvým úkolem je posunout existující aplikaci STOPA na úroveň moderní profesionální digitální forenzní platformy.

Cílem je vytvořit komplexní systém, který kombinuje schopnosti tradičních forenzních nástrojů s moderními technologiemi:

- Umělá inteligence a multi-agentní analytika.
- Automatizovaná extrakce digitálních artefaktů.
- Korelace dat napříč zařízeními a operačními systémy.
- Pokročilá časová analýza.
- Cloud, mobile, memory a multimedia forensics.
- Pokročilé vyhledávání a analýza rozsáhlých datasetů.
- Kryptografická integrita důkazů.
- Reprodukovatelnost analytických postupů.
- Automatizované generování odborných forenzních reportů.

STOPA nesmí být pouze kopií existujících produktů. Musí mít vlastní architekturu, vlastní analytické schopnosti a moderní AI vrstvu.

Zásadní pravidlo: Nejdříve pochop existující systém, následně jej rozšiřuj. Nepřepisuj funkční části bez technického důvodu.

---

## 2. VÝCHOZÍ STAV PROJEKTU

Aktuální aplikace již obsahuje:

- Case management a SQLite databázi.
- Evidence management a audit log.
- Multi-hash processing MD5/SHA-1/SHA-256.
- Magic-bytes identifikaci souborů.
- Advanced deduplication.
- SQLite FTS5 fulltextové vyhledávání.
- Chrome a Firefox parsery.
- Windows Registry, LNK, Prefetch, Jump Lists, EVTX, Amcache, ShimCache a USN Journal.
- Apple plist a mobilní artefakty.
- Disk images E01, AFF4 a RAW.
- The Sleuth Kit integraci.
- File carving.
- FDE/FBE a LUKS.
- Timeline Engine.
- Entity/Correlation Engine.
- File Inspector.
- HTML/PDF reporty.
- AI Forensic Assistant napojený na LM Studio.
- FastAPI a vanilla JavaScript GUI.

Aktuální deklarovaný stav:

- Přibližně 60 modulů.
- Přibližně 22 400 řádků zdrojového kódu a testů.
- 29 API endpointů.
- 642 úspěšných testů.
- Ruff clean.
- Offline testovací infrastruktura.

Tato čísla považuj za výchozí deklaraci. Na začátku práce je nezávisle ověř.

---

## 3. POVINNÁ PRAVIDLA VÝVOJE

1. Zachovej existující funkční architekturu Clean Architecture.
2. Zachovej oddělení domain, artifacts, data a web.
3. Doménová logika musí zůstat co nejvíce nezávislá na I/O.
4. Zachovej plnou možnost offline provozu.
5. AI nesmí být povinnou závislostí základních forenzních funkcí.
6. Zachovej zpětnou kompatibilitu existujících případů a databází.
7. Každý nový parser musí mít automatizované testy.
8. Každá nová funkce musí mít dokumentaci.
9. Každá analytická operace musí být auditovatelná.
10. Nikdy neměň originální důkazní data.
11. Každý export musí být reprodukovatelný.
12. Neodstraňuj existující testy kvůli dosažení zeleného výsledku.
13. Nepoužívej mockování jako náhradu za testování kritické forenzní logiky.
14. Nepřidávej technologii jen proto, že je moderní. Každá závislost musí mít jasný přínos.
15. Změny implementuj po malých, kontrolovatelných celcích.

Pokud narazíš na nejednoznačnost nebo riziko narušení integrity důkazů, nejprve problém zdokumentuj a navrhni bezpečné řešení.

---

## 4. NOVÁ STRATEGICKÁ ARCHITEKTURA

### 4.1 Unified Evidence Model

Vytvoř jednotný datový model, který bude představovat společný základ všech analytických modulů.

Musí podporovat:

- Evidence sources.
- Files.
- Artifacts.
- Events.
- Entities.
- Communications.
- Metadata.
- Relationships.
- Derived findings.
- Analytical observations.
- Provenance.
- Confidence.
- Validation status.

Každý artefakt musí obsahovat minimálně:
- Jednoznačný identifikátor.
- Case ID.
- Source ID.
- Původní soubor.
- Identifikaci parseru.
- Verzi parseru.
- Čas extrakce.
- Původní časovou hodnotu, pokud existuje.
- Normalizovaný čas a časové pásmo.
- Referenci na zdrojový záznam nebo offset, pokud je dostupný.
- Stav validace.
- Kvalitu a omezení extrakce.

Zajisti možnost rozšiřování modelu bez nutnosti měnit všechny existující parsery.

Zaveď verzování datového schématu a migrační mechanismus.

### 4.2 Evidence Lineage Engine

Implementuj systém sledování původu každého zjištění.

Musí být možné dohledat:

Originální evidence → Parser → Extrahovaný artefakt → Transformace → Analytická korelace → Finding → Report.

Každá transformace musí mít zaznamenanou verzi nástroje, konfiguraci, vstup a výstup.

Zajisti možnost zpětného dohledání konkrétního tvrzení v reportu až k původnímu zdroji.

### 4.3 Advanced Data Analytics

Ponech SQLite jako primární case management databázi.

Vyhodnoť zavedení:

- DuckDB pro analytické dotazy.
- Apache Parquet pro rozsáhlé analytické datasety.
- Apache Arrow pro efektivní přenos dat.
- Volitelného OpenSearch adaptéru pro rozsáhlé fulltextové vyhledávání.

Všechny nové technologie musí být volitelné a nesmí narušit offline základní provoz.

---

## 5. AI FORENSIC INTELLIGENCE ENGINE

Rozšiř stávající AI Forensic Assistant na plnohodnotnou analytickou platformu.

### 5.1 Multi-Agent Architecture

Vytvoř centrální orchestrátor a pět specializovaných agentů.

**Case Analyst**
- Analýza případu.
- Vyhledávání relevantních informací.
- Korelace jednotlivých zjištění.
- Přehled nevyřešených otázek.

**Timeline Analyst**
- Analýza časových událostí.
- Detekce časových rozporů.
- Identifikace neobvyklých časových souvislostí.
- Porovnávání událostí napříč zdroji.

**Artifact Analyst**
- Interpretace extrahovaných artefaktů.
- Vysvětlení struktury a významu.
- Identifikace neúplných nebo nejednoznačných záznamů.

**Media Analyst**
- Analýza multimediálních metadat.
- OCR.
- Audio a video analytika.
- Detekce indikátorů manipulace.

**Report Analyst**
- Generování podkladů pro odborné reporty.
- Sumarizace ověřených zjištění.
- Odkazování na zdrojové artefakty.
- Rozlišení faktů a analytických interpretací.

Agenti musí pracovat prostřednictvím společného orchestrace API.

Neimplementuj zbytečně složitý autonomní systém. Každý agent musí mít jasně definované vstupy, výstupy, oprávnění a limity.

### 5.2 Forensic RAG

Vytvoř tři oddělené znalostní vrstvy:

1. Case RAG – data konkrétního případu.
2. Technical RAG – dokumentace formátů, parserů a technických standardů.
3. Knowledge RAG – odborná metodika a schválené interní postupy.

Přístup musí být řízený podle oprávnění.

Zajisti:

- Citace na konkrétní artefakty.
- Citace na technické zdroje.
- Oddělení případových dat od obecných znalostí.
- Ochranu před prompt injection v importovaných dokumentech.
- Kontrolu kontextu mezi jednotlivými případy.
- Audit AI dotazů.
- Evidence použitého modelu a jeho verze.
- Evidenci použitých promptů a konfigurací.

### 5.3 AI Grounding

AI nesmí prezentovat domněnku jako skutečnost.

Každé zjištění musí rozlišovat:

- Direct Evidence – přímo extrahovaný údaj.
- Derived Finding – výsledek deterministické transformace.
- Analytical Interpretation – analytická interpretace.
- AI Hypothesis – hypotéza navržená AI.
- Unverified – neověřená informace.

Všechny odpovědi musí obsahovat odkazy na zdroje a možnost nezávislého ověření.

AI nesmí sama měnit důkazy, potvrzovat hypotézy nebo přepisovat auditní historii.

---

## 6. ADVANCED TIMELINE INTELLIGENCE

Rozšiř existující Timeline Engine.

Implementuj:

- Jednotnou časovou osu všech podporovaných zdrojů.
- Normalizaci UTC a zachování původních časových hodnot.
- Evidenci přesnosti a nejistoty časových údajů.
- Detekci časových rozporů.
- Detekci duplicitních událostí.
- Korelaci událostí napříč zařízeními.
- Filtrování podle entit, aplikací a zdrojů.
- Interaktivní vizualizaci.
- Ukládání analytických pohledů.
- Export filtrovaných časových úseků.

Každá událost musí mít dohledatelný původ a informaci o přesnosti timestampu.

---

## 7. ADVANCED ENTITY RESOLUTION

Rozšiř existující Entity/Correlation Engine.

Implementuj:

- Normalizaci telefonních čísel.
- Normalizaci e-mailových adres.
- Normalizaci uživatelských účtů.
- Korelaci identifikátorů napříč zařízeními.
- Detekci duplicitních entit.
- Graf vztahů.
- Časově závislé vztahy.
- Vysvětlení důvodu každého propojení.
- Evidence alternativních vysvětlení.

Zaveď rozlišení mezi:

- Confirmed relationship.
- Strong candidate.
- Possible relationship.
- Unverified relationship.

Automatické propojení entit nesmí znamenat automatické potvrzení totožnosti osob.

---

## 8. CLOUD FORENSICS

Vytvoř samostatný modul Cloud Forensics.

Prioritní oblasti:

- Microsoft 365.
- Exchange Online.
- Microsoft Teams.
- OneDrive.
- SharePoint.
- Google Workspace.
- Gmail exporty.
- AWS CloudTrail exporty.
- Azure auditní záznamy.
- Google Cloud auditní logy.

Podporuj především standardizované exporty a oprávněně získaná data.

Implementuj:

- Import cloudových exportů.
- Normalizaci auditních záznamů.
- Metadata souborů.
- Časové osy aktivit.
- Identifikaci účtů a služeb.
- Korelaci s lokálními zařízeními.
- Zachování původu každého záznamu.

Připrav modulární konektory, které lze rozšiřovat bez zásahu do hlavního jádra.

---

## 9. MEMORY FORENSICS

Připrav samostatný modul pro analýzu paměťových obrazů.

Vyhodnoť integraci existujících odborných nástrojů a formátů.

Požadované oblasti:

- Windows memory images.
- Linux memory images.
- macOS memory images.
- Strukturovaný import analytických výsledků.
- Evidence zdrojových offsetů.
- Korelace s ostatními artefakty.
- Integrace do unified evidence modelu.

Preferuj integraci ověřených nástrojů před vytvářením vlastního nízkoúrovňového parseru bez validačního základu.

---

## 10. MOBILE FORENSICS 2.0

Rozšiř podporu Android a iOS.

Prioritní oblasti:

- SQLite databáze aplikací.
- WAL a SHM.
- Messaging aplikace.
- Kontakty a adresáře.
- Historie hovorů.
- Notifikace.
- Browser data.
- Backup metadata.
- Aplikační metadata.
- Systémové logy.

Vytvoř společný framework pro import výsledků různých extrakčních nástrojů.

Každý import musí zachovat původní strukturu, metadata a integritu vstupních souborů.

---

## 11. COMMUNICATION INTELLIGENCE

Vytvoř samostatný komunikační analytický modul.

Podporované formáty:

- EML.
- MBOX.
- PST.
- OST, pokud je možné získat data pomocí ověřené knihovny.
- Exporty komunikačních aplikací.
- CSV/XLSX exporty.

Funkce:

- Parsování e-mailových hlaviček.
- Extrakce příloh.
- Korelace odesílatelů a příjemců.
- Rekonstrukce konverzací.
- Deduplicita zpráv.
- Časová analýza komunikace.
- Propojení s Entity Engine.
- Vyhledávání napříč komunikačními zdroji.

---

## 12. MULTIMEDIA FORENSICS 2.0

Vytvoř modul pro odbornou analýzu obrazových, zvukových a video souborů.

**Image Forensics**
- EXIF a další metadata.
- Analýza rozměrů a formátu.
- Kontrola C2PA Content Credentials.
- Detekce indikátorů úprav.
- OCR.
- Evidence původu obrazu.

**Audio Forensics**
- Metadata.
- Analýza časových parametrů.
- Detekce střihů a diskontinuit.
- Speech-to-text.
- Identifikace syntetických indikátorů.
- Přehled technických omezení analýzy.

**Video Forensics**
- Metadata kontejnerů a kodeků.
- Extrakce snímků.
- Časová analýza.
- Detekce diskontinuit.
- Synchronizace audio/video.
- OCR ve snímcích.
- Analýza indikátorů manipulace.

**Deepfake Analysis**
Vytvoř samostatnou vrstvu pro vyhodnocování indikátorů syntetického obsahu.

Výsledky musí být prezentovány jako indikátory, nikoliv jako absolutní potvrzení pravosti nebo nepravosti.

Originální multimediální soubory se nikdy nesmějí upravovat.

---

## 13. FORENSIC VALIDATION LABORATORY

Toto je jedna z nejdůležitějších částí celého projektu.

Vytvoř samostatnou validační infrastrukturu.

Každý parser musí mít:

- Jednoznačný identifikátor.
- Verzi.
- Podporované formáty.
- Známá omezení.
- Referenční dataset.
- Očekávané výsledky.
- Pozitivní testy.
- Negativní testy.
- Edge-case testy.
- Regresní testy.
- Dokumentaci validace.

Implementuj:
- Parser Validation Registry.
- Benchmark Engine.
- Regression Test Engine.
- Dataset Management.
- Test Coverage Dashboard.
- Performance Benchmarking.
- Evidence Validation Reports.

Doplň existující E13 backlog.

Využívej odborné referenční zdroje NIST, SWGDE a dokumentaci příslušných formátů.

Nikdy netvrď, že je parser forenzně validovaný pouze proto, že prochází unit testy.

---

## 14. EVIDENCE INTEGRITY 2.0

Rozšiř současný auditní systém.

Implementuj:

- Kryptograficky provázaný auditní log.
- Hash chaining.
- Pravidelně podepisované kontrolní body.
- Hashování exportních manifestů.
- Evidenci verzí nástrojů.
- Evidenci konfigurací.
- Evidenci analytických operací.
- Kontrolu integrity důkazních souborů.
- Oddělení originálů a pracovních kopií.
- Reprodukovatelné analytické postupy.

Vyhodnoť vhodnost Ed25519 pro digitální podpisy.

Zajisti ochranu proti neoprávněné změně auditních záznamů a možnost nezávislé kontroly integrity.

---

## 15. FORENSIC REPRODUCIBILITY ENGINE

Vytvoř systém pro reprodukci analytických operací.

Musí být možné zaznamenat:

- Vstupní soubory a jejich hashe.
- Použitý parser.
- Verzi parseru.
- Konfiguraci.
- Verzi STOPA.
- Výstupní artefakty.
- Výsledky validace.
- Čas zpracování.
- Závislosti a prostředí.

Umožni zopakovat konkrétní analytickou operaci bez změny originálních důkazních dat.

Zajisti porovnání původního a nového výsledku.

---

## 16. ADVANCED SEARCH

Rozšiř existující FTS5 vyhledávání.

Přidej:

- Pokročilé kombinované filtry.
- Vyhledávání napříč případem.
- Vyhledávání napříč artefakty.
- Vyhledávání podle entit.
- Vyhledávání podle časových intervalů.
- Vyhledávání podobných textů.
- Volitelné sémantické vyhledávání.
- Ukládání vyhledávacích dotazů.
- Audit vyhledávání.

Zvaž embedding modely provozované lokálně.

Sémantické vyhledávání musí být jasně odděleno od přesného forenzního vyhledávání.

---

## 17. ROZŠÍŘENÍ PODPORY DŮKAZNÍCH ZDROJŮ

Vytvoř plán postupného rozšiřování extraktorů.

Prioritní oblasti:

**Windows**
- Další registry artefakty.
- Office dokumenty.
- Windows Search.
- Browser artefakty.
- Aplikační logy.
- Další systémové databáze.

**macOS**
- APFS metadata.
- Unified Logs.
- Spotlight.
- Safari.
- Aplikační artefakty.

**Linux**
- Journal.
- Shell history.
- Browser data.
- Package metadata.
- Desktop artefakty.

**Documents**
- PDF.
- DOCX.
- XLSX.
- PPTX.
- RTF.
- E-mailové přílohy.

**Databases**
- SQLite.
- WAL.
- SHM.
- Další běžné databázové formáty.

**Network**
- PCAP.
- DNS logy.
- Síťové metadata.
- Časové korelace.

**Additional**
- IoT exporty.
- GPS.
- Geospatial metadata.
- Kryptoměnové transakční exporty.

Prostuduj existující seznam 237 AXIOM extraktorů v "docs/re-axiom/".

Zmapuj, které již STOPA implementuje, které chybí a které jsou skutečně relevantní pro další rozvoj.

---

## 18. ADVANCED INVESTIGATION WORKSPACE

Modernizuj GUI.

Zachovej současný vanilla JS přístup bez povinného build kroku, pokud audit neprokáže zásadní důvod ke změně.

Navrhni profesionální pracovní prostředí inspirované moderními analytickými aplikacemi.

Požadované funkce:

- Třísloupcový analytický layout.
- Levý navigační panel.
- Centrální pracovní plocha.
- Pravý Inspector.
- Pokročilý status bar.
- Moderní barevná paleta.
- Jednotná typografie.
- Ikonografie.
- Pokročilé datové tabulky.
- Ukládání pohledů.
- Timeline workspace.
- Entity Graph workspace.
- AI Assistant workspace.
- Media workspace.
- Porovnávání souborů.
- Anotace a poznámky.
- Vyšetřovací záložky.
- Pokročilé filtrování.
- Keyboard shortcuts.

Přidej přehledné System Diagnostics a stav jednotlivých analytických modulů.

GUI musí zůstat rychlé i při práci s rozsáhlými případy.

---

## 19. ENTERPRISE A MULTI-USER ARCHITEKTURA

Připrav STOPA na budoucí nasazení ve větší organizaci.

Vyhodnoť a postupně implementuj:

- RBAC.
- Správu uživatelů.
- Oddělení případů.
- Přístupová oprávnění.
- Audit přístupu.
- Schvalovací procesy.
- Centrální správu konfigurace.
- API pro externí systémy.
- Bezpečné zálohování.
- Šifrování citlivých dat.
- Oddělené pracovní prostředí jednotlivých případů.

Zachovej možnost samostatného offline nasazení na jednom počítači.

---

## 20. TECHNOLOGICKÉ INOVACE

Proveď odborné vyhodnocení následujících technologií:

- DuckDB.
- Apache Arrow.
- Apache Parquet.
- OpenSearch.
- ONNX Runtime.
- C2PA.
- OpenTelemetry.
- YARA.
- Apache Tika.
- OCR a moderní document layout modely.
- Lokální embedding modely.
- Lokální vision-language modely.

U každé technologie stanov:

1. Jaký problém řeší.
2. Jaký přináší výkonový nebo funkční přínos.
3. Jaké jsou její nároky na RAM, CPU a GPU.
4. Zda podporuje offline provoz.
5. Jaké jsou licenční podmínky.
6. Jak bude integrována do současné architektury.
7. Jaké existují alternativy.

Nepřidávej technologii, pokud její přínos není prokazatelný.

---

## 21. PRIORITY IMPLEMENTACE

Dodržuj následující pořadí:

**P0 – Forensic Core 2.0**
- Unified Evidence Model.
- Evidence Lineage.
- Parser Validation Registry.
- Evidence Integrity 2.0.
- Reproducibility Engine.
- E13 benchmarky.

**P0 – Intelligence Engine**
- AI orchestrace.
- Forensic RAG.
- Entity Resolution.
- Timeline Intelligence.
- AI grounding.
- Detekce rozporů.

**P1 – Modern Evidence Sources**
- Cloud Forensics.
- Memory Forensics.
- Communication Intelligence.
- Mobile Forensics 2.0.
- macOS a Linux.
- Document Intelligence.

**P1 – Multimedia Intelligence**
- OCR.
- Audio Forensics.
- Video Forensics.
- Image Forensics.
- Deepfake indikátory.
- C2PA.

**P2 – Enterprise Platform**
- Multi-user.
- RBAC.
- API.
- Enterprise deployment.
- Advanced Investigation Workspace.

---

## 22. POVINNÝ POSTUP PRÁCE

Práci rozděl do jasných etap.

### ETAPA A – Kompletní audit

Nejdříve projdi celý repozitář.

Zmapuj:

- Strukturu projektu.
- Všechny moduly.
- Datové modely.
- Databázi.
- API.
- Parsery.
- Testy.
- GUI.
- AI integraci.
- Bezpečnost.
- Závislosti.
- Dokumentaci.
- Nedokončené funkce.

Vytvoř dokument:

"docs/STOPA_TECHNICAL_AUDIT.md"

Dokument musí obsahovat:

- Současný stav.
- Silné stránky.
- Slabá místa.
- Technický dluh.
- Duplicitní funkcionality.
- Bezpečnostní rizika.
- Chybějící schopnosti.
- Návrhy architektonických změn.

### ETAPA B – GAP ANALYSIS

Porovnej současný stav s tímto zadáním.

Každou funkci označ:

- IMPLEMENTED.
- PARTIALLY IMPLEMENTED.
- MISSING.
- NEEDS VALIDATION.
- NOT RECOMMENDED.

U každé položky uveď konkrétní moduly a soubory, kterých se změna týká.

Vytvoř:

"docs/STOPA_GAP_ANALYSIS.md"

### ETAPA C – ARCHITEKTONICKÝ PLÁN

Vytvoř:

"docs/STOPA_TARGET_ARCHITECTURE.md"

Zpracuj:

- Cílovou architekturu.
- Datové modely.
- API kontrakty.
- Závislosti.
- Migrační strategii.
- Bezpečnost.
- Testovací strategii.
- Pořadí implementace.

### ETAPA D – IMPLEMENTACE

Po dokončení auditu začni skutečně implementovat.

Nezůstávej pouze u dokumentace.

Pracuj po menších samostatných úkolech.

Pro každou změnu:

1. Prostuduj existující implementaci.
2. Navrhni řešení.
3. Implementuj.
4. Přidej testy.
5. Spusť související testy.
6. Spusť kompletní regresní sadu.
7. Spusť Ruff.
8. Zkontroluj kompatibilitu databáze.
9. Aktualizuj dokumentaci.
10. Zaznamenej výsledek.

Pokud je úkol příliš rozsáhlý, rozděl jej na menší implementační jednotky.

### ETAPA E – KONTROLA KVALITY

Po každé implementační etapě ověř:

- Funkčnost.
- Integritu důkazních dat.
- Bezpečnost.
- Výkon.
- Offline provoz.
- Zpětnou kompatibilitu.
- Test coverage.
- Dokumentaci.

Nikdy nepokračuj v rozsáhlé implementaci, pokud jsou kritické regresní testy neúspěšné.

---

## 23. PRAVIDLA PRO AI A EXTERNÍ SLUŽBY

STOPA musí být schopna fungovat plně offline.

Externí služby musí být volitelné a vypnuté jako výchozí stav.

Zajisti:

- Žádné automatické odesílání důkazních dat na internet.
- Žádné automatické cloudové AI zpracování.
- Oddělení lokálních a externích modelů.
- Evidenci každého externího přenosu.
- Kontrolu oprávnění.
- Bezpečné nakládání s API klíči.
- Zabránění přenosu dat mezi případy.
- Ochranu proti prompt injection.
- Izolaci nedůvěryhodných vstupů.

AI výstupy musí být vždy označeny jako analytické výstupy, nikoliv jako původní důkazy.

---

## 24. DEFINITION OF DONE

Funkci považuj za dokončenou pouze tehdy, pokud:
- Je skutečně implementovaná.
- Má funkční integrační rozhraní.
- Má odpovídající testy.
- Má zdokumentovaná omezení.
- Zachovává integritu evidence.
- Je auditovatelná.
- Funguje v podporovaném režimu offline.
- Nezpůsobuje regresi existujících funkcí.
- Má aktualizovanou dokumentaci.

Pouhé vytvoření prázdného modulu, API endpointu, UI tlačítka nebo TODO komentáře se nepovažuje za implementaci.

---

## 25. FINÁLNÍ VÝSTUPY

Vytvoř a průběžně aktualizuj:

- "docs/STOPA_TECHNICAL_AUDIT.md"
- "docs/STOPA_GAP_ANALYSIS.md"
- "docs/STOPA_TARGET_ARCHITECTURE.md"
- "docs/STOPA_IMPLEMENTATION_ROADMAP.md"
- "docs/STOPA_VALIDATION_STRATEGY.md"
- "docs/STOPA_SECURITY_MODEL.md"
- "docs/STOPA_AI_ARCHITECTURE.md"
- "docs/STOPA_CHANGELOG.md"

Zajisti, aby dokumentace odpovídala skutečnému stavu implementace.

---

## 26. ZÁVĚREČNÉ POKYNY

Přistupuj k STOPA jako k profesionálnímu forenznímu produktu, který má potenciál konkurovat zavedeným komerčním platformám.

Nesnaž se pouze napodobovat existující funkce. Hledej inovace, které mají skutečnou přidanou hodnotu.

Prioritami jsou:

1. Maximální důvěryhodnost výsledků.
2. Široká podpora digitálních důkazních zdrojů.
3. Inteligentní analytika.
4. Automatizace opakovaných činností.
5. Rychlost zpracování rozsáhlých datasetů.
6. Vysoká kvalita uživatelského prostředí.
7. Plná dohledatelnost každého zjištění.
8. Offline a bezpečný provoz.
9. Dlouhodobá rozšiřitelnost.
10. Profesionální prezentace výsledků.

Neobětuj forenzní správnost kvůli rychlosti vývoje nebo efektním funkcím AI.

---

## PRVNÍ PŘÍKAZ

Začni ETAPOU A – kompletním technickým auditem současného repozitáře STOPA.

Zatím neprováděj rozsáhlé refaktoringy ani destruktivní změny.

Nejdříve zjisti, co již existuje, co funguje, co je nedokončené a co je potřeba skutečně vytvořit.

Poté připrav GAP Analysis a konkrétní implementační plán.

Jakmile budou tyto dokumenty hotové a ověřené, pokračuj implementací priorit P0.

Pracuj autonomně, systematicky a po ověřitelných krocích. Tvým cílem není vytvořit největší množství kódu. Tvým cílem je vytvořit nejlepší možnou verzi STOPA.
