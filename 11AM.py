from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import csv
import time
import logging
import traceback

# ------------ إعدادات التسجيل ------------
logging.basicConfig(
    filename='te_balance.log',
    filemode='w',
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8',
    level=logging.INFO
)

# ------------ مسارات الملفات ------------
ACCOUNTS_CSV = '11AM.csv'     # ملف CSV يحوي الأعمدة: mobile_number,password,target_cell
SHEET_NAME     = 'فواتير'        # اسم Google Sheet
CREDENTIALS_JSON = 'credentials.json'  # مسار ملف الخدمة

# ------------ دالة قراءة الحسابات من CSV ------------
def load_accounts_from_csv(csv_path):
    accounts = []
    try:
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            # نتوقع الأعمدة: mobile_number و password و target_cell
            for row in reader:
                mobile = row.get('mobile_number', '').strip()
                passwd = row.get('password', '').strip()
                cell   = row.get('target_cell', '').strip()
                if mobile and passwd and cell:
                    accounts.append({
                        'mobile_number': mobile,
                        'password': passwd,
                        'target_cell':  cell
                    })
        logging.info(f"تم تحميل {len(accounts)} حساب من الملف {csv_path}")
    except Exception:
        logging.error(f"خطأ في قراءة ملف {csv_path}:\n{traceback.format_exc()}")
    return accounts

# ------------ إعداد خيارات Chrome ------------
def setup_chrome_options():
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--log-level=3')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    return options

# ------------ اختيار نوع الخدمة ------------
def select_service_type(driver, wait):
    try:
        dropdown = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".ant-select-selector")))
        ActionChains(driver).move_to_element(dropdown).click().perform()
        logging.info("تم النقر على قائمة أنواع الخدمات")
        time.sleep(1)

        wait.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "div.ant-select-dropdown:not([style*='display: none'])")
        ))

        option_texts = ['Internet', 'INTERNET', 'انترنت', 'الانترنت', 'إنترنت', 'الإنترنت']
        for text in option_texts:
            try:
                option = driver.find_element(
                    By.XPATH,
                    f"//div[contains(@class,'ant-select-item') and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                )
                option.click()
                logging.info(f"تم اختيار نوع الخدمة: {text}")
                return True
            except NoSuchElementException:
                continue

        raise Exception("لم يتم العثور على خيار الانترنت في القائمة")

    except Exception:
        logging.error(f"خطأ في اختيار نوع الخدمة:\n{traceback.format_exc()}")
        driver.save_screenshot('service_type_error.png')
        return False

# ------------ استخراج قيمة الرصيد ------------
def get_balance_value(driver, wait):
    balance_selectors = [
        "span[style*='font-size: 2.1875rem']",
        ".balance-value",
        ".amount-display",
        "//span[contains(@class, 'balance')]"
    ]
    for selector in balance_selectors:
        try:
            if selector.startswith('//'):
                value_span = wait.until(EC.visibility_of_element_located((By.XPATH, selector)))
            else:
                value_span = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
            value_text = value_span.text.strip().replace(',', '')
            return int(float(value_text))
        except (TimeoutException, NoSuchElementException):
            continue
    raise Exception("لم يتم العثور على قيمة الرصيد")

# ------------ تسجيل الدخول ------------
def login_to_te(driver, wait, mobile, password):
    try:
        driver.get('https://my.te.eg/echannel/#/login')
        wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        logging.info(f"تم تحميل صفحة تسجيل الدخول للحساب {mobile}")

        # إدخال رقم الخدمة
        mobile_input = wait.until(EC.element_to_be_clickable((By.ID, 'login_loginid_input_01')))
        mobile_input.clear()
        mobile_input.send_keys(mobile)
        logging.info(f"تم إدخال رقم الخدمة: {mobile}")
        time.sleep(1)

        # اختيار نوع الخدمة
        if not select_service_type(driver, wait):
            raise Exception("فشل في اختيار نوع الخدمة")
        time.sleep(1)

        # إدخال كلمة المرور
        password_input = wait.until(EC.element_to_be_clickable((By.ID, 'login_password_input_01')))
        password_input.clear()
        password_input.send_keys(password)
        logging.info("تم إدخال كلمة المرور")
        time.sleep(1)

        # الضغط على زر تسجيل الدخول
        login_button = wait.until(EC.element_to_be_clickable((By.ID, 'login-withecare')))
        driver.execute_script("arguments[0].click();", login_button)
        logging.info("تم النقر على زر تسجيل الدخول")
        time.sleep(3)

        # التأكد من نجاح الدخول عبر انتظار ظهور عنصر الرصيد
        try:
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "span[style*='font-size: 2.1875rem']")))
            logging.info(f"تم تسجيل الدخول بنجاح للحساب {mobile}")
            return True
        except TimeoutException:
            raise Exception("لم يظهر عنصر الرصيد بعد تسجيل الدخول")

    except Exception:
        logging.error(f"خطأ في تسجيل الدخول للحساب {mobile}:\n{traceback.format_exc()}")
        driver.save_screenshot(f'login_error_{mobile}.png')
        return False

# ------------ حفظ البيانات في ملف نصي ------------
def save_to_text_file(value, filename):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(str(value))
        logging.info(f"تم حفظ الرصيد في الملف النصي: {filename}")
        return True
    except Exception:
        logging.error(f"خطأ في حفظ الملف النصي {filename}:\n{traceback.format_exc()}")
        return False

# ------------ تحديث Google Sheets ------------
def update_google_sheet(value, target_cell, sheet_name=SHEET_NAME, creds_json=CREDENTIALS_JSON):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_json, scope)
        client = gspread.authorize(creds)

        sheet = client.open(sheet_name).sheet1
        old_text = sheet.acell(target_cell).value
        parts = old_text.split(' ', 1) if old_text else []
        new_text = f"{value} {parts[1]}" if len(parts) > 1 else str(value)
        sheet.update_acell(target_cell, new_text)
        logging.info(f"تم تحديث الخلية {target_cell} في جوجل شيتس بالقيمة: {value}")
        return True
    except Exception:
        logging.error(f"خطأ في تحديث جوجل شيتس في الخلية {target_cell}:\n{traceback.format_exc()}")
        return False

# ------------ الدالة الرئيسية ------------
def main():
    driver = None
    try:
        # 1) نحمّل الحسابات من CSV
        accounts = load_accounts_from_csv(ACCOUNTS_CSV)
        if not accounts:
            logging.error("لم يتم العثور على أي حسابات في ملف CSV. تأكد من المسار والمحتوى.")
            return

        # 2) نفتح المتصفح مرة واحدة
        options = setup_chrome_options()
        service = Service('chromedriver.exe')
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 60)
        driver.set_page_load_timeout(60)

        # 3) لكل حساب في القائمة نطبق نفس الخطوات
        for account in accounts:
            mobile = account['mobile_number']
            password = account['password']
            target_cell = account['target_cell']  # مثلاً "H2" أو "H3", إلخ

            # تسجيل الدخول
            success = login_to_te(driver, wait, mobile, password)
            if not success:
                logging.error(f"تخطي الحساب {mobile} بسبب فشل في تسجيل الدخول")
                continue

            # استخراج الرصيد
            try:
                balance = get_balance_value(driver, wait)
                logging.info(f"الرصيد للحساب {mobile}: {balance}")
            except Exception:
                logging.error(f"خطأ في استخراج الرصيد للحساب {mobile}:\n{traceback.format_exc()}")
                continue

            # حفظ في ملف نصي باسم "balance_<mobile>.txt"
            text_filename = f"balance_{mobile}.txt"
            save_to_text_file(balance, text_filename)

            # تحديث Google Sheets في الخلية المحددة
            update_google_sheet(balance, target_cell)

            # مسح الكوكيز قبل الحساب التالي
            driver.delete_all_cookies()
            time.sleep(1)

    except Exception:
        logging.error(f"حدث خطأ غير متوقع:\n{traceback.format_exc()}")
        if driver:
            driver.save_screenshot('unexpected_error.png')

    finally:
        if driver:
            driver.quit()
            logging.info("تم إغلاق المتصفح")

if __name__ == "__main__":
    main()
