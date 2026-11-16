# BENY Modbus pro Home Assistant

[English documentation](README.md)

Vlastní integrace pro jednozásuvkové wallboxy BENY Smart BCP-...-L přes
převodník RS485–Ethernet, navržená pro BCP-AT2N-L podle protokolu BENY v3.8.
DLB box není potřeba. Nejde o oficiální produkt BENY.

**Verze 0.1.2.** K dispozici je 73 simulačních testů protokolu a ovládání.
Instalace v běžícím HA a komunikace se skutečným wallboxem ještě vyžadují
ověření. Určeno pro Home Assistant Core 2026.10.0 a novější.

## Instalace přes HACS

Repozitář: `https://github.com/Koubkovi7/ha-beny-modbus`

1. V HACS otevřete **tři tečky → Vlastní repozitáře / Custom repositories**.
2. Vložte `https://github.com/Koubkovi7/ha-beny-modbus` a vyberte **Integration**.
3. Vyhledejte **BENY Modbus** a stáhněte integraci.
4. Restartujte Home Assistant.
5. Otevřete **Nastavení → Zařízení a služby → Přidat integraci → BENY Modbus**.
6. Zadejte připojení převodníku. Formulář obsahuje české i anglické popisky
   a doporučení pod jednotlivými poli podle jazyka HA.
7. Pro první ověření ponechte horní limit 6 A. Zvyšujte jej pouze podle
   ověřeného limitu instalace.

Jde o vlastní repozitář, nikoli záznam ve výchozím katalogu HACS. HACS umí
stahovat výchozí větev i před prvním vydáním GitHub Release.

Ruční instalace: zkopírujte složku `custom_components/beny_modbus` do konfigurace
HA a restartujte. Výsledná cesta musí být
`/config/custom_components/beny_modbus/manifest.json`.

## Doporučené připojení

| Parametr | Doporučená výchozí hodnota |
| --- | --- |
| IP nebo název převodníku | Vlastní adresa; doporučeno DHCP s rezervací v routeru |
| Pracovní režim převodníku | TCP Server |
| Převod protokolu | Modbus TCP to RTU |
| Režim v integraci | Modbus TCP |
| TCP port | 502, případně skutečný port z konfigurace převodníku |
| Modbus adresa wallboxu | 1, pokud nebyla změněna |
| RS485 rychlost | 4800 Bd |
| Sériový formát | 8 datových bitů, bez parity, 1 stop bit (8N1) |
| Plug & Play ve wallboxu | Vypnuto pro dálkové START/STOP |
| Horní limit integrace | Pro první test 6 A; nastavitelný nejvýše na 32 A |

Sériové parametry nastavte přímo v převodníku. Integrace je nemění.
Port 80 obvykle slouží webovému rozhraní, do integrace patří komunikační port.
**Modbus TCP** použijte pro převodník v režimu **Modbus TCP to RTU**.
**Modbus RTU over TCP** je určen pro transparentní přenos RTU rámců s CRC.
Nesprávná volba znemožní platné odpovědi.

DHCP může adresu změnit; rezervace v routeru jí přiřadí stálou IP.
Pozdější změna: nabídka integrace **Znovu nakonfigurovat / Reconfigure**
upraví IP, port a režim se zachováním identifikátorů entit. Volba
**Konfigurovat** mění proudový strop a povolení ovládání. Automatické hledání
převodníku není implementováno.

## Co integrace poskytuje

- Přepínač **Povolit nabíjení** a nastavení dočasného nabíjecího proudu.
- Samostatný stav **Nabíjí**, připojení auta, stav konektoru a poruchy.
- Napětí a proud L1–L3 a energii nabíjecí relace.
- Diagnostiku a volitelné hodnoty podle firmwaru.

Povolené nabíjení neznamená, že auto právě odebírá proud. Energie relace není
celoživotní elektroměr pro Energy Dashboard. Proud je omezen nižší hodnotou
z nastaveného stropu integrace a trvalého limitu wallboxu. Změna stropu sama
neomezí již probíhající nabíjení a nemění ovládání z aplikace výrobce.

Pravidelné načítání pouze čte jednotlivé registry. Opakovaný START při již
povoleném nabíjení se neposílá; další pokus chrání prodleva 30 sekund.
STOP na ni nečeká. Změna proudu používá dočasný registr `0x0200` bez
vypnutí a zapnutí. Nejistý zápis se automaticky neopakuje. Při přidání,
restartu HA ani obnovení komunikace se automaticky neposílá START.
Pokud po novém START není do 2 minut zaznamenáno nabíjení, vznikne oznámení
v HA bez opakovaného startování. Nejde o push zprávu do telefonu.

Původní příčina cvakání stykače nebyla potvrzena měřením. Ochrany omezují
opakované softwarové příkazy. Tato verze neobsahuje tarifní automatizaci ani
DLB. Timeout wallboxu se pouze čte; zastavení při výpadku HA není garantované.
Ověřte cache a autonomní čtení převodníku: mohou vracet staré hodnoty nebo
udržovat komunikaci s wallboxem i po výpadku HA. BENY DLB box nepřipojujte
současně ke stejné řídicí lince RS485.

## První test

1. Ověřte načtení modelu, napětí, stavů a případných poruch.
2. Vypněte Plug & Play a ponechte počáteční limit 6 A.
3. Připojte auto a jednou povolte nabíjení. Sledujte i skutečné proudy fází.
4. Ověřte nastavení proudu v povoleném rozsahu a následně STOP a konec odběru.
5. Teprve poté navazujte automatizací nízkého tarifu.

Při potížích stáhněte diagnostiku integrace a související log. Diagnostika
skrývá zadanou IP a název; log před zveřejněním zkontrolujte zvlášť.

## Obnova po ztrátě HA

Nainstalujte znovu HACS, přidejte repozitář a stáhněte integraci. Potom zadejte
připojení převodníku. GitHub uchovává kód, nikoli vaše nastavení HA,
automatizace nebo historii; pro jejich obnovu potřebujete zálohu HA.

## Testy a zdrojový balíček

```sh
python tools/check_repository.py
python -m unittest discover -s tests -v
python tools/build_package.py
```

ZIP vznikne ve složce `dist`. Obsahuje veřejné zdroje, překlady, návody a testy.
Původní XLSX od výrobce je samostatný podklad a není součástí veřejného balíčku.
V prostředí bez socketů použijte `python tests/run_memory.py`; tento režim
neověřuje skutečnou síť ani běžící HA. GitHub Actions jsou připravené pro testy,
kontrolu balíčku, HACS a hassfest. Kontrola HACS je určená pro vlastní repozitář:
vynechává katalogový popis, témata a branding. Při instalaci vlastního repozitáře
se tyto kontroly nespouštějí. Před přihlášením do výchozího katalogu HACS je
potřeba tyto údaje doplnit a příslušné kontroly zapnout.

Úplný technický popis a odkazy na dokumentaci jsou v [anglickém návodu](README.md).
Zdrojový kód je pod licencí MIT.

## Podrobnosti chyby připojení

Od verze 0.1.2 ukazuje formulář konkrétní registr a důvod chyby. Funkční web
převodníku ověřuje pouze jeho HTTP rozhraní, nikoli dostupnost Modbus z HA.

| Text v detailu | Co ověřit |
| --- | --- |
| `opening TCP connection` | Dostupnost z HA, port TCP serveru a oddělení sítí |
| `waiting for Modbus response` | Režim převodníku, nastavení RS485, napájení a adresu wallboxu |
| `exception 0x..` | Přišla chybová odpověď Modbus; pošlete kód i adresu registru |
| `Invalid Modbus TCP header` / `RTU CRC mismatch` | Formát rámců, režim převodníku a neporušenost odpovědi |
| `Unknown charger state` / `Unsupported identity` | Pošlete vrácené hodnoty před změnou ovládání |

Při řešení chyby pošlete celý detail z formuláře nebo řádek logu
`BENY setup validation failed`. Samotná adresa registru příčinu neurčuje.
