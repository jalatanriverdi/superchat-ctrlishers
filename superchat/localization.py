"""Presentation-only translations of the official catalogue's English prose.

These strings never create or change catalogue records. Search and numeric facts
always come from the five organiser-supplied JSON files.
"""

from __future__ import annotations


PRODUCT_DESCRIPTIONS = {
    "P001": {"az": "Qulağı örtən Bluetooth qulaqlıq, 30 saatlıq batareya",
             "ru": "Полноразмерные Bluetooth-наушники, аккумулятор на 30 часов"},
    "P002": {"az": "Şarj qutusu olan qulaqdaxili qulaqcıqlar",
             "ru": "Внутриканальные наушники с зарядным футляром"},
    "P003": {"az": "16 GB RAM, 512 GB SSD, 15,6 düymlük ekran",
             "ru": "16 ГБ ОЗУ, 512 ГБ SSD, экран 15,6 дюйма"},
    "P004": {"az": "8 GB RAM, 256 GB SSD, yüngül, 1,2 kq",
             "ru": "8 ГБ ОЗУ, 256 ГБ SSD, лёгкий, 1,2 кг"},
    "P005": {"az": "6,5 düymlük OLED ekran, 128 GB, iki kamera",
             "ru": "OLED-экран 6,5 дюйма, 128 ГБ, двойная камера"},
    "P006": {"az": "6,1 düymlük LCD ekran, 64 GB",
             "ru": "LCD-экран 6,1 дюйма, 64 ГБ"},
    "P007": {"az": "Nəbz ölçümü, GPS, 7 günlük batareya",
             "ru": "Пульсометр, GPS, аккумулятор на 7 дней"},
    "P008": {"az": "Su keçirməyən, 12 saat səsləndirmə",
             "ru": "Водонепроницаемая, 12 часов воспроизведения"},
    "P009": {"az": "Yüngül yol qaçışı ayaqqabısı, 38–46 ölçülər",
             "ru": "Лёгкие беговые кроссовки для дороги, размеры 38–46"},
    "P010": {"az": "Su itələyən, 15 düymədək noutbuk bölməsi",
             "ru": "Водоотталкивающий, отделение для ноутбука до 15 дюймов"},
    "P011": {"az": "Avtomatik espresso, daxili qəhvəüyüdən",
             "ru": "Автоматическое эспрессо, встроенная кофемолка"},
    "P012": {"az": "2–5 oyunçu üçün ailəvi strategiya oyunu",
             "ru": "Семейная стратегическая игра для 2–5 игроков"},
}

MOVIE_SYNOPSIS = {
    "M001": {"az": "Sıradan çıxan kosmik stansiyanın heyəti kimin Yerə qayıdacağına qərar verməlidir.",
             "ru": "Экипаж неисправной космической станции должен решить, кто вернётся на Землю."},
    "M002": {"az": "Tacir ailəsi hadisələrlə dolu bir qışda İpək Yolunu keçir.",
             "ru": "Семья торговцев пересекает Шёлковый путь за одну полную событий зиму."},
    "M003": {"az": "İki rəqib stendap komiki qastrol avtobusunu bölüşməyə məcbur olur.",
             "ru": "Два соперничающих стендап-комика вынуждены делить гастрольный автобус."},
    "M004": {"az": "Gecə gözətçisi şəhər arxivinin hadisələri baş verməzdən əvvəl qeydə aldığını aşkar edir.",
             "ru": "Ночной сторож обнаруживает, что городской архив записывает события до того, как они происходят."},
    "M005": {"az": "Uşaqlar bölünmüş şəhər boyunca mesaj aparan uçurtmalar düzəldirlər.",
             "ru": "Дети делают воздушных змеев, которые переносят послания через разделённый город."},
    "M006": {"az": "Mühasib qaçaqmalçılıq şəbəkəsini üzə çıxarır və qaçmağa məcbur olur.",
             "ru": "Бухгалтер раскрывает сеть контрабанды и вынужден бежать."},
    "M007": {"az": "Köhnə binanı bərpa edən iki memar yavaş-yavaş bir-birinə aşiq olur.",
             "ru": "Два архитектора, восстанавливающие старое здание, постепенно влюбляются друг в друга."},
    "M008": {"az": "Radioastronom öz adına ünvanlanmış mesajı deşifrə edir.",
             "ru": "Радиоастроном расшифровывает сообщение, адресованное лично ей."},
}

LABELS = {
    "black": {"az": "qara", "ru": "чёрный"},
    "white": {"az": "ağ", "ru": "белый"},
    "silver": {"az": "gümüşü", "ru": "серебристый"},
    "grey": {"az": "boz", "ru": "серый"},
    "blue": {"az": "mavi", "ru": "синий"},
    "multicolor": {"az": "çoxrəngli", "ru": "разноцветный"},
    "sci-fi": {"az": "elmi fantastika", "ru": "фантастика"},
    "thriller": {"az": "triller", "ru": "триллер"},
    "adventure": {"az": "macəra", "ru": "приключения"},
    "drama": {"az": "dram", "ru": "драма"},
    "comedy": {"az": "komediya", "ru": "комедия"},
    "horror": {"az": "qorxu", "ru": "ужасы"},
    "mystery": {"az": "sirr", "ru": "загадка"},
    "animation": {"az": "animasiya", "ru": "анимация"},
    "family": {"az": "ailə", "ru": "семейный"},
    "action": {"az": "döyüş", "ru": "боевик"},
    "crime": {"az": "cinayət", "ru": "криминал"},
    "romance": {"az": "romantika", "ru": "романтика"},
    "English": {"az": "ingilis dili", "ru": "английский"},
    "Azerbaijani": {"az": "Azərbaycan dili", "ru": "азербайджанский"},
    "Russian": {"az": "rus dili", "ru": "русский"},
}


def translated(mapping: dict, record_id: str, language: str, original: str) -> str:
    return mapping.get(record_id, {}).get(language, original)


def label(value: str, language: str) -> str:
    return LABELS.get(value, {}).get(language, value)
