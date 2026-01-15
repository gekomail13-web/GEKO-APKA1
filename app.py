import streamlit as st
import pdfplumber
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 1. KONFIGURACJA (Twoje Dane)
# ==========================================
# Te dane będą WYCINANE z faktury, żeby nie pomylić Ciebie z klientem
MOJE_DANE = [
    "GEKO", "7722420459", "Sp.k.", "Sp. z o.o.", "Kietlin", "Radomsko", 
    "Sprzedawca", "Wystawca", "Bank", "Konto", "BDO"
]

# Limit interwencji
MAX_BRAK_PLN = 300.00

# ==========================================
# 2. BAZA PROMOCJI (Z Twoich Gazetek)
# ==========================================

# Promocje Progowe
PROMOS = [
    # KOMINIARSKA AB.pdf
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    
    # RĘKAWICE AB.pdf + KALOSZE AB.pdf (BHP)
    # Produkty: Rękawice (G735.., G750..), Kalosze (G905..)
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    
    # OGÓLNE (Domyślne progi)
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

# Wielosztuki (2026AB.pdf) - Wykrywanie po kodach
WIELOSZTUKI = {
    "g01097": "Wciągarka 3T - Taniej przy 2 szt!",
    "g01362": "Nożyce do drutu 30\" - Taniej przy 2 szt!",
    "g01363": "Nożyce do drutu 36\" - Taniej przy 2 szt!",
    "g02180": "Podnośnik ATV - Taniej przy 2 szt!",
    "g73866": "Łańcuchy śniegowe - Zestaw tańszy!",
    "g80443": "Grzejnik Konwektor - Taniej przy 2 szt!",
    "g80444": "Grzejnik LCD - Taniej przy 2 szt!",
    "g80446": "Grzejnik Szklany - Taniej przy 2 szt!",
    "g02648": "Klucze - Sprawdź ilość!",
    "g10868": "Regał magazynowy - Hit Stycznia", # Z Gazetki Styczeń
    "g80535": "Wentylator kominkowy - Hit Stycznia" #
}

# Cross-Selling (Sugestie)
SUGESTIE_CROSS = {
    "prowadnic": "Ostrzałka elektr. (G81207) - Serwis pił",
    "siekier": "Ostrzałka 2w1 (T02-009) - Tani dodatek",
    "szczotk": "Kula + Lina - Zbuduj zestaw do 200 zł! [Kominiarska]",
    "kula": "Lina kominiarska - Do kompletu",
    "rękawic": "Kalosze / Więcej par - Dobij do 250 zł (Wieszak) [BHP]",
    "kalosz": "Wkładki filcowe / Rękawice",
    "nagrzewnic": "Sprawdź drugą sztukę (Wielosztuka 2026AB)"
}

# ==========================================
# 3. SILNIK ANALIZY (Poprawiony Nabywca)
# ==========================================

def clean_text(text):
    if not text: return ""
    return text.replace('\xa0', ' ')

def extract_client_data_aggressive(text):
    """
    Nowy, agresywny algorytm szukania klienta.
    Ignoruje pozycję linii, szuka 'blokowo' po słowie Nabywca.
    """
    lines = text.splitlines()
    client_name = ""
    client_nip = ""
    
    # 1. Znajdź NIP Klienta (dowolny 10 cyfr, który nie jest Twój)
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":
            client_nip = nip
            break
            
    # 2. Szukanie Nazwy Firmy
    # Strategia: Znajdź linię z "Nabywca", weź 5 kolejnych linii.
    # Filtruj każdą linię przez listę zakazanych słów (MOJE_DANE).
    # Pierwsza, która przetrwa, to klient.
    
    candidates = []
    start_capture = False
    buffer_counter = 0
    
    for line in lines:
        # Start capture przy słowie Nabywca/Płatnik/Odbiorca
        if any(x in line for x in ["Nabywca", "Płatnik", "Odbiorca"]):
            start_capture = True
            buffer_counter = 0
            continue # Pomiń samą linię z nagłówkiem
            
        if start_capture:
            buffer_counter += 1
            if buffer_counter > 6: # Szukamy tylko w 6 liniach pod nagłówkiem
                start_capture = False
            
            clean = line.strip()
            
            # FILTRY ODRZUCAJĄCE
            is_bad = False
            if len(clean) < 3: is_bad = True
            if any(bad in clean for bad in MOJE_DANE): is_bad = True # Odrzuca GEKO itp.
            if re.search(r'\d{10}', clean.replace('-','')): is_bad = True # Odrzuca linię z samym NIPem
            if "Adres" in clean or "Data" in clean: is_bad = True
            
            if not is_bad:
                candidates.append(clean)

    if candidates:
        client_name = candidates[0] # Bierzemy pierwszego kandydata
    else:
        client_name = "Nie wykryto (Wpisz ręcznie)"

    return client_name, client_nip

def extract_amount_and_codes(text):
    # Kwota
    try:
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = []
        for a in amounts:
            try:
                # Usuń spacje, zamień przecinki na kropki
                val = float(a.replace(' ', '').replace(',', '.').replace('\xa0', ''))
                clean_amounts.append(val)
            except: pass
        netto = max(clean_amounts) if clean_amounts else 0.0
    except:
        netto = 0.0
        
    # Kody Gxxxxx
    found_codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches:
        found_codes.add(m.lower())
        
    return netto, found_codes

def analyze_promotion(text, amount):
    text_lower = text.lower()
    best_promo = None
    min_gap = 99999.0
    
    # 1. Sprawdź dedykowane (Kominiarka, BHP)
    dedicated_active = False
    sorted_promos = sorted(PROMOS, key=lambda x: x[1]) # Sortuj od najniższych progów
    
    for keywords, threshold, reward, name in sorted_promos:
        if keywords: # Jeśli to promocja specjalna
            if any(k in text_lower for k in keywords):
                gap = threshold - amount
                if gap > 0 and gap < min_gap:
                    min_gap = gap
                    best_promo = (name, threshold, reward)
                    dedicated_active = True
                # Jeśli próg BHP (250) osiągnięty, pozwól szukać kolejnego (500)
                elif gap <= 0 and gap > -500: 
                    pass 

    # 2. Jeśli brak dedykowanej (lub spełniona), sprawdź ogólne
    if not dedicated_active:
        for keywords, threshold, reward, name in sorted_promos:
            if not keywords: # Ogólna
                gap = threshold - amount
                if gap > 0 and gap < min_gap:
                    min_gap = gap
                    best_promo = (name, threshold, reward)

    if not best_promo:
         return ("MAX", 0.0, "Wszystko zdobyte!"), 0.0
         
    return best_promo, min_gap

def get_suggestions(text, found_codes):
    sug = []
    text_lower = text.lower()
    
    # Wielosztuki
    for code, msg in WIELOSZTUKI.items():
        if code in found_codes:
            sug.append(f"📦 **WIELOSZTUKA:** {msg}")
            
    # Cross-selling
    for k, v in SUGESTIE_CROSS.items():
        if k in text_lower:
            sug.append(f"💡 **SUGESTIA:** {v}")
            
    if not sug: sug.append("💡 Sugestia: Chemia warsztatowa (uniwersalna)")
    return list(set(sug)) # Usuń duplikaty

def send_email_report(data, secrets):
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {data['client']} - Brakuje {data['gap']:.0f} zł"
    
    body = f"""
    KLIENT: {data['client']} (NIP: {data['nip']})
    KWOTA:  {data['amount']:.2f} zł
    --------------------------------
    CEL:     {data['promo_name']} ({data['promo_target']} zł)
    BRAKUJE: {data['gap']:.2f} zł
    NAGRODA: {data['promo_reward']}
    --------------------------------
    {chr(10).join(data['suggestions'])}
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
# 4. UI (Streamlit)
# ==========================================
st.set_page_config(page_title="GEKO PANZER", page_icon="🛡️", layout="centered")

st.markdown("""
<style>
    .stButton>button {
        width: 100%; height: 60px; font-size: 24px; font-weight: bold;
        background-color: #d63031; color: white; border-radius: 8px;
    }
    .big-input input { font-size: 20px !important; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

try:
    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
except: SECRETS = None

st.title("🛡️ GEKO PANZER 6.0")
st.caption("Najmocniejszy silnik wykrywania klientów")

uploaded_file = st.file_uploader("WRZUĆ PDF", type="pdf")

if uploaded_file:
    # 1. Parsowanie
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            raw_text += page.extract_text() or ""
    text = clean_text(raw_text)
    
    # 2. Ekstrakcja Danych
    d_client, d_nip = extract_client_data_aggressive(text)
    d_amount, d_codes = extract_amount_and_codes(text)
    
    # 3. PANEL WERYFIKACJI (Góra Ekranu)
    st.success("👇 DANE KLIENTA (Edytuj jeśli trzeba) 👇")
    c1, c2 = st.columns([2, 1])
    with c1:
        f_client = st.text_input("NAZWA KLIENTA", value=d_client)
        f_nip = st.text_input("NIP", value=d_nip)
    with c2:
        f_amount = st.number_input("NETTO (PLN)", value=float(d_amount), step=10.0)

    # 4. ANALIZA
    if f_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, f_amount)
        suggestions = get_suggestions(text, d_codes)
        
        st.divider()
        if p_target > 0:
            prog = min(f_amount / p_target, 1.0)
            st.progress(prog, text=f"Postęp: {int(prog*100)}% (Cel: {p_target} zł)")
            
        if gap <= 0:
            st.balloons()
            st.success(f"✅ ZDOBYTE: {p_reward} ({p_name})")
        elif gap > MAX_BRAK_PLN:
            st.info(f"🔵 Brakuje {gap:.2f} zł. Powyżej limitu interwencji.")
        else:
            st.error(f"🔥 ALARM! BRAKUJE {gap:.2f} ZŁ")
            st.markdown(f"### 🎁 Nagroda: {p_reward}")
            
            with st.container(border=True):
                st.write("💡 **PODPOWIEDZI:**")
                for s in suggestions:
                    st.write(s)
                
                # SMS
                sms_item = suggestions[0].split(':')[-1].strip() if suggestions else "Chemia"
                sms = f"Dzien dobry! Tu GEKO. Brakuje Panu {gap:.0f} zl do promocji '{p_name}'. Moze dorzucimy: {sms_item}?"
                st.code(sms, language="text")
                
            if st.button("📧 WYŚLIJ RAPORT"):
                dat = {"client": f_client, "nip": f_nip, "amount": f_amount, 
                       "gap": gap, "promo_name": p_name, "promo_target": p_target, 
                       "promo_reward": p_reward, "suggestions": suggestions}
                if send_email_report(dat, SECRETS):
                    st.toast("Wysłano!", icon="✅")
                else: st.error("Błąd wysyłki")
    else:
        st.warning("⚠️ Brak kwoty. Wpisz ręcznie.")
