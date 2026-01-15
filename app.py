import streamlit as st
import pdfplumber
import re
import smtplib
import pandas as pd
from datetime import datetime
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 0. KONFIGURACJA WYGLĄDU (DLA DYREKTORA)
# ==========================================
st.set_page_config(page_title="GEKO SALES DIRECTOR", page_icon="🦁", layout="wide")

# Ukrywamy stopkę Streamlit, żeby wyglądało profesjonalnie
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .metric-card {
                background-color: #ffffff;
                border-left: 5px solid #d63031;
                border-radius: 5px;
                padding: 15px;
                box-shadow: 2px 2px 10px rgba(0,0,0,0.05);
            }
            .stButton>button {
                width: 100%;
                font-weight: bold;
                border-radius: 8px;
                height: 55px;
                font-size: 18px;
            }
            /* Powiększenie czcionki w polach edycji */
            input { font-size: 18px !important; font-weight: 600 !important; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==========================================
# 1. BAZA DANYCH (SŁOWNIKI I REGUŁY)
# ==========================================

# DANE GEKO (DO FILTROWANIA - TEGO SYSTEM MA NIE CZYTAĆ JAKO KLIENTA)
MOJE_DANE = ["GEKO", "7722420459", "Sprzedawca", "Kietlin", "Radomsko", "Sp.k.", "Spółka"]
MAX_BRAK_PLN = 300.00  # Powyżej tej kwoty braku nie dzwonimy

# PROMOCJE PROGOWE (Z TWOICH PLIKÓW PDF)
PROMOS = [
    # KOMINIARSKA AB
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    
    # BHP (RĘKAWICE + KALOSZE)
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    
    # OGÓLNE (STYCZEŃ)
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

# WIELOSZTUKI (2026AB + STYCZEŃ) - Podpowiedzi po kodach
WIELOSZTUKI = {
    "G01097": "Wciągarka 3T - Taniej przy 2 szt! (2026AB)",
    "G01362": "Nożyce 30\" - Taniej przy 2 szt! (2026AB)",
    "G02180": "Podnośnik ATV - Taniej przy 2 szt! (2026AB)",
    "G73866": "Łańcuchy śniegowe - Zestaw tańszy! (2026AB)",
    "G80443": "Grzejnik Konwektor - Taniej przy 2 szt! (2026AB)",
    "G10868": "Regał Magazynowy - Hit Stycznia (Gazetka)",
    "G80535": "Wentylator kominkowy - Hit Stycznia (Gazetka)"
}

# CROSS-SELLING (INTELIGENTNE PODPOWIADANIE)
# System podpowiada TYLKO to, co masz w gazetkach
SUGESTIE_CROSS = {
    # Piły -> Tarcze (Styczeń)
    "prowadnic": "Tarcza listkowa (G78531) - Hit Stycznia",
    "łańcuch": "Tarcza listkowa (G78531) - Hit Stycznia",
    
    # Kominiarka (Kominiarska AB)
    "szczotk": "Kula + Lina (G667..) - Zbuduj zestaw do 200 zł",
    "kula": "Lina kominiarska - Do kompletu",
    
    # BHP (Rękawice/Kalosze)
    "rękawic": "Kalosze / Gumofilce - Dobij do 250 zł (Wieszak)",
    "kalosz": "Rękawice zimowe (G735..) - Dobij do 250 zł",
    
    # Budowlanka -> Miary (Styczeń)
    "poziomic": "Miara zwijana (G01461) - Hit Stycznia",
    
    # Grzanie (2026AB)
    "nagrzewnic": "Druga sztuka (Rabat Wielosztuka)",
    "grzejnik": "Druga sztuka (Rabat Wielosztuka)"
}

# DOMYŚLNY PRODUKT "DO KASY" (Gdy nic innego nie pasuje)
DOMYSLNY_PRODUKT = "Nożyk do tapet (G29026) - Hit Cenowy Stycznia"

# ==========================================
# 2. SILNIK LOGICZNY (BACKEND)
# ==========================================

if 'history' not in st.session_state:
    st.session_state['history'] = []

def clean_text(text):
    return text.replace('\xa0', ' ') if text else ""

def extract_client_data_solex(text):
    """
    ALGORYTM ANTY-GEKO:
    Specjalnie pod faktury SolexB2B.
    Ignoruje sekcję Sprzedawca. Szuka Nabywcy.
    """
    lines = text.splitlines()
    client_name = "Nie wykryto klienta"
    client_nip = ""
    
    # 1. SZUKANIE NIPU KLIENTA (Musi być inny niż Twój 7722420459)
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":
            client_nip = nip
            break
            
    # 2. SZUKANIE NAZWY FIRMY
    # Szukamy słowa "Nabywca" i bierzemy linię pod nim, ale filtrujemy śmieci
    found_nabywca = False
    for i, line in enumerate(lines):
        if "Nabywca" in line:
            # Skanujemy 5 linii w dół w poszukiwaniu nazwy
            for offset in range(1, 6): 
                if i + offset >= len(lines): break
                candidate = lines[i + offset].strip()
                
                # FILTRY ODRZUCAJĄCE (To jest klucz do sukcesu)
                if len(candidate) < 3: continue # Za krótkie
                if "NIP" in candidate: continue # To linia z NIPem
                if re.search(r'\d{10}', candidate.replace('-','')): continue # To sam NIP
                if any(x.upper() in candidate.upper() for x in MOJE_DANE): continue # To dane GEKO
                
                # Jeśli przeszło filtry, to jest Klient (np. AGROTECH)
                client_name = candidate
                found_nabywca = True
                break
        if found_nabywca: break

    # FALLBACK (Gdyby układ był inny)
    if client_name == "Nie wykryto klienta":
        for line in lines:
            if "Nabywca" in line: continue
            # Szukamy linii długiej, bez GEKO, bez Sprzedawca, bez cyfr (adresu)
            if len(line) > 5 and "GEKO" not in line.upper() and "SPRZEDAWCA" not in line.upper() and not re.search(r'\d', line):
                 client_name = line.strip()
                 break
                 
    return client_name, client_nip

def extract_amount_and_codes(text):
    # Wyciąganie kwoty
    try:
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = []
        for a in amounts:
            try:
                # Zamiana 1 234,56 na 1234.56
                val = float(a.replace(' ', '').replace(',', '.').replace('\xa0', ''))
                clean_amounts.append(val)
            except: pass
        netto = max(clean_amounts) if clean_amounts else 0.0
    except: netto = 0.0
        
    # Wyciąganie kodów produktów (Gxxxxx) do analizy wielosztuk
    codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches: codes.add(m)
    return netto, codes

def analyze_promotion(text, amount):
    text_lower = text.lower()
    best = None
    min_gap = 99999.0
    dedyk_active = False
    
    # 1. Promocje Dedykowane (Mają słowa kluczowe)
    sorted_promos = sorted(PROMOS, key=lambda x: x[1])
    for keywords, thresh, reward, name in sorted_promos:
        if keywords and any(k in text_lower for k in keywords):
            gap = thresh - amount
            if gap > 0 and gap < min_gap:
                min_gap = gap
                best = (name, thresh, reward)
                dedyk_active = True
            elif gap <= 0 and gap > -1000:
                continue # Jeśli ta zdobyta, szukamy wyższej

    # 2. Promocje Ogólne (Jeśli nie walczymy o dedykowaną)
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
    
    # Sprawdź Wielosztuki po kodach
    for c, msg in WIELOSZTUKI.items():
        if c in codes: sug.append(f"📦 **{c}:** {msg}")
        
    # Sprawdź Cross-Selling po słowach
    for k, v in SUGESTIE_CROSS.items():
        if k in text_lower: sug.append(f"💡 **SUGESTIA:** {v}")
        
    if not sug: sug.append(f"💡 **SUGESTIA:** {DOMYSLNY_PRODUKT}")
    return list(set(sug))

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Raport')
    return output.getvalue()

def send_email_report(data, secrets):
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {data['client']} - Brakuje {data['gap']:.0f} zł"
    
    body = f"""
    RAPORT HANDLOWY GEKO
    ---------------------------------
    KLIENT: {data['client']}
    NIP:    {data['nip']}
    KWOTA:  {data['amount']:.2f} zł
    ---------------------------------
    CEL PROMOCJI: {data['promo_name']} ({data['promo_target']} zł)
    BRAKUJE:      {data['gap']:.2f} zł
    NAGRODA:      {data['promo_reward']}
    ---------------------------------
    HANDLOWIEC POWINIEN ZAPROPONOWAĆ:
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
# 3. INTERFEJS (DASHBOARD)
# ==========================================

# --- PANEL BOCZNY (Raportowanie) ---
with st.sidebar:
    st.header("📂 Raport Dnia")
    if st.session_state['history']:
        df = pd.DataFrame(st.session_state['history'])
        st.dataframe(df[['Klient', 'Netto', 'Brakuje']], hide_index=True)
        
        total_rev = df['Netto'].sum()
        total_gap = df[df['Brakuje'] > 0]['Brakuje'].sum()
        
        st.markdown("---")
        st.metric("Dzisiejszy Obrót", f"{total_rev:.2f} zł")
        st.metric("Potencjał Dosprzedaży", f"{total_gap:.2f} zł", delta="Do wyjęcia")
        
        excel_data = to_excel(df)
        st.download_button(
            label="📥 POBIERZ RAPORT (EXCEL)",
            data=excel_data,
            file_name=f"Raport_GEKO_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Brak przeskanowanych zamówień.")

# --- STRONA GŁÓWNA ---
c1, c2 = st.columns([1, 6])
with c1: st.write("# 🦁")
with c2:
    st.title("System Wsparcia Sprzedaży B2B")
    st.caption("Kampanie Aktywne: Styczeń 2026 | Kominiarska | BHP | Wielosztuki")

# Wskaźniki górne
m1, m2, m3 = st.columns(3)
with m1:
    st.markdown(f'<div class="metric-card"><h3>📄 Sprawdzone</h3><h1>{len(st.session_state["history"])}</h1></div>', unsafe_allow_html=True)
with m2:
    last_val = st.session_state['history'][-1]['Netto'] if st.session_state['history'] else 0.0
    st.markdown(f'<div class="metric-card"><h3>💰 Ostatnie Netto</h3><h1>{last_val:.2f} zł</h1></div>', unsafe_allow_html=True)
with m3:
    st.markdown(f'<div class="metric-card"><h3>🔥 Promocje</h3><h1>4 Aktywne</h1></div>', unsafe_allow_html=True)

st.divider()

uploaded_file = st.file_uploader("WRZUĆ PDF (ZAMÓWIENIE SOLEX)", type="pdf")

if uploaded_file:
    # Parsowanie
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages: raw_text += page.extract_text() or ""
    text = clean_text(raw_text)
    
    # Wyciąganie danych
    d_client, d_nip = extract_client_data_solex(text)
    d_amount, d_codes = extract_amount_and_codes(text)
    
    # --- PANEL EDYCJI DANYCH (KLUCZOWY DLA DYREKTORA) ---
    st.markdown("### 🔍 Weryfikacja Danych")
    st.info(f"System zidentyfikował klienta: **{d_client}**")
    
    col_a, col_b, col_c = st.columns([3, 2, 2])
    with col_a:
        f_client = st.text_input("KLIENT", value=d_client)
    with col_b:
        f_nip = st.text_input("NIP", value=d_nip)
    with col_c:
        f_amount = st.number_input("KWOTA NETTO", value=float(d_amount), step=10.0)

    # --- LOGIKA BIZNESOWA ---
    if f_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, f_amount)
        suggestions = get_suggestions(text, d_codes)
        
        # Zapis do historii (tylko nowe wpisy)
        entry = {'Klient': f_client, 'NIP': f_nip, 'Netto': f_amount, 'Cel': p_name, 'Brakuje': gap if gap > 0 else 0}
        if not st.session_state['history'] or st.session_state['history'][-1] != entry:
             st.session_state['history'].append(entry)

        st.divider()
        
        # WYNIKI W KOLUMNACH
        res_c1, res_c2 = st.columns([3, 2])
        
        with res_c1:
            st.subheader(f"🎯 Cel: {p_name}")
            
            # Pasek postępu
            if p_target > 0:
                prog = min(f_amount / p_target, 1.0)
                st.progress(prog, text=f"Postęp: {int(prog*100)}% ({f_amount:.2f} / {p_target} zł)")
            
            if gap <= 0:
                st.balloons()
                st.success(f"✅ CEL OSIĄGNIĘTY! Nagroda: {p_reward}")
            elif gap > MAX_BRAK_PLN:
                st.info(f"Brakuje {gap:.2f} zł. To powyżej limitu interwencji ({MAX_BRAK_PLN} zł).")
            else:
                st.error(f"⚠️ KLIENT TRACI NAGRODĘ: {p_reward}")
                st.metric("BRAKUJE TYLKO", f"{gap:.2f} zł", delta="- Do domówienia", delta_color="inverse")
                
                # PRZYCISK MAILA (Tylko jak jest strata)
                try:
                    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
                    if st.button("📧 WYŚLIJ RAPORT DO MNIE"):
                        dat = {"client": f_client, "nip": f_nip, "amount": f_amount,
                               "gap": gap, "promo_name": p_name, "promo_target": p_target,
                               "promo_reward": p_reward, "suggestions": suggestions}
                        if send_email_report(dat, SECRETS):
                            st.toast("Wysłano!", icon="✅")
                        else: st.error("Błąd wysyłki")
                except: pass

        with res_c2:
            st.subheader("💡 Asystent Handlowca")
            with st.container(border=True):
                if suggestions:
                    for s in suggestions: st.markdown(s)
                else:
                    st.write("Brak specyficznych sugestii.")
                
                st.markdown("---")
                # GENERATOR SMS
                item_sms = suggestions[0].split(':')[-1].strip().replace('*', '') if suggestions else "Nozyk do tapet"
                sms = f"Dzien dobry! Tu GEKO. Brakuje Panu {gap:.0f} zl do promocji '{p_name}'. Moze dorzucimy: {item_sms}?"
                st.text_area("Gotowy SMS (Kopiuj)", value=sms, height=100)
    else:
        st.warning("⚠️ Wpisz kwotę zamówienia ręcznie.")
