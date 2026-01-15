import streamlit as st
import pdfplumber
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 1. KONFIGURACJA DANYCH
# ==========================================
MOJE_DANE = ["GEKO", "7722420459", "Sprzedawca", "Kietlin", "Radomsko"]
MAX_BRAK_PLN = 300.00

# ==========================================
# 2. BAZA PROMOCJI (GAZETKI)
# ==========================================

# Format: ([Słowa kluczowe], Próg, Nagroda, Nazwa)
PROMOS = [
    # KOMINIARSKA AB
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "zestaw komin", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    
    # BHP (RĘKAWICE + KALOSZE)
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    
    # OGÓLNE
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

# WIELOSZTUKI (2026AB) - Kody
WIELOSZTUKI = {
    "G01097": "Wciągarka 3T - Taniej przy 2 szt!",
    "G01362": "Nożyce 30\" - Taniej przy 2 szt!",
    "G01363": "Nożyce 36\" - Taniej przy 2 szt!",
    "G02180": "Podnośnik ATV - Taniej przy 2 szt!",
    "G73866": "Łańcuchy śniegowe - Zestaw tańszy!",
    "G80443": "Grzejnik Konwektor - Taniej przy 2 szt!",
    "G80444": "Grzejnik LCD - Taniej przy 2 szt!",
    "G80446": "Grzejnik Szklany - Taniej przy 2 szt!",
    "G02648": "Klucze - Sprawdź progi!",
    "G10868": "Regał - Hit Stycznia",
    "G29026": "Nożyk do tapet - Hit Cena"
}

# CROSS-SELLING
SUGESTIE_CROSS = {
    "prowadnic": "Ostrzałka elektr. (G81207)",
    "siekier": "Ostrzałka 2w1 (T02-009)",
    "szczotk": "Kula + Lina (Kominiarska)",
    "kula": "Lina kominiarska",
    "rękawic": "Kalosze / Gumofilce (BHP)",
    "kalosz": "Wkładki filcowe",
    "nagrzewnic": "Druga sztuka (Wielosztuka)"
}

# ==========================================
# 3. SILNIK PARSOWANIA (DEDYKOWANY POD SOLEX)
# ==========================================

def clean_text(text):
    return text.replace('\xa0', ' ') if text else ""

def extract_client_data_titan(text):
    """
    Algorytm Tytan: Łączy metodę pozycyjną (Solex) i słownikową.
    """
    lines = text.splitlines()
    client_name = "Nie wykryto klienta"
    client_nip = ""
    
    # 1. NIP (Szukamy każdego, który nie jest GEKO)
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":
            client_nip = nip
            break
            
    # 2. NAZWA KLIENTA - Logika SolexB2B
    # Szukamy linii "Nabywca". Następna linia, która NIE jest pusta i NIE jest NIPem, to nazwa.
    found_nabywca = False
    for i, line in enumerate(lines):
        if "Nabywca" in line:
            # Sprawdzamy kilka linii w dół
            for offset in range(1, 5): 
                if i + offset >= len(lines): break
                
                candidate = lines[i + offset].strip()
                
                # Filtry:
                if len(candidate) < 3: continue
                if "NIP" in candidate: continue
                if re.search(r'\d{10}', candidate.replace('-','')): continue # To linia z NIPem
                if any(x in candidate for x in MOJE_DANE): continue # To dane GEKO
                
                # Jeśli przeszło filtry -> To Klient!
                client_name = candidate
                found_nabywca = True
                break
        if found_nabywca: break

    # Fallback (Jeśli metoda Solex zawiedzie, szukamy czegokolwiek co nie jest GEKO)
    if client_name == "Nie wykryto klienta":
        for line in lines:
            if "Nabywca" in line: continue
            if len(line) > 5 and "GEKO" not in line.upper() and "SPRZEDAWCA" not in line.upper():
                 # Bardzo luźna heurystyka - bierzemy pierwszą linię wyglądającą na firmę
                 if not re.search(r'\d', line): # Brak cyfr (adresy mają cyfry)
                     client_name = line.strip()
                     break

    return client_name, client_nip

def extract_amount_and_codes(text):
    # Kwota
    try:
        # Szuka: 1 234,56 lub 1234.56
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = []
        for a in amounts:
            try:
                # Normalizacja
                val = float(a.replace(' ', '').replace(',', '.').replace('\xa0', ''))
                clean_amounts.append(val)
            except: pass
        netto = max(clean_amounts) if clean_amounts else 0.0
    except:
        netto = 0.0
        
    # Kody Produktów (Gxxxxx)
    codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches: codes.add(m)
        
    return netto, codes

def analyze_promotion(text, amount):
    text_lower = text.lower()
    best = None
    min_gap = 99999.0
    
    # 1. Dedykowane
    dedyk_active = False
    sorted_promos = sorted(PROMOS, key=lambda x: x[1])
    
    for keywords, thresh, reward, name in sorted_promos:
        if keywords and any(k in text_lower for k in keywords):
            gap = thresh - amount
            if gap > 0 and gap < min_gap:
                min_gap = gap
                best = (name, thresh, reward)
                dedyk_active = True
            elif gap <= 0 and gap > -1000: # Jeśli spełniona, szukaj wyższej w tej kategorii
                continue

    # 2. Ogólne
    if not dedyk_active:
        for keywords, thresh, reward, name in sorted_promos:
            if not keywords:
                gap = thresh - amount
                if gap > 0 and gap < min_gap:
                    min_gap = gap
                    best = (name, thresh, reward)
                    
    if not best: return ("MAX", 0.0, "WSZYSTKO ZDOBYTE"), 0.0
    return best, min_gap

def get_suggestions(text, codes):
    sug = []
    text_lower = text.lower()
    
    # Wielosztuki (po kodach)
    for c, msg in WIELOSZTUKI.items():
        if c in codes:
            sug.append(f"📦 **{c}:** {msg}")
            
    # Cross-selling (po słowach)
    for k, v in SUGESTIE_CROSS.items():
        if k in text_lower:
            sug.append(f"💡 **SUGESTIA:** {v}")
            
    if not sug: sug.append("💡 Sugestia: Chemia warsztatowa")
    return list(set(sug))

def send_email_report(data, secrets):
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {data['client']} - Brakuje {data['gap']:.0f} zł"
    
    body = f"""
    KLIENT: {data['client']}
    NIP:    {data['nip']}
    KWOTA:  {data['amount']:.2f} zł
    ---------------------------------
    CEL:     {data['promo_name']} ({data['promo_target']} zł)
    BRAKUJE: {data['gap']:.2f} zł
    NAGRODA: {data['promo_reward']}
    ---------------------------------
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
# 4. UI APLIKACJI
# ==========================================
st.set_page_config(page_title="GEKO TYTAN", page_icon="🏛️", layout="centered")

# CSS - Wielkie przyciski na telefon
st.markdown("""
<style>
    .stButton>button {
        width: 100%; height: 65px; font-size: 22px; font-weight: bold;
        background-color: #d63031; color: white; border-radius: 8px;
    }
    input { font-weight: bold; }
</style>
""", unsafe_allow_html=True)

try:
    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
except: SECRETS = None

st.title("🏛️ GEKO TYTAN 7.0")
st.caption("Specjalizacja: Platforma SolexB2B")

uploaded_file = st.file_uploader("WRZUĆ PDF Z ZAMÓWIENIEM", type="pdf")

if uploaded_file:
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages: raw_text += page.extract_text() or ""
    text = clean_text(raw_text)
    
    # Ekstrakcja
    d_client, d_nip = extract_client_data_titan(text)
    d_amount, d_codes = extract_amount_and_codes(text)
    
    # PANEL EDYCJI (Zawsze widoczny)
    st.info("👇 WERYFIKACJA DANYCH 👇")
    c1, c2 = st.columns([2, 1])
    with c1:
        f_client = st.text_input("KLIENT", value=d_client)
        f_nip = st.text_input("NIP", value=d_nip)
    with c2:
        f_amount = st.number_input("NETTO", value=float(d_amount), step=10.0)
        
    # ANALIZA
    if f_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, f_amount)
        suggestions = get_suggestions(text, d_codes)
        
        st.divider()
        if p_target > 0:
            prog = min(f_amount / p_target, 1.0)
            st.progress(prog, text=f"Postęp: {int(prog*100)}% (Cel: {p_target} zł)")
            
        if gap <= 0:
            st.balloons()
            st.success(f"✅ ZDOBYTE: {p_reward}!")
        elif gap > MAX_BRAK_PLN:
            st.info(f"🔵 Brakuje {gap:.2f} zł. Powyżej limitu interwencji.")
        else:
            st.error(f"🔥 ALARM! BRAKUJE {gap:.2f} ZŁ")
            st.markdown(f"**Nagroda:** {p_reward}")
            
            with st.container(border=True):
                st.write("💡 **PODPOWIEDZI:**")
                for s in suggestions: st.write(s)
                
                # SMS
                item = suggestions[0].split(':')[-1].strip() if suggestions else "Chemia"
                sms = f"Dzien dobry! Brakuje Panu {gap:.0f} zl do promocji '{p_name}'. Moze dorzucimy: {item}?"
                st.code(sms, language="text")
                
            if st.button("📧 WYŚLIJ RAPORT"):
                dat = {"client": f_client, "nip": f_nip, "amount": f_amount,
                       "gap": gap, "promo_name": p_name, "promo_target": p_target,
                       "promo_reward": p_reward, "suggestions": suggestions}
                if send_email_report(dat, SECRETS):
                    st.toast("Wysłano!", icon="✅")
                else: st.error("Błąd maila")
    else:
        st.warning("⚠️ Wpisz kwotę ręcznie.")
