import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8",
}

QUERIES = [
    "будівництво",
    "фундамент",
    "земляні роботи",
    "відсипка ділянки",
    "планування ділянки",
    "стяжка підлоги",
    "стяжка пола",
    "ландшафтний дизайн",
    "благоустрій ділянки",
    "дренаж ділянки",
    "озеленення",
    "тротуарна плитка",
    "будівництво будинку",
    "котеджне будівництво",
    "риття котловану",
    "демонтаж",
    "бетонні роботи",
    "мощення",
    "кладка цегли",
    "кладка блоків",
    "цегляна кладка",
    "засипка дороги",
    "підсипка ям",
    "відсипка дороги",
    "грейдування дороги",
    "планування дороги",
]

# Слова-фильтры — объявления с этими словами выкидываем
SPAM_WORDS = [
    "посуточно", "подобово", "квартира", "кімната", "оренда", "сдам", "сдаю",
    "продаж квартири", "продам квартиру", "житло", "апартамент", "студія",
    "море", "басейн", "панорама", "дендропарк", "почасово", "погодинно",
]

PAGES_PER_QUERY = 5  # сколько страниц берём по каждому запросу

BASE_URL = "https://www.olx.ua/uk/list/q-{query}/?search[city_id]=2&page={page}"


def is_relevant(title):
    title_lower = title.lower()
    return not any(word in title_lower for word in SPAM_WORDS)


def parse_page(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        listings = soup.find_all("div", {"data-cy": "l-card"})
        results = []
        for item in listings:
            title_el = item.find("h4")
            link_el = item.find("a", href=True)
            title = title_el.text.strip() if title_el else ""
            link = "https://www.olx.ua" + link_el["href"] if link_el else ""
            if title and link and is_relevant(title):
                results.append({"title": title, "link": link})
        return results
    except Exception as e:
        print(f"Ошибка: {e}")
        return []


def parse_contact(link):
    try:
        response = requests.get(link, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        phone = ""
        phone_el = soup.find("a", href=lambda h: h and "tel:" in h)
        if phone_el:
            phone = phone_el["href"].replace("tel:", "").strip()
        desc_el = soup.find("div", {"data-cy": "ad_description"})
        description = desc_el.text.strip()[:200] if desc_el else ""
        return phone, description
    except:
        return "", ""


all_results = []

for query in QUERIES:
    print(f"\nПарсим: {query}")
    for page in range(1, PAGES_PER_QUERY + 1):
        url = BASE_URL.format(query=query.replace(" ", "-"), page=page)
        listings = parse_page(url)
        if not listings:
            break
        print(f"  Страница {page}: найдено {len(listings)} объявлений")
        for item in listings:
            phone, description = parse_contact(item["link"])
            item["phone"] = phone
            item["description"] = description
            item["query"] = query
            all_results.append(item)
            time.sleep(random.uniform(1.5, 2.5))

df = pd.DataFrame(all_results)
df = df.drop_duplicates(subset=["link"])

# Убираем строки без телефона
df_with_phone = df[df["phone"] != ""]
df_all = df

df_with_phone.to_excel("база_с_телефонами.xlsx", index=False)
df_all.to_excel("база_все_контакты.xlsx", index=False)

print(f"\nГотово!")
print(f"  Всего объявлений: {len(df_all)}")
print(f"  С телефонами: {len(df_with_phone)}")
print(f"  Файлы: база_с_телефонами.xlsx и база_все_контакты.xlsx")
