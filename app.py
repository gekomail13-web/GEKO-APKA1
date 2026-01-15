import streamlit as st
import pdfplumber
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 🧠 MÓZG SYSTEMU (Konfiguracja)
# ==========================================

# Twoje dane (do ignorowania)
MOJ_NIP = "7722420459"
MOJA_NAZWA = "GEKO"

# Zasada: Maksymalna kwota, jakiej może brakować, żebyś dzwonił (300 zł)
MAX_BRAK = 300.00

# BAZA WIEDZY (Słowo klucz -> Co proponować)
# To jest ten "idealny podpowiadacz"
CROSS_SELLING = {
    # --- GRUPA: DREWNO / LAS ---
    "prowadnic": {"towar": "Ostrzałka elektr. (G81207)", "arg": "Klient tnie drewno -> musi ostrzyć łańcuchy."},
    "łańcuch": {"towar": "Olej do łańcuchów (G82000)", "arg": "Eksploatacja piły. Olej schodzi zawsze."},
    "siekier": {"towar": "Ostrzałka 2w1 (T02-009)", "arg": "Tani dodatek przy kasie (15 zł)."},
    
    # --- GRUPA: WARSZTAT / AUTO ---
    "wykrętak": {"towar": "Gwintowniki (G38301)", "arg": "Po wykręceniu urwanej śruby trzeba naprawić gwint."},
    "prostownik": {"towar": "Kable rozruchowe (G02400)", "arg": "Zestaw zimowy. Klienci często biorą komplet."},
    "podnośnik": {"towar": "Kobyłki warsztatowe (G02160)", "arg": "Bezpieczeństwo (BHP). Nie wolno pracować na samym podnośniku."},
    "pneumaty": {"towar": "Wąż zakuty / Szybkozłączki", "arg": "Akcesoria do pneumatyki."},
    "klucz udar": {"towar": "Nasadki udarowe", "arg": "Zwykłe nasadki pękną. Potrzebne udarowe."},

    # --- GRUPA: GAZETKOWE SPECJALNE ---
    "szczotk": {"towar": "Kula kominiarska + Lina", "arg": "PROMOCJA KOMINIARSKA: Buduj zestaw, by dobić do 200 zł!"},
    "kula": {"towar": "Lina kominiarska", "arg": "Masz kulę, brakuje liny."},
    "rękawic": {"towar": "Więcej rękawic / Kalosze", "arg": "PROMOCJA BHP: Przy 250 zł jest wieszak, przy 500 zł rabat!"},
    "kalosz": {"towar": "Wkładki filcowe", "arg": "Dodatek do butów."},
    
    # --- WIELOSZTUKI ---
    "nagrzewnic": {"towar": "DRUGA SZTUKA (Rabat!)", "arg": "Wielosztuki: Przy 2 szt. cena drastycznie spada."},
    "wciągark": {"towar": "Zblocze / Uchwyt", "arg": "Promocja na wciągarki (2026AB)."}
}

DOMYSLNA_SUGESTIA = "Chemia warsztatowa (Zmywacze/Smary)"

# ==========================================
# 🔧 SILNIK (Funkcje techniczne)
# ==========================================

def get_best_promotion(text, netto):
    """Decyduje, która promocja jest najważniejsza dla tego zamówienia"""
    t = text.lower()
    promocje = []

    # 1. Kominiarska (Cel: 200 zł)
    if any(x in t for x in ['szczotk', 'wycior', 'kula', 'lina', 'przepychacz']):
        promocje.append({"nazwa": "🔥 Kominiarska", "prog": 200.00, "nagroda": "T-SHIRT (0.01 zł)"})

    # 2. BHP (Cel: 250 zł lub 500 zł)
    if any(x in t for x in ['rękawic', 'kalosz', 'gumofilc', 'obuwie']):
        promocje.append({"nazwa": "🔥 BHP (Mała)", "prog": 250.00, "nagroda": "Wieszak (1 zł)"})
        promocje.append({"nazwa": "🔥 BHP (Duża)", "prog": 500.00, "nagroda": "Rabat 3% + Wieszak"})

    # 3. Ogólne (Cel: 1000 zł lub 3000 zł)
    promocje.append({"nazwa": "Ogólna (Polar)", "prog": 1000.00, "nagroda": "Bluza Polarowa"})
    promocje.append({"nazwa": "Ogólna (Premium)", "prog": 3000.00, "nagroda": "Nagroda Premium"})

    # Wybierz najlepszą (tę, która nie jest spełniona, ale jest najbliżej)
    najlepsza = None
    najmniejszy_brak = 99999.0

    promocje.sort(key=lambda x: x['prog']) # Sortuj od najmniejszych progów

    for p in promocje:
        brak = p['prog'] - netto
        if brak > 0: # Jeśli jeszcze nie osiągnięto progu
            if brak < najmniejszy_brak:
                najmniejszy_brak = brak
                najlepsza = p
    
    # Jeśli wszystkie progi spełnione (np. zamówienie za 5000 zł)
    if not najlepsza:
        return {"nazwa": "MAX", "prog": 0, "nagroda": "Wszystko zdobyte!"}, 0.0

    return najlepsza, najmniejszy_brak

def parse_pdf(file):
    try:
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    except:
        return ""

def extract_data(text):
    # 1. Kwota
    try:
        # Szukamy liczb w formacie 123,45 lub 123.45
        amounts = re.findall(r"(\d+[\.,]\d{2})", text)
        if amounts:
            # Zamień przecinki na kropki i znajdź największą liczbę (zakładamy, że to suma netto)
            netto = max([float(a.replace(',', '.').replace(' ', '')) for a in amounts])
        else:
            netto = 0.0
    except:
        netto = 0.0

    # 2. Klient (FILTR ANTY-GEKO)
    klient = "Klient Nieznany"
    nip = ""
    
    lines = text.splitlines()
    for line in lines:
        # Szukamy linii z NIP-em (10 cyfr), która NIE jest NIP-em GEKO
        nips = re.findall(r'\d{10}', line.replace('-', ''))
        for n in nips:
            if n != MOJ_NIP:
                nip = n
        
        # Szukamy nazwy firmy (heurystyka: linia długa, bez słowa GEKO, bez słowa Sprzedawca)
        if "Nabywca" in line: continue # Pomiń nagłówek
        if len(line) > 4 and MOJA_NAZWA not in line and "Sprzedawca" not in line and "Bank" not in line:
            if klient == "Klient Nieznany": # Weź pierwszą pasującą
                klient = line[:40] # Ucinamy, żeby nie było za długie

    return klient, nip, netto

def get_suggestion(text):
    text_lower = text.lower()
    for key, value in CROSS_SELLING.items():
        if key in text_lower:
            return value
    return {"towar": DOMYSLNA_SUGESTIA, "arg": "Uniwersalny produkt do dobicia progu."}

def send_email(dane, sugestia, secrets):
    if not secrets: return False
    
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 OKAZJA: {dane['klient']} (Brakuje {dane['brak']:.0f} zł)"
    
    body = f"""
    RAPORT SZYBKI:
    --------------------------
    KLIENT: {dane['klient']} (NIP: {dane['nip']})
    ZAMÓWIENIE: {dane['netto']:.2f} zł
    --------------------------
    CEL: {dane['promocja']}
    BRAKUJE: {dane['brak']:.2f} zł
    --------------------------
    SUGESTIA:
    Produkt: {sugestia['towar']}
    Powód: {sugestia['arg']}
    """
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(secrets["EMAIL_NADAWCY"], secrets["HASLO_NADAWCY"])
        server.sendmail(secrets["EMAIL_NADAWCY"], secrets["EMAIL_ODBIORCY"], msg.as_string())
        server.quit()
        return True
    except: return False

# ==========================================
# 📱 APLIKACJA (UI)
# ==========================================
st.set_page_config(page_title="GEKO 3.0", page_icon="🔥")

# Style CSS żeby powiększyć przyciski na telefonie
st.markdown("""
<style>
    div.stButton > button:first-child {
        height: 3em;
        width: 100%;
        font-size: 20px;
        font-weight: bold;
    }
    .big-text { font-size: 24px !important; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🔥 GEKO TERMINATOR")
st.caption("Wersja 3.0: Stabilna & Inteligentna")

# Pobierz hasła (bezpiecznie)
try:
    SECRETS = {
        "EMAIL_NADAWCY": st.secrets["EMAIL_NADAWCY"],
        "HASLO_NADAWCY": st.secrets["HASLO_NADAWCY"],
        "EMAIL_ODBIORCY": st.secrets["EMAIL_ODBIORCY"]
    }
except:
    SECRETS = None
    st.warning("⚠️ Brak konfiguracji maila w Secrets!")

# --- SEKCJA GŁÓWNA ---
uploaded_file = st.file_uploader("Wrzuć Fakturę (PDF)", type="pdf")

# Zmienne sesji (do edycji ręcznej)
if 'netto_val' not in st.session_state: st.session_state.netto_val = 0.0
if 'klient_val' not in st.session_state: st.session_state.klient_val = ""

if uploaded_file:
    text = parse_pdf(uploaded_file)
    k, n, val = extract_data(text)
    
    # Jeśli automat nic nie znalazł (błąd PDF), pozwól wpisać ręcznie
    if val == 0.0:
        st.error("⚠️ Nie udało się odczytać kwoty automatycznie.")
    
    # Formularz edycji (zawsze aktywny dla pewności)
    with st.container(border=True):
        st.markdown("### 📝 Dane Zamówienia")
        col1, col2 = st.columns(2)
        with col1:
            klient_final = st.text_input("Klient", value=k if k else "Klient")
            nip_final = st.text_input("NIP", value=n)
        with col2:
            netto_final = st.number_input("KWOTA NETTO", value=float(val), step=10.0, format="%.2f")

    # --- ANALIZA (DZIEJE SIĘ AUTOMATYCZNIE JAK ZMIENISZ KWOTĘ) ---
    if netto_final > 0:
        promo, brak = get_best_promotion(text, netto_final)
        sugestia = get_suggestion(text)
        
        st.markdown("---")
        st.markdown(f"### 🎯 Cel: {promo['nazwa']}")
        
        # Pasek postępu
        if promo['prog'] > 0:
            postep = min(netto_final / promo['prog'], 1.0)
            st.progress(postep, text=f"Postęp: {int(postep*100)}% (Brakuje {brak:.2f} zł)")
        
        if brak <= 0:
            st.success(f"✅ BRAWO! Próg zdobyty: {promo['nagroda']}")
        elif brak > MAX_BRAK:
            st.info(f"🔵 Brakuje {brak:.2f} zł. Za dużo, by dzwonić (Limit: {MAX_BRAK} zł).")
        else:
            # ALARM - TU JEST PIENIĄDZ
            st.error(f"🔥 ALARM! Brakuje tylko {brak:.2f} zł")
            
            with st.container(border=True):
                st.markdown(f"**💡 PODPOWIEDŹ:** {sugestia['towar']}")
                st.caption(f"Argument: {sugestia['arg']}")
                
                # Gotowiec SMS
                sms = f"Dzień dobry! Brakuje Panu {brak:.0f} zł do promocji '{promo['nazwa']}'. Może dorzucimy {sugestia['towar']}?"
                st.code(sms, language="text")
            
            # Przycisk wysyłki
            if st.button("📧 WYŚLIJ RAPORT DO MNIE"):
                dane = {
                    "klient": klient_final, "nip": nip_final, 
                    "netto": netto_final, "brak": brak, "promocja": promo['nazwa']
                }
                if send_email(dane, sugestia, SECRETS):
                    st.toast("Mail wysłany!", icon="✅")
                else:
                    st.error("Błąd wysyłki.")
