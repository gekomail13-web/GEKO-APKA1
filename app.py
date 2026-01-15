import streamlit as st
import pdfplumber
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# ⚙️ KONFIGURACJA
# ==========================================
MOJ_NIP = "7722420459"
MOJA_NAZWA = "GEKO" # To słowo będzie ignorowane przy szukaniu klienta
MAX_BRAK = 300.00   # Limit interwencji

# BAZA CROSS-SELLING (Podpowiadacz)
CROSS_SELLING = {
    # DREWNO
    "prowadnic": {"towar": "Ostrzałka elektr. (G81207)", "arg": "Serwis pił - towar powiązany."},
    "łańcuch": {"towar": "Olej do łańcuchów (G82000)", "arg": "Eksploatacja piły."},
    "siekier": {"towar": "Ostrzałka 2w1 (T02-009)", "arg": "Tani dodatek przy kasie."},
    # WARSZTAT
    "wykrętak": {"towar": "Gwintowniki (G38301)", "arg": "Naprawa gwintów po wykręcaniu."},
    "prostownik": {"towar": "Kable rozruchowe (G02400)", "arg": "Zestaw zimowy."},
    "podnośnik": {"towar": "Kobyłki warsztatowe", "arg": "BHP - nie pracujemy na samym podnośniku."},
    "klucz udar": {"towar": "Nasadki udarowe", "arg": "Zwykłe pękną, potrzebne udarowe."},
    # GAZETKOWE
    "szczotk": {"towar": "Kula + Lina", "arg": "🔥 Kominiarska: Buduj zestaw do 200 zł!"},
    "kula": {"towar": "Lina kominiarska", "arg": "🔥 Kominiarska: Masz kulę, brakuje liny."},
    "rękawic": {"towar": "Więcej rękawic / Kalosze", "arg": "🔥 BHP: Walcz o wieszak lub rabat!"},
    "kalosz": {"towar": "Wkładki filcowe", "arg": "🔥 BHP: Kalosze wliczają się do promocji."},
    # WIELOSZTUKI
    "nagrzewnic": {"towar": "DRUGA SZTUKA (Rabat!)", "arg": "Wielosztuki: Przy 2 szt. cena spada."},
}
DOMYSLNA_SUGESTIA = "Chemia warsztatowa / Zmywacze"

# ==========================================
# 🔧 SILNIK
# ==========================================

def get_best_promotion(text, netto):
    t = text.lower()
    promocje = []
    
    # 1. Kominiarska (200 zł)
    if any(x in t for x in ['szczotk', 'wycior', 'kula', 'lina']):
        promocje.append({"nazwa": "🔥 Kominiarska", "prog": 200.00, "nagroda": "T-SHIRT"})
    # 2. BHP (250/500 zł)
    if any(x in t for x in ['rękawic', 'kalosz', 'gumofilc']):
        promocje.append({"nazwa": "🔥 BHP (Mała)", "prog": 250.00, "nagroda": "Wieszak"})
        promocje.append({"nazwa": "🔥 BHP (Duża)", "prog": 500.00, "nagroda": "Rabat 3%"})
    # 3. Ogólne
    promocje.append({"nazwa": "Ogólna (Polar)", "prog": 1000.00, "nagroda": "Polar"})
    promocje.append({"nazwa": "Ogólna (Premium)", "prog": 3000.00, "nagroda": "Premium"})

    najlepsza = None
    min_brak = 99999.0
    
    promocje.sort(key=lambda x: x['prog'])
    
    for p in promocje:
        brak = p['prog'] - netto
        if brak > 0: # Szukamy nieosiągniętego celu
            if brak < min_brak:
                min_brak = brak
                najlepsza = p
    
    # Jeśli wszystko zdobyte
    if not najlepsza: return {"nazwa": "MAX", "prog": 0, "nagroda": "FULL"}, 0.0
    return najlepsza, min_brak

def parse_pdf(file):
    try:
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    except: return ""

def extract_data_smart(text):
    # 1. KWOTA
    try:
        amounts = re.findall(r"(\d+[\.,]\d{2})", text)
        if amounts:
            netto = max([float(a.replace(',', '.').replace(' ', '')) for a in amounts])
        else: netto = 0.0
    except: netto = 0.0

    # 2. KLIENT (To jest ta nowa, ulepszona część)
    klient = "Nieznany Klient"
    nip = ""
    lines = text.splitlines()
    
    # Szukanie NIP (Ignorując Twój)
    found_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for n in found_nips:
        if n != MOJ_NIP:
            nip = n
            break # Bierzemy pierwszy NIP, który nie jest Twój

    # Szukanie Nazwy Firmy
    # Logika: Szukamy linii po słowie "Nabywca", która nie zawiera "GEKO"
    szukam_klienta = False
    for line in lines:
        if "Nabywca" in line or "Płatnik" in line:
            szukam_klienta = True
            continue # Przeskocz nagłówek
        
        if szukam_klienta:
            clean_line = line.strip()
            # Warunki:
            # 1. Nie jest pusta
            # 2. Nie zawiera słowa GEKO (bez względu na wielkość liter)
            # 3. Nie zawiera słowa "Sprzedawca"
            # 4. Ma więcej niż 3 znaki
            if len(clean_line) > 3 and "GEKO" not in clean_line.upper() and "SPRZEDAWCA" not in clean_line.upper():
                klient = clean_line[:40] # Bierzemy tę linię jako nazwę klienta
                break # Mamy go, kończymy szukanie
            
            # Jeśli trafiliśmy na "Adres dostawy" lub "Sprzedawca", przerywamy
            if "Adres" in line or "Sprzedawca" in line:
                break

    return klient, nip, netto

def get_suggestion(text):
    t = text.lower()
    for k, v in CROSS_SELLING.items():
        if k in t: return v
    return {"towar": DOMYSLNA_SUGESTIA, "arg": "Uniwersalny produkt."}

def send_email(dane, sugestia, secrets):
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {dane['klient']} - Brakuje {dane['brak']:.0f} zł"
    
    body = f"""
    KLIENT: {dane['klient']}
    NIP: {dane['nip']}
    ====================
    ZAMÓWIENIE: {dane['netto']:.2f} zł
    CEL: {dane['promocja']}
    BRAKUJE: {dane['brak']:.2f} zł
    ====================
    SUGESTIA: {sugestia['towar']}
    POWÓD: {sugestia['arg']}
    """
    msg.attach(MIMEText(body, 'plain'))
    try:
        s = smtplib.SMTP('smtp.gmail.com', 587)
        s.starttls()
        s.login(secrets["EMAIL_NADAWCY"], secrets["HASLO_NADAWCY"])
        s.sendmail(secrets["EMAIL_NADAWCY"], secrets["EMAIL_ODBIORCY"], msg.as_string())
        s.quit()
        return True
    except: return False

# ==========================================
# 📱 INTERFEJS
# ==========================================
st.set_page_config(page_title="GEKO 4.0", page_icon="🕵️‍♂️")

# CSS - Wielkie przyciski
st.markdown("""
<style>
    div.stButton > button:first-child { height: 3.5em; font-size: 22px; font-weight: bold; background-color: #ff4b4b; color: white; }
    input { font-size: 1.2rem !important; }
</style>
""", unsafe_allow_html=True)

try:
    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
except: SECRETS = None

st.title("🕵️‍♂️ GEKO - KTO DZWONI?")

uploaded_file = st.file_uploader("Wrzuć PDF", type="pdf")

if uploaded_file:
    text = parse_pdf(uploaded_file)
    k, n, val = extract_data_smart(text)
    
    # --- FORMULARZ EDYCJI (NA SAMEJ GÓRZE) ---
    st.info("👇 SPRAWDŹ DANE KLIENTA 👇")
    col1, col2 = st.columns([2, 1])
    with col1:
        # To pole pozwala Ci poprawić nazwę, jeśli system się pomyli
        klient_final = st.text_input("NAZWA KLIENTA", value=k)
        nip_final = st.text_input("NIP", value=n)
    with col2:
        netto_final = st.number_input("NETTO (PLN)", value=float(val), step=10.0)

    # --- ANALIZA ---
    if netto_final > 0:
        promo, brak = get_best_promotion(text, netto_final)
        sugestia = get_suggestion(text)
        
        st.markdown("---")
        st.markdown(f"### 🎯 CEL: {promo['nazwa']}")
        
        # Pasek
        if promo['prog'] > 0:
            postep = min(netto_final / promo['prog'], 1.0)
            st.progress(postep, text=f"Postęp: {int(postep*100)}% (Brakuje {brak:.2f} zł)")

        # Logika decyzji
        if brak <= 0:
            st.balloons()
            st.success(f"✅ ZDOBYTE: {promo['nagroda']}")
        elif brak > MAX_BRAK:
            st.info(f"🔵 Brakuje {brak:.2f} zł. Za dużo, nie dzwonimy.")
        else:
            st.error(f"🔥 DZWONIĆ! BRAKUJE {brak:.2f} zł")
            
            with st.container(border=True):
                st.markdown(f"**💡 PODPOWIEDŹ:** {sugestia['towar']}")
                st.caption(sugestia['arg'])
                
                # Gotowiec SMS
                sms = f"Dzień dobry! Tu GEKO. Brakuje Panu {brak:.0f} zł do promocji '{promo['nazwa']}'. Może dorzucimy {sugestia['towar']}?"
                st.code(sms, language="text")
            
            if st.button("📧 WYŚLIJ DO MNIE"):
                dane = {"klient": klient_final, "nip": nip_final, "netto": netto_final, "brak": brak, "promocja": promo['nazwa']}
                if send_email(dane, sugestia, SECRETS):
                    st.toast("Wysłano!", icon="✅")
                else: st.error("Błąd maila")
