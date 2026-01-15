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
# 0. KONFIGURACJA WYGLĄDU (MUSI BYĆ NA GÓRZE)
# ==========================================
st.set_page_config(page_title="GEKO SALES DIRECTOR", page_icon="🦁", layout="wide")

# Ukrywanie stopki Streamlit i menu (Wygląd PRO - "Aplikacja Natywna")
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .metric-card {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 10px;
                padding: 15px;
                text-align: center;
                box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
            }
            .stButton>button {
                width: 100%;
                font-weight: bold;
                border-radius: 8px;
                height: 50px;
            }
            /* Powiększenie inputów na mobilu */
            input { font-size: 16px !important; }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==========================================
# 1. BAZA WIEDZY (PROMOCJE I REGUŁY)
# ==========================================

# Dane do ignorowania (GEKO) - żeby nie pomylić sprzedawcy z nabywcą
MOJE_DANE = ["GEKO", "7722420459", "Sprzedawca", "Kietlin", "Radomsko", "Sp.k.", "Spółka"]
MAX_BRAK_PLN = 300.00  # Limit interwencji

# Baza Promocji Progowych
PROMOS = [
    # KOMINIARSKA AB
    # Wykrywa: szczotki, kule, liny (kody G667..)
    (["szczotk", "wycior", "kula", "lina", "przepychacz", "zestaw komin", "g667"], 200.00, "T-SHIRT GEKO (0.01 zł)", "🔥 KOMINIARSKA"),
    
    # BHP (RĘKAWICE + KALOSZE)
    # Łączy obie gazetki w jeden cel. Wykrywa: rękawice, kalosze, gumofilce.
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 500.00, "Rabat 3% + Wieszak", "🔥 BHP (DUŻA)"),
    (["rękawic", "kalosz", "gumofilc", "obuwie", "g735", "g750", "g905"], 250.00, "Wieszak G90406 (1 zł)", "🔥 BHP (MAŁA)"),
    
    # OGÓLNE (GAZETKA STYCZEŃ)
    ([], 1000.00, "Bluza Polarowa (1 zł)", "Ogólna (Polar)"),
    ([], 3000.00, "Nagroda PREMIUM", "Ogólna (VIP)")
]

# Wielosztuki (2026AB) - Kody produktów
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

# Cross-Selling (Sugestie "Co dorzucić")
SUGESTIE_CROSS = {
    "prowadnic": "Ostrzałka elektr. (G81207) - Serwis pił",
    "siekier": "Ostrzałka 2w1 (T02-009) - Tani dodatek",
    "szczotk": "Kula + Lina (Kominiarska) - Zbuduj zestaw",
    "kula": "Lina kominiarska - Do kompletu",
    "rękawic": "Kalosze / Gumofilce (BHP) - Dobij do 250 zł",
    "nagrzewnic": "Druga sztuka (Wielosztuka)",
    "wciągark": "Zblocze / Uchwyt"
}

# ==========================================
# 2. SILNIK LOGICZNY (BACKEND)
# ==========================================

# Inicjalizacja sesji (pamięć podręczna na historię dnia)
if 'history' not in st.session_state:
    st.session_state['history'] = []

def clean_text(text):
    return text.replace('\xa0', ' ') if text else ""

def extract_client_data_titan(text):
    """
    Algorytm TYTAN: Ignoruje dane GEKO. Szuka sekcji 'Nabywca'.
    Zaprojektowany pod faktury SolexB2B.
    """
    lines = text.splitlines()
    client_name = "Nie wykryto klienta"
    client_nip = ""
    
    # 1. Szukanie NIP (Każdy 10-cyfrowy ciąg, który NIE jest GEKO)
    all_nips = re.findall(r'\d{10}', text.replace('-', ''))
    for nip in all_nips:
        if nip != "7722420459":  # Twój NIP
            client_nip = nip
            break
            
    # 2. Szukanie Nazwy Firmy (Logika pozycyjna i słownikowa)
    found_nabywca = False
    
    # Przejście 1: Szukanie po słowie kluczowym "Nabywca"
    for i, line in enumerate(lines):
        if "Nabywca" in line:
            # Sprawdzamy 5 kolejnych linii
            for offset in range(1, 6): 
                if i + offset >= len(lines): break
                candidate = lines[i + offset].strip()
                
                # Filtry odrzucające śmieci
                if len(candidate) < 3: continue
                if "NIP" in candidate: continue
                if re.search(r'\d{10}', candidate.replace('-','')): continue # To linia z NIPem
                if any(x.upper() in candidate.upper() for x in MOJE_DANE): continue # To dane GEKO
                
                # Jeśli przetrwał filtry -> To Klient!
                client_name = candidate
                found_nabywca = True
                break
        if found_nabywca: break

    # Przejście 2 (Fallback): Jeśli "Nabywca" zawiódł, szukamy "na siłę"
    if client_name == "Nie wykryto klienta":
        for line in lines:
            if "Nabywca" in line: continue
            # Jeśli linia jest długa, nie ma GEKO, nie ma cyfr (adresu) -> Może to firma?
            if len(line) > 5 and "GEKO" not in line.upper() and "SPRZEDAWCA" not in line.upper() and not re.search(r'\d', line):
                 client_name = line.strip()
                 break
                 
    return client_name, client_nip

def extract_amount_and_codes(text):
    """Wyciąga kwotę netto i kody produktów (Gxxxxx)"""
    # Kwota
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
        
    # Kody
    codes = set()
    matches = re.findall(r'(G\d{5})', text.upper())
    for m in matches: codes.add(m)
    return netto, codes

def analyze_promotion(text, amount):
    """Wybiera najlepszą promocję (Priorytet: Dedykowana -> Ogólna)"""
    text_lower = text.lower()
    best = None
    min_gap = 99999.0
    dedyk_active = False
    
    # 1. Sprawdź Dedykowane (Kominiarska, BHP)
    sorted_promos = sorted(PROMOS, key=lambda x: x[1]) # Sortuj od najniższego progu
    for keywords, thresh, reward, name in sorted_promos:
        if keywords and any(k in text_lower for k in keywords):
            gap = thresh - amount
            if gap > 0 and gap < min_gap:
                min_gap = gap
                best = (name, thresh, reward)
                dedyk_active = True
            elif gap <= 0 and gap > -1000: # Jeśli spełniona, szukaj wyższej w tej kategorii
                continue

    # 2. Sprawdź Ogólne (tylko jeśli nie walczymy o dedykowaną)
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
    """Generuje listę podpowiedzi (Wielosztuki + Cross-Sell)"""
    sug = []
    text_lower = text.lower()
    
    # Sprawdź Wielosztuki po kodach
    for c, msg in WIELOSZTUKI.items():
        if c in codes: sug.append(f"📦 **{c}:** {msg}")
        
    # Sprawdź Cross-Selling po słowach
    for k, v in SUGESTIE_CROSS.items():
        if k in text_lower: sug.append(f"💡 **SUGESTIA:** {v}")
        
    if not sug: sug.append("💡 Sugestia: Chemia warsztatowa (uniwersalna)")
    return list(set(sug))

def to_excel(df):
    """Generuje plik Excel do pobrania"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Raport')
    return output.getvalue()

def send_email_report(data, secrets):
    """Wysyła raport na maila"""
    if not secrets: return False
    msg = MIMEMultipart()
    msg['From'] = secrets["EMAIL_NADAWCY"]
    msg['To'] = secrets["EMAIL_ODBIORCY"]
    msg['Subject'] = f"🔔 {data['client']} - Brakuje {data['gap']:.0f} zł"
    
    body = f"""
    RAPORT HANDLOWY - GEKO
    ---------------------------------
    KLIENT: {data['client']}
    NIP:    {data['nip']}
    KWOTA:  {data['amount']:.2f} zł
    ---------------------------------
    CEL:     {data['promo_name']} ({data['promo_target']} zł)
    BRAKUJE: {data['gap']:.2f} zł
    NAGRODA: {data['promo_reward']}
    ---------------------------------
    SUGESTIE DLA HANDLOWCA:
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
# 3. INTERFEJS UŻYTKOWNIKA (DASHBOARD)
# ==========================================

# --- PANEL BOCZNY (Sidebar) ---
with st.sidebar:
    st.header("📂 Raport Dnia")
    if st.session_state['history']:
        df = pd.DataFrame(st.session_state['history'])
        st.dataframe(df[['Klient', 'Netto', 'Brakuje']], hide_index=True)
        
        total_rev = df['Netto'].sum()
        total_gap = df[df['Brakuje'] > 0]['Brakuje'].sum()
        
        st.markdown("---")
        st.metric("Dzisiejszy Obrót", f"{total_rev:.2f} zł")
        st.metric("Potencjał Dosprzedaży", f"{total_gap:.2f} zł", delta="Możliwy Zysk")
        
        # Przycisk Eksportu
        excel_data = to_excel(df)
        st.download_button(
            label="📥 POBIERZ RAPORT (EXCEL)",
            data=excel_data,
            file_name=f"Raport_GEKO_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Zeskanuj pierwsze zamówienie, aby zbudować raport.")

# --- STRONA GŁÓWNA ---
c_logo, c_title = st.columns([1, 6])
with c_logo:
    st.markdown("# 🦁") # Tu w przyszłości logo GEKO
with c_title:
    st.title("System Wsparcia Sprzedaży B2B")
    st.caption("Wspierane kampanie: Styczeń 2026 | Kominiarska | BHP | Wielosztuki")

st.divider()

# SEKCJ A: UPLOAD
uploaded_file = st.file_uploader("WRZUĆ PDF (ZAMÓWIENIE SOLEX)", type="pdf")

if uploaded_file:
    # 1. Przetwarzanie
    raw_text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages: raw_text += page.extract_text() or ""
    text = clean_text(raw_text)
    
    # 2. Wyciąganie danych (Algorytm Tytan)
    d_client, d_nip = extract_client_data_titan(text)
    d_amount, d_codes = extract_amount_and_codes(text)
    
    # 3. Formularz Weryfikacji (Edytowalny)
    st.markdown("### 🔍 Weryfikacja Danych")
    col_a, col_b, col_c = st.columns([3, 2, 2])
    with col_a:
        f_client = st.text_input("KLIENT", value=d_client)
    with col_b:
        f_nip = st.text_input("NIP", value=d_nip)
    with col_c:
        f_amount = st.number_input("KWOTA NETTO", value=float(d_amount), step=10.0)

    # 4. Logika Biznesowa
    if f_amount > 0:
        (p_name, p_target, p_reward), gap = analyze_promotion(text, f_amount)
        suggestions = get_suggestions(text, d_codes)
        
        # Aktualizacja historii
        entry = {'Klient': f_client, 'NIP': f_nip, 'Netto': f_amount, 'Cel': p_name, 'Brakuje': gap if gap > 0 else 0}
        # Dodajemy tylko jeśli to nowy wpis
        if not st.session_state['history'] or st.session_state['history'][-1]['Klient'] != f_client or st.session_state['history'][-1]['Netto'] != f_amount:
             st.session_state['history'].append(entry)

        st.divider()
        
        # WYNIKI (Dwie kolumny)
        res_c1, res_c2 = st.columns([3, 2])
        
        with res_c1:
            st.subheader(f"🎯 Cel: {p_name}")
            
            # Pasek postępu
            if p_target > 0:
                prog = min(f_amount / p_target, 1.0)
                st.progress(prog, text=f"Postęp: {int(prog*100)}% ({f_amount:.2f} / {p_target} zł)")
            
            # Status
            if gap <= 0:
                st.balloons()
                st.success(f"✅ CEL ZREALIZOWANY! Nagroda: {p_reward}")
            elif gap > MAX_BRAK_PLN:
                st.info(f"🔵 Brakuje {gap:.2f} zł. Powyżej limitu interwencji.")
            else:
                st.error(f"🔥 ALARM! KLIENT TRACI NAGRODĘ: {p_reward}")
                st.metric("BRAKUJE TYLKO", f"{gap:.2f} zł", delta="- Do domówienia", delta_color="inverse")
                
                # Przycisk maila (tylko gdy jest o co walczyć)
                try:
                    SECRETS = {k: st.secrets[k] for k in ["EMAIL_NADAWCY", "HASLO_NADAWCY", "EMAIL_ODBIORCY"]}
                    if st.button("📧 WYŚLIJ RAPORT MAILEM"):
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
                    st.write("Brak specyficznych sugestii. Proponuj nowości.")
                
                # Generator SMS
                st.markdown("---")
                item_sms = suggestions[0].split(':')[-1].strip() if suggestions else "Chemia"
                sms = f"Dzien dobry! Tu GEKO. Brakuje Panu {gap:.0f} zl do promocji '{p_name}'. Moze dorzucimy: {item_sms}?"
                st.text_area("Gotowy SMS (Kopiuj)", value=sms, height=100)

    else:
        st.warning("⚠️ Wpisz kwotę zamówienia ręcznie, jeśli PDF jest nieczytelny.")

