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
# 0. KONFIGURACJA WYGLĄDU (BRANDING GEKO)
# ==========================================
st.set_page_config(page_title="GEKO SALES DIRECTOR", page_icon="🦁", layout="wide")

# CSS: Kolory GEKO (Czerwony, Czarny, Biały) i profesjonalny styl
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            
            /* Karty statystyk */
            .metric-card {
                background-color: #ffffff;
                border-left: 6px solid #d63031; /* Czerwony GEKO */
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }
            
            /* Przyciski */
            .stButton>button {
                width: 100%;
                font-weight: bold;
                border-radius: 8px;
                height: 55px;
                font-size: 18px;
                background-color: #d63031;
                color: white;
                border: none;
            }
            .stButton>button:hover {
                background-color: #b71c1c;
                color: white;
            }
            
            /* Inputy */
            input { font-size: 18px !important; font-weight: 600 !important; }
            
            /* Zakładki */
            .stTabs [data-baseweb="tab-list"] { gap: 24px; }
            .stTabs [data-baseweb="tab"] {
                height: 50px;
                white-space: pre-wrap;
                background-color: #f1f1f1;
                border-radius: 4px 4px 0 0;
                gap: 1px;
                padding-top: 10px;
                padding-bottom: 10px;
            }
            .stTabs [aria-selected="true"] {
                background-color: #ffffff;
                border-bottom: 2px solid #d63031;
                color: #d63031;
                font-weight: bold;
            }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==========================================
# 1. BAZA DANYCH
# ==========================================
MOJE_DANE = ["GEKO", "7722420459", "Sprzedawca", "Kietlin", "Radomsko"]
MAX_BRAK_PLN = 300.00

PROMOS = [
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

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
    lines = text.splitlines()
    client_name = "Nie wykryto klienta"
    client_nip = ""
    
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":
            client_nip = nip
            break
            
    found_header = False
    for i, line in enumerate(lines):
        if "Adres dostawy" in line:
            for offset in range(1, 5):
                if i + offset >= len(lines): break
                candidate = lines[i + offset].strip()
                if len(candidate) < 3 or "Telefon" in candidate or "e-mail" in candidate or "PL" == candidate: continue
                if any(x.upper() in candidate.upper() for x in MOJE_DANE): continue
                client_name = candidate
                found_header = True
                break
        if found_header: break
        
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
    SUGESTIE: {chr(10).join(data['suggestions'])}
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
# 3. INTERFEJS
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
        st.info("Oczekiwanie na dane...")

c1, c2 = st.columns([1, 6])
with c1: st.markdown("# 🦁")
with c2:
    st.title("System Wsparcia Sprzedaży B2B")
    st.caption("v13.0 Ultimate | Solex Integration | Knowledge Base")

# ----------------- GŁÓWNE ZAKŁADKI -----------------
main_tab1, main_tab2 = st.tabs(["🚀 ANALIZA ZAMÓWIENIA", "📚 CENNIKI I ZASADY"])

# --- ZAKŁADKA 1: AUTOMAT ---
with main_tab1:
    m1, m2, m3 = st.columns(3)
    with m1: st.markdown(f'<div class="metric-card"><h3>📄 Faktury</h3><h1>{len(st.session_state["history"])}</h1></div>', unsafe_allow_html=True)
    with m2: 
        val = st.session_state['history'][-1]['Netto'] if st.session_state['history'] else 0.0
        st.markdown(f'<div class="metric-card"><h3>💰 Ostatnia</h3><h1>{val:.2f} zł</h1></div>', unsafe_allow_html=True)
    with m3: st.markdown(f'<div class="metric-card"><h3>🔥 Kampanie</h3><h1>4 Aktywne</h1></div>', unsafe_allow_html=True)

    st.divider()

    uploaded_file = st.file_uploader("WRZUĆ PDF (ZAMÓWIENIE SOLEX)", type="pdf")

    if uploaded_file:
        raw_text = ""
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages: raw_text += page.extract_text() or ""
        text = clean_text(raw_text)
        
        d_client, d_nip = extract_client_data_delivery(text)
        d_amount, d_codes = extract_amount_and_codes(text)
        
        st.info(f"Klient zidentyfikowany: **{d_client}**")
        
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
                
                if gap <= 0:
                    st.balloons()
                    st.success(f"✅ ZDOBYTE: {p_reward}")
                elif gap > MAX_BRAK_PLN:
                    st.info(f"Brakuje {gap:.2f} zł (Limit interwencji).")
                else:
                    st.error(f"⚠️ BRAKUJE: {gap:.2f} ZŁ")
                    st.metric("Nagroda", p_reward)
                    
                    try:
                        SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
                        if st.button("📧 WYŚLIJ RAPORT MAILEM"):
                            dat = {"client": f_client, "nip": f_nip, "amount": f_amount, "gap": gap, "promo_name": p_name, "promo_target": p_target, "promo_reward": p_reward, "suggestions": suggestions}
                            if send_email_report(dat, SECRETS): st.toast("Wysłano!", icon="✅")
                            else: st.error("Błąd wysyłki")
                    except: pass

            with rc2:
                st.subheader("💡 Asystent")
                with st.container(border=True):
                    for s in suggestions: st.markdown(s)
            
            st.markdown("---")
            st.subheader("🗨️ CENTRUM KOMUNIKACJI")
            item_sms = suggestions[0].split(':')[-1].strip().replace('*', '') if suggestions else "Nozyk do tapet"
            
            t1, t2, t3 = st.tabs(["🚀 SZYBKI", "👔 OFICJALNY", "📦 PRODUKTOWY"])
            with t1: st.text_area("SMS Szybki", value=f"Cześć! Brakuje Ci tylko {gap:.0f} zł do darmowej bluzy/gratisu. Dorzucamy {item_sms}? Daj znać.", height=100)
            with t2: st.text_area("SMS Oficjalny", value=f"Dzień dobry, przesyłam analizę. Do progu '{p_name}' brakuje {gap:.2f} zł. Sugeruję domówienie: {item_sms}. Pozdrawiam.", height=100)
            with t3: st.text_area("SMS Produktowy", value=f"Dzień dobry. Mamy hit cenowy: {item_sms}. Brakuje Panu {gap:.0f} zł do gratisu, więc idealnie pasuje. Dopisujemy?", height=100)

        else:
            st.warning("⚠️ Wpisz kwotę ręcznie.")

# --- ZAKŁADKA 2: BAZA WIEDZY ---
with main_tab2:
    st.header("📚 Baza Wiedzy Handlowca")
    st.markdown("Szczegóły akcji promocyjnych, żebyś nie musiał szukać w PDF-ach.")
    
    with st.expander("📦 WIELOSZTUKI (2026AB) - Ceny spadają przy ilości!"):
        st.markdown("""
        | Kod | Nazwa | Cena Detal | Cena przy 2 szt |
        |---|---|---|---|
        | **G01097** | Wciągarka 3T | 185 zł | **173,16 zł** |
        | **G01362** | Nożyce do drutu 30" | 45 zł | **40,79 zł** |
        | **G01363** | Nożyce do drutu 36" | 52 zł | **47,93 zł** |
        | **G02180** | Podnośnik ATV | 280 zł | **268,64 zł** |
        | **G73866** | Łańcuchy śniegowe | 95 zł | **90,64 zł** |
        | **G80443** | Grzejnik Konwektor | 82 zł | **76,82 zł** |
        """)
    
    with st.expander("📅 GAZETKA STYCZEŃ - Hity Cenowe"):
        st.markdown("""
        - **Regał magazynowy (G10868):** Promocja **82,99 zł** (z 174 zł!)
        - **Tarcza listkowa (G78531):** **6,60 zł**
        - **Nożyk do tapet (G29026):** **1,72 zł** (Idealny zapychacz)
        - **Miara zwijana 3m (G01461):** **7,92 zł**
        - **Wentylator kominkowy (G80535):** **61,09 zł**
        """)
        
    with st.expander("🧤 BHP (Rękawice & Kalosze) - Zasady"):
        st.info("**ZASADA:** Sumujemy Rękawice + Kalosze.")
        st.markdown("""
        - **Próg 250 zł:** Wieszak G90406 za 1 zł
        - **Próg 500 zł:** Rabat 3% + Wieszak
        - **Produkty:** Rękawice zimowe (Green, Orange, Blue), Kalosze EVA/PCV.
        """)
        
    with st.expander("🔥 KOMINIARSKA - Zasady"):
        st.info("**ZASADA:** Produkty kominiarskie (szczotki, kule, liny).")
        st.markdown("""
        - **Próg 200 zł:** T-SHIRT GEKO za 1 grosz.
        - **Produkty:** Kody G667xx (Szczotki, Wyciory, Kule, Liny, Zestawy).
        """)
