"""Theme stylesheets / 主题样式表"""
from gifmanager.frontend.qt.theme.dark_theme import QSS as DARK_QSS
from gifmanager.frontend.qt.theme.light_theme import QSS as LIGHT_QSS

# Theme name -> stylesheet, keyed by the values `core.settings.THEMES` allows /
# 主题名 -> 样式表，键为 `core.settings.THEMES` 允许的取值
STYLESHEETS = {
    "dark": DARK_QSS,
    "light": LIGHT_QSS,
}

__all__ = ["DARK_QSS", "LIGHT_QSS", "STYLESHEETS"]
