# Stavová obrazovka PC

Program pro Windows posílá místní čas, vytížení CPU a obsazení RAM přes Bluetooth LE na panel iPixel Color s maticí 64 × 16. Údaje obnovuje každých 10 sekund. Panel používá nejnižší jas a dvojtečka u hodin se rozsvěcí a zhasíná po půl sekundě. Animaci zobrazuje dočasně.

## Aplikace pro Windows

1. Stáhni [LED-Panel.exe](https://github.com/Takashiri/led-panel-pc/releases/latest/download/LED-Panel.exe), zapni Bluetooth ve Windows a připoj napájení panelu.
2. Vyber panel ze seznamu a klikni na **Připojit**. Pokud ho aplikace nenašla, zavři iPixel Color v telefonu a použij **Vyhledat**.
3. **Zapnout** zobrazí stav PC a **Vypnout** zhasne panel. Aplikace si zapamatuje vybraný panel a jeho stav. Po dalším spuštění nebo výpadku Bluetooth se k němu zkusí znovu připojit.

Zavřením okna přes **×** se aplikace skryje k hodinám. Pravým kliknutím na její ikonu zobrazíš nabídku **Otevřít** a **Ukončit**. Volbou **Ukončit** aplikaci zavřeš úplně. Windows může ikonu umístit pod šipku **^**. Tlačítko **Odpojit** uvolní Bluetooth spojení a zastaví pokusy o připojení pro aktuální spuštění aplikace.

V **Nastavení → Spuštění aplikace** můžeš zapnout **Spustit s Windows**. Aplikace se otevře po přihlášení k tvému účtu. Volba **Spustit skrytě u hodin** nechá hlavní okno skryté. Volba **Obnovit poslední obrazovku** se použije i při ručním spuštění. Když `.exe` přesuneš, otevři ho z nového umístění a znovu ulož nastavení, aby Windows použil novou cestu.

## Obrazovky displeje

- **Stav PC** zobrazuje hodiny, vytížení CPU a obsazení RAM.
- **Počasí** zobrazuje teplotu ve °C a relativní vlhkost. V okně **Nastavení** vyhledej město, vyber odpovídající výsledek a klikni na **Uložit**. Aktuální modelová data dodává [Open-Meteo](https://open-meteo.com/en/docs). Bezplatné API je určené pro [nekomerční použití](https://open-meteo.com/en/terms).
- **Novinky.cz** posouvá první titulek z oficiálního RSS kanálu **Zpravodajství**. Aplikace ho načítá přímo na PC pro osobní zobrazení. [Tiráž a RSS kanály Novinky.cz](https://www.novinky.cz/p/tiraz)

Obrazovky se přepínají výběrem v okně nebo výchozí zkratkou **Ctrl+Alt+F9**. Zkratku lze změnit v **Nastavení** a funguje i se skrytým oknem.

Můžeš použít i dvě běžné klávesy současně, například `§+)` na českém rozložení. Přidrž jednu, stiskni druhou a uvolni je. Znaky se určují podle aktuálního rozložení klávesnice.

V **Nastavení → Přechod mezi obrazovkami** vyber efekt a rychlost. Jeden efekt platí pro všechna přepnutí na panelu i v náhledu. K dispozici je deset animací a volba **Bez animace**. Výchozí posun doleva trvá zhruba půl sekundy samotného přehrávání. Pravidelná obnova údajů používá stejnou obrazovku a přechod nespouští.

Na LED panelu a v jeho náhledu se text kreslí ostrými pixely bez diakritiky. V okně aplikace se zobrazují původní názvy a titulky.

Soubor `.exe` lze použít samostatně na 64bitových Windows 10 nebo 11 s Bluetooth LE. Pro jeden panel používej jedno ovládání.

Pokud Windows při spuštění hlásí chybějící `VCRUNTIME140.dll` nebo `VCRUNTIME140_1.dll`, nainstaluj [Microsoft Visual C++ Redistributable pro x64](https://aka.ms/vc14/vc_redist.x64.exe).

### Aktualizace

Od verze 1.2.1 kontroluje samostatné `.exe` při spuštění a poté jednou denně nové stabilní vydání na GitHubu. Kontrolu můžeš spustit i tlačítkem **Zkontrolovat aktualizace**. Když se objeví novější vydání, klikni na **Nainstalovat a restartovat**. Aplikace ověří SHA-256 staženého souboru podle údajů z GitHubu a nahradí své `.exe`. Zapamatovaný panel, lokalita a zkratka zůstanou uložené. Předchozí `.exe` se uloží vedle aplikace s příponou `.previous`.

První přechod z verze 1.2.0 nebo starší udělej ručním stažením [nového EXE](https://github.com/Takashiri/led-panel-pc/releases/latest/download/LED-Panel.exe). Před výměnou zavři aplikaci přes **Ukončit** v nabídce u hodin.

## Spuštění z příkazové řádky

1. Zapoj panel do napájení, zapni Bluetooth ve Windows a zavři aplikaci iPixel Color v telefonu.
2. Otevři `Spustit.cmd` a zadej číslo svého panelu. Ve výpisu se obvykle jmenuje `LED_BLE_…`.
3. Okno nech běžet. Program ukončíš pomocí `Ctrl+C`.

Po výpadku Bluetooth se program zkusí znovu připojit ke stejnému panelu. Pokud se panel nedaří najít, odpoj ho na chvíli od napájení a spusť vyhledávání znovu.

## Příkazy v PowerShellu

```powershell
.\Spustit.cmd --scan
.\Spustit.cmd --preview preview.png
.\Spustit.cmd --once
```

Pro spuštění bez výběru zadej adresu z příkazu `--scan` pomocí `--address`. Parametr `--interval` mění počet sekund mezi kontrolami stavu PC.

## Instalace na jiném PC

S nainstalovaným Pythonem 3.12 spusť ve složce projektu tyto příkazy a pak otevři `Spustit.cmd`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Ovládání panelu zajišťuje knihovna [pypixelcolor](https://github.com/lucagoc/pypixelcolor).

## Sestavení aplikace

Po instalaci závislostí lze s Pythonem a Tcl/Tk vytvořit nový soubor `dist/LED-Panel.exe`.

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller==6.22.3
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm release.spec
```

Vydání obsahuje [licenční oznámení přibalených součástí](THIRD-PARTY-NOTICES.txt).
