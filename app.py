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
# 0. KONFIGURACJA
# ==========================================
st.set_page_config(page_title="GEKO SALES DIRECTOR", page_icon="🦁", layout="wide")

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
            input { font-size: 18px !important; font-weight: 600 !important; }
            /* Styl dla sekcji SMS */
            .sms-box {
                border: 2px dashed #d63031;
                padding: 20px;
                border-radius: 10px;
                background-color: #fff5f5;
            }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==========================================
# 1. BAZA DANYCH
# ==========================================

# DANE DO FILTROWANIA (GEKO)
MOJE_DANE = ["GEKO", "7722420459", "Sprzedawca", "Kietlin", "Radomsko"]
MAX_BRAK_PLN = 300.00

# PROMOCJE
PROMOS = [
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

# WIELOSZTUKI
WIELOSZTUKI = {
    "G01097": "Wciągarka 3T - Taniej przy 2 szt!",
    "G01362": "Nożyce 30\" - Taniej przy 2 szt!",
    "G01363": "Nożyce 36\" - Taniej przy 2 szt!",
    "G02180": "Podnośnik ATV - Taniej przy 2 szt!",
    "G73866": "Łańcuchy śniegowe - Zestaw tańszy!",
    "G80443": "Grzejnik Konwektor - Taniej przy 2 szt!",
    "G10868": "Regał Magazynowy - Hit Stycznia",
    "G80535": "Wentylator kominkowy - Hit Stycznia"
}

# SUGESTIE CROSS-SELLING (BEZ CHEMII WARSZTATOWEJ)
SUGESTIE_CROSS = {
    "prowadnic": "Tarcza listkowa (G78531) - Hit Stycznia",
    "łańcuch": "Tarcza listkowa (G78531) - Hit Stycznia",
    "szczotk": "Kula + Lina (G667..) - Zbuduj zestaw do 200 zł",
    "kula": "Lina kominiarska - Do kompletu",
    "rękawic": "Kalosze / Gumofilce - Dobij do 250 zł (Wieszak)",
    "kalosz": "Rękawice zimowe (G735..) - Dobij do 250 zł",
    "nagrzewnic": "Druga sztuka (Rabat Wielosztuka)"
}

DOMYSLNY_PRODUKT = "Nożyk do tapet (G29026) - Hit Cenowy Stycznia"

# ==========================================
# 2. SILNIK LOGICZNY
# ==========================================

if 'history' not in st.session_state:
    st.session_state['history'] = []

def clean_text(text):
    return text.replace('\xa0', ' ') if text else ""

def extract_client_data_delivery(text):
    """
    ALGORYTM 'ADRES DOSTAWY':
    Szukamy danych pod sekcją 'Adres dostawy'.
    """
    lines = text.splitlines()
    client_name = "Nie wykryto klienta"
    client_nip = ""
    
    # 1. NIP
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":
            client_nip = nip
            break
            
    # 2. KLIENT (POD ADRESEM DOSTAWY)
    found_header = False
    for i, line in enumerate(lines):
        if "Adres dostawy" in line:
            for offset in range(1, 5):
                if i + offset >= len(lines): break
                candidate = lines[i + offset].strip()
                if len(candidate) < 3: continue
                if "Telefon" in candidate: continue
                if "e-mail" in candidate: continue
                if "PL" == candidate: continue
                if any(x.upper() in candidate.upper() for x in MOJE_DANE): continue
                client_name = candidate
                found_header = True
                break
        if found_header: break
        
    # FALLBACK
    if client_name == "Nie wykryto klienta":
        for i, line in enumerate(lines):
            if "Nabywca" in line:
                 for offset in range(1, 4):
                    if i + offset >= len(lines): break
                    cand = lines[i + offset].strip()
                    if len(cand) > 3 and "NIP" not in cand and "GEKO" not in cand:
                        client_name = cand
                        break
    return client_name, client_nip

def extract_amount_and_codes(text):
    try:
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = []
        for a in amounts:
            try:
                val = float(a.replace(' ', '').replace(',', '.').replace('\xa0', ''))
                clean_amounts.append(val)
            except: pass
        netto = max(clean_amounts) if clean_amounts else 0.0
    except: netto = 0.0
        
    codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches: codes.add(m)
    return netto, codes

def analyze_promotion(text, amount):
    text_lower = text.lower()
    best = None
    min_gap = 99999.0
    dedyk_active = False
    
    sorted_promos = sorted(PROMOS, key=lambda x: x[1])
    for keywords, thresh, reward, name in sorted_promos:
        if keywords and any(k in text_lower for k in keywords):
            gap = thresh - amount
            if gap > 0 and gap < min_gap:
                min_gap = gap
                best = (name, thresh, reward)
                dedyk_active = True
            elif gap <= 0 and gap > -1000:
                continue

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
    for c, msg in WIELOSZTUKI.items():
        if c in codes: sug.append(f"📦 **{c}:** {msg}")
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
    KLIENT: {data['client']}
    KWOTA:  {data['amount']:.2f} zł
    BRAKUJE: {data['gap']:.2f} zł
    CEL: {data['promo_name']}
    NAGRODA: {data['promo_reward']}
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

with st.sidebar:
    st.header("📂 Raport Dnia")
    if st.session_state['history']:
        df = pd.DataFrame(st.session_state['history'])
        st.dataframe(df[['Klient', 'Netto', 'Brakuje']], hide_index=True)
        total_rev = df['Netto'].sum()
        total_gap = df[df['Brakuje'] > 0]['Brakuje'].sum()
        st.markdown("---")
        st.metric("Dzisiejszy Obrót", f"{total_rev:.2f} zł")
        st.metric("Potencjał", f"{total_gap:.2f} zł", delta="Do wyjęcia")
        excel_data = to_excel(df)
        st.download_button("📥 POBIERZ RAPORT (EXCEL)", data=excel_data, file_name=f"Raport_GEKO_{datetime.now().strftime('%Y%m%d')}.xlsx")
    else:
        st.info("Brak danych.")

c1, c2 = st.columns([1, 6])
with c1: st.write("# 🦁")
with c2:
    st.title("System Wsparcia Sprzedaży B2B")
    st.caption("Kampanie: Styczeń 2026 | Wielosztuki | Cross-Selling")

# METRICS
m1, m2, m3 = st.columns(3)
with m1: st.markdown(f'<div class="metric-card"><h3>📄 Faktury</h3><h1>{len(st.session_state["history"])}</h1></div>', unsafe_allow_html=True)
with m2: 
    val = st.session_state['history'][-1]['Netto'] if st.session_state['history'] else 0.0
    st.markdown(f'<div class="metric-card"><h3>💰 Ostatnia</h3><h1>{val:.2f} zł</h1></div>', unsafe_allow_html=True)
with m3: st.markdown(f'<div class="metric-card"><h3>🔥 Promocje</h3><h1>4 Aktywne</h1></div>', unsafe_allow_html=True)

st.divider()

uploaded_file = st.file_uploader("WRZUĆ PDF (ZAMÓWIENIE SOLEX)", type="pdf")

if uploaded_file:
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages: raw_text += page.extract_text() or ""
    text = clean_text(raw_text)
    
    d_client, d_nip = extract_client_data_delivery(text)
    d_amount, d_codes = extract_amount_and_codes(text)
    
    st.markdown("### 🔍 Weryfikacja Danych")
    st.info(f"Klient odczytany z 'Adres dostawy': **{d_client}**")
    
    ca, cb, cc = st.columns([3, 2, 2])
    with ca: f_client = st.text_input("KLIENT", value=d_client)
    with cb: f_nip = st.text_input("NIP", value=d_nip)
    with cc: f_amount = st.number_input("KWOTA NETTO", value=float(d_amount), step=10.0)

    if f_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, f_amount)
        suggestions = get_suggestions(text, d_codes)
        
        entry = {'Klient': f_client, 'NIP': f_nip, 'Netto': f_amount, 'Cel': p_name, 'Brakuje': gap if gap > 0 else 0}
        if not st.session_state['history'] or st.session_state['history'][-1] != entry:
             st.session_state['history'].append(entry)

        st.divider()
        rc1, rc2 = st.columns([3, 2])
        
        with rc1:
            st.subheader(f"🎯 Cel: {p_name}")
            if p_target > 0:
                prog = min(f_amount / p_target, 1.0)
                st.progress(prog, text=f"Realizacja: {int(prog*100)}% ({f_amount:.2f} / {p_target} zł)")
