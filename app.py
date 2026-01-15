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
# 0. KONFIGURACJA WYGLĄDU (PRO)
# ==========================================
st.set_page_config(page_title="GEKO SALES DIRECTOR", page_icon="🦁", layout="wide")

hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .metric-card {
                background-color: #ffffff; border-left: 6px solid #d63031;
                border-radius: 8px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }
            .stButton>button {
                width: 100%; font-weight: bold; border-radius: 8px; height: 55px;
                background-color: #d63031; color: white; border: none; font-size: 18px;
            }
            .promo-box {
                border: 1px solid #ddd; padding: 15px; border-radius: 10px;
                margin-bottom: 10px; background-color: #f9f9f9;
            }
            .promo-success { background-color: #d4edda; border-color: #c3e6cb; }
            .promo-warning { background-color: #fff3cd; border-color: #ffeeba; }
            input { font-size: 18px !important; font-weight: 600 !important; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==========================================
# 1. BAZA DANYCH
# ==========================================
MOJE_DANE = ["GEKO", "7722420459", "Sprzedawca", "Kietlin", "Radomsko"]
MAX_BRAK_PLN = 300.00 # Limit interwencji

# DEFINICJA PROMOCJI (KATEGORIE)
PROMO_RULES = {
    "KOMINIARSKA": {
        "keywords": ["szczotk", "wycior", "kula", "lina", "przepychacz", "zestaw komin", "g667"],
        "thresholds": [(200.00, "T-SHIRT GEKO (0.01 zł)")],
        "name": "🔥 KOMINIARSKA (T-Shirt)"
    },
    "BHP": {
        "keywords": ["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"],
        "thresholds": [
            (500.00, "Rabat 3% + Wieszak"),
            (250.00, "Wieszak G90406 (1 zł)")
        ],
        "name": "🔥 BHP (Rękawice/Buty)"
    },
    "OGOLNA": {
        "keywords": [], # Pusta lista oznacza "wszystko"
        "thresholds": [
            (3000.00, "Nagroda PREMIUM"),
            (1000.00, "Bluza Polarowa (1 zł)")
        ],
        "name": "💰 OGÓLNA (Polar/Premium)"
    }
}

# WIELOSZTUKI (2026AB)
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
    "szczotk": "Kula + Lina (G667..) - Zbuduj zestaw",
    "kula": "Lina kominiarska - Do kompletu",
    "rękawic": "Kalosze / Gumofilce - Dobij do 250 zł",
    "nagrzewnic": "Druga sztuka (Rabat Wielosztuka)"
}

DOMYSLNY_PRODUKT = "Nożyk do tapet (G29026) - Hit Cenowy Stycznia"

# ==========================================
# 2. SILNIK LOGICZNY
# ==========================================
if 'history' not in st.session_state: st.session_state['history'] = []

def clean_text(text):
    return text.replace('\xa0', ' ') if text else ""

def extract_client_data(text):
    lines = text.splitlines()
    client_name = "Nie wykryto klienta"
    client_nip = ""
    
    # NIP
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":
            client_nip = nip
            break
    
    # KLIENT (Adres dostawy -> Nabywca -> Fallback)
    found = False
    # 1. Adres dostawy
    for i, line in enumerate(lines):
        if "Adres dostawy" in line:
            for offset in range(1, 5):
                if i+offset >= len(lines): break
                cand = lines[i+offset].strip()
                if len(cand)>3 and "Telefon" not in cand and "PL" != cand and not any(x.upper() in cand.upper() for x in MOJE_DANE):
                    client_name = cand
                    found = True
                    break
        if found: break
        
    # 2. Nabywca (jeśli brak adresu dostawy)
    if not found:
        for i, line in enumerate(lines):
            if "Nabywca" in line:
                 for offset in range(1, 4):
                    if i+offset >= len(lines): break
                    cand = lines[i+offset].strip()
                    if len(cand)>3 and "NIP" not in cand and "GEKO" not in cand:
                        client_name = cand
                        break
    return client_name, client_nip

def extract_items_and_codes(text):
    """
    Zwraca:
    1. Całkowitą kwotę netto.
    2. Słownik kategorii z kwotami { 'KOMINIARSKA': 150.0, 'BHP': 0.0 ... }
    3. Zbiór kodów produktów.
    """
    # Prosta heurystyka kwotowa (suma największa to netto całego zam)
    try:
        amounts = re.findall(r"(\d+[\s\.]?\d+[\.,]\d{2})", text)
        clean_amounts = []
        for a in amounts:
            try:
                val = float(a.replace(' ', '').replace(',', '.').replace('\xa0', ''))
                clean_amounts.append(val)
            except: pass
        total_netto = max(clean_amounts) if clean_amounts else 0.0
    except: total_netto = 0.0

    # Analiza linii pod kątem kategorii (szacunkowa)
    # W PDF-ach handlowych trudno przypisać kwotę do linii bez OCR tabeli,
    # więc używamy uproszczenia: 
    # Dla Kominiarskiej i BHP sprawdzamy czy są słowa kluczowe.
    # Jeśli są, zakładamy że klient "jest w grze" i liczymy gap od TOTAL NETTO,
    # ALE w idealnym świecie powinniśmy sumować pozycje.
    # Tutaj dla bezpieczeństwa (żeby nie pominąć) przyjmiemy strategię:
    # Jeśli znaleziono towary z kategorii, wyświetlamy pasek tej kategorii w oparciu o TOTAL,
    # ale z ostrzeżeniem, że to suma całego zamówienia.
    # (Dla pełnej precyzji potrzebny byłby parser tabelaryczny, który jest ryzykowny na różnych formatach).
    
    # Wyciągamy kody
    codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches: codes.add(m)
    
    return total_netto, codes

def analyze_all_promotions(text, total_netto):
    """
    Sprawdza WSZYSTKIE promocje równolegle.
    Zwraca listę aktywnych/potencjalnych promocji.
    """
    text_lower = text.lower()
    results = []
    
    for key, rule in PROMO_RULES.items():
        # Sprawdź czy zamówienie zawiera produkty z tej kategorii
        is_relevant = False
        if not rule['keywords']: # OGÓLNA
            is_relevant = True
        else:
            if any(k in text_lower for k in rule['keywords']):
                is_relevant = True
        
        if is_relevant:
            # Szukamy najbliższego niespełnionego progu
            # Sortujemy progi malejąco, żeby znaleźć najwyższy zdobyty lub najbliższy do zdobycia
            thresholds = sorted(rule['thresholds'], key=lambda x: x[0])
            
            best_status = None
            
            for thresh, reward in thresholds:
                gap = thresh - total_netto
                
                # Jeśli próg zdobyty
                if gap <= 0:
                    best_status = {
                        "type": key,
                        "name": rule['name'],
                        "target": thresh,
                        "reward": reward,
                        "gap": 0,
                        "status": "DONE"
                    }
                    # Idziemy dalej pętlą, bo może zdobył też wyższy próg (nadpisze best_status)
                
                # Jeśli brakuje do progu
                elif gap > 0:
                    # Jeśli to pierwszy brakujący próg (najniższy niezdobyty)
                    if best_status is None or best_status['status'] == "DONE":
                         best_status = {
                            "type": key,
                            "name": rule['name'],
                            "target": thresh,
                            "reward": reward,
                            "gap": gap,
                            "status": "PENDING"
                        }
                    break # Przerywamy, bo celujemy w ten najbliższy
            
            if best_status:
                results.append(best_status)
                
    return results

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

def send_email_report(data, active_promos, secrets):
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 RAPORT: {data['client']} - {data['amount']:.2f} zł"
    
    promo_txt = ""
    for p in active_promos:
        if p['gap'] > 0:
            promo_txt += f"- {p['name']}: Brakuje {p['gap']:.2f} zł (Nagroda: {p['reward']})\n"
        else:
            promo_txt += f"- {p['name']}: ZDOBYTE! (Nagroda: {p['reward']})\n"

    body = f"""
    RAPORT HANDLOWY GEKO
    ====================
    KLIENT: {data['client']}
    NIP:    {data['nip']}
    KWOTA:  {data['amount']:.2f} zł
    ====================
    STATUS PROMOCJI:
    {promo_txt}
    ====================
    SUGESTIE:
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
# 3. INTERFEJS
# ==========================================

# SIDEBAR
with st.sidebar:
    st.header("📂 Raport Dnia")
    if st.session_state['history']:
        df = pd.DataFrame(st.session_state['history'])
        st.dataframe(df[['Klient', 'Netto']], hide_index=True)
        st.metric("Dzisiejszy Obrót", f"{df['Netto'].sum():.2f} zł")
        st.download_button("📥 POBIERZ EXCEL", data=to_excel(df), file_name=f"Raport_GEKO.xlsx")

# MAIN
c1, c2 = st.columns([1, 6])
with c1: st.write("# 🦁")
with c2:
    st.title("System Wsparcia Sprzedaży B2B")
    st.caption("Analiza Wielowątkowa: Kominiarska | BHP | Ogólna 1000+")

st.divider()

uploaded_file = st.file_uploader("WRZUĆ PDF (ZAMÓWIENIE SOLEX)", type="pdf")

if uploaded_file:
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages: raw_text += page.extract_text() or ""
    text = clean_text(raw_text)
    
    d_client, d_nip = extract_client_data(text)
    d_amount, d_codes = extract_items_and_codes(text)
    
    st.info(f"Klient: **{d_client}**")
    
    ca, cb, cc = st.columns([3, 2, 2])
    with ca: f_client = st.text_input("KLIENT", value=d_client)
    with cb: f_nip = st.text_input("NIP", value=d_nip)
    with cc: f_amount = st.number_input("KWOTA NETTO", value=float(d_amount), step=10.0)

    if f_amount > 0:
        # ANALIZA WSZYSTKICH PROMOCJI
        active_promos = analyze_all_promotions(text, f_amount)
        suggestions = get_suggestions(text, d_codes)
        
        # Zapis historii
        entry = {'Klient': f_client, 'Netto': f_amount, 'Data': datetime.now().strftime("%H:%M")}
        if not st.session_state['history'] or st.session_state['history'][-1]['Netto'] != f_amount:
             st.session_state['history'].append(entry)

        st.divider()
        
        # WIDOK PROMOCJI
        rc1, rc2 = st.columns([3, 2])
        
        with rc1:
            st.subheader("🎯 Status Promocji")
            if not active_promos:
                st.warning("Brak aktywnych promocji dla tego asortymentu.")
            
            main_gap_sms = 0 # Do SMS-a weźmiemy najważniejszy brak
            
            for p in active_promos:
                # Stylizacja karty w zależności od statusu
                css_class = "promo-success" if p['status'] == "DONE" else "promo-warning"
                icon = "✅" if p['status'] == "DONE" else "⚠️"
                
                with st.container():
                    st.markdown(f"""
                    <div class="promo-box {css_class}">
                        <h4>{icon} {p['name']}</h4>
                        <p>Cel: {p['target']} zł | Nagroda: <strong>{p['reward']}</strong></p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if p['status'] == "PENDING":
                        # Jeśli brakuje mniej niż limit i więcej niż 0
                        if 0 < p['gap'] <= MAX_BRAK_PLN:
                             st.error(f"BRAKUJE TYLKO: {p['gap']:.2f} ZŁ")
                             main_gap_sms = p['gap'] # Zapamiętaj do SMS
                        elif p['gap'] > MAX_BRAK_PLN:
                             st.info(f"Brakuje {p['gap']:.2f} zł (Daleko do celu)")
                        
                        prog = min(f_amount / p['target'], 1.0)
                        st.progress(prog)
                    else:
                        st.success("ZDOBYTE!")

            # Przycisk Raportu
            try:
                SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
                if st.button("📧 WYŚLIJ RAPORT MAILEM"):
                    dat = {"client": f_client, "nip": f_nip, "amount": f_amount, "suggestions": suggestions}
                    if send_email_report(dat, active_promos, SECRETS): st.toast("Wysłano!", icon="✅")
                    else: st.error("Błąd wysyłki")
            except: pass

        with rc2:
            st.subheader("💡 Sugestie")
            with st.container(border=True):
                for s in suggestions: st.markdown(s)
            
            # SMS GENERATOR
            st.markdown("---")
            st.subheader("📲 SMS")
            
            # Wybierz gap do SMS (jeśli jest jakiś aktywny "blisko", weź go, jeśli nie to ogólny)
            gap_txt = f"{main_gap_sms:.0f}" if main_gap_sms > 0 else "trochę"
            item_sms = suggestions[0].split(':')[-1].strip().replace('*', '') if suggestions else "Nozyk do tapet"
            
            t1, t2 = st.tabs(["SZYBKI", "OFICJALNY"])
            with t1:
                st.text_area("Do stałego klienta:", 
                    value=f"Cześć! W zamówieniu brakuje Ci {gap_txt} zł do nagrody. Dorzucamy {item_sms}? Daj znać.", height=100)
            with t2:
                st.text_area("Oficjalny:", 
                    value=f"Dzień dobry. Do progu promocyjnego brakuje {gap_txt} zł. Proponuję domówić: {item_sms}. Pozdrawiam, GEKO.", height=100)

    else:
        st.warning("⚠️ Wpisz kwotę ręcznie.")
