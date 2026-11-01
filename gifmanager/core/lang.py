"""Multi-language management: load translation files and translate keys.

Translation files live in `<resources>/language/<code>.json` and map a stable
key to a display string. `en_US` is always loaded first as a fallback, so a key
missing from the active language never surfaces as a raw key name.

多语言管理：加载翻译文件并翻译键。

翻译文件位于 `<resources>/language/<code>.json`，把稳定的键映射为显示文本。
`en_US` 始终先作为兜底加载，因此当前语言缺失的键不会以原始键名暴露。
"""
import json
import os
import threading

from gifmanager.core import paths

# Language used as the fallback dictionary / 作为兜底字典的语言
FALLBACK_LANG = "en_US"

# Default language when none is configured / 未配置语言时的默认值
DEFAULT_LANG = "zh_CN"


class LanguageManager:
    # Load the translation files from a language directory and expose
    # `t(key, **kwargs)`. The directory is injectable so a bundled build, a
    # portable install and the test suite can each point somewhere else.
    # 从语言目录加载翻译文件并暴露 `t(key, **kwargs)`。目录可注入，使打包版、
    # 便携版与测试各自指向不同位置。

    def __init__(self, lang_dir=None):
        self._lang_dir = lang_dir
        self._texts = {}
        self._lang = DEFAULT_LANG
        self._lock = threading.RLock()
        self._load(DEFAULT_LANG)

    # Resolved language directory, computed on first use when not injected /
    # 解析后的语言目录，未注入时首次使用时计算
    @property
    def lang_dir(self):
        if self._lang_dir is None:
            self._lang_dir = paths.language_dir()
        return self._lang_dir

    def _read(self, path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _load(self, lang):
        # Load the fallback dictionary first, then let the active language
        # override it, so missing keys never show raw key names.
        # 先加载兜底字典，当前语言再覆盖；缺失键不会显示键名。
        with self._lock:
            texts = {}
            if lang != FALLBACK_LANG:
                fallback = os.path.join(self.lang_dir, f"{FALLBACK_LANG}.json")
                if os.path.isfile(fallback):
                    texts.update(dict(self._read(fallback)))
            active = os.path.join(self.lang_dir, f"{lang}.json")
            if os.path.isfile(active):
                texts.update(dict(self._read(active)))
                self._lang = lang
            self._texts = texts

    def t(self, key, **kwargs):
        with self._lock:
            text = self._texts.get(key, key)
        if not kwargs:
            return text
        # A malformed translation string (unpaired brace / unknown placeholder)
        # must not crash the calling UI slot. / 翻译串异常（未配对花括号 /
        # 未知占位符）不得导致调用它的界面槽崩溃。
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return text

    def available_languages(self):
        langs = []
        directory = self.lang_dir
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                if name.endswith(".json"):
                    langs.append(name[:-5])
        return sorted(langs)

    @property
    def current_lang(self):
        with self._lock:
            return self._lang

    def set_language(self, lang):
        self._load(lang)

    # Keys present in the active dictionary; used by the resource checker.
    # 当前字典中存在的键；供资源检查脚本使用。
    def keys(self):
        with self._lock:
            return set(self._texts)


# Global singleton, kept for call sites that cannot take an injected manager.
# 全局单例，供无法注入管理器的调用点使用。
_manager = LanguageManager()


# Manager used by the module-level helpers; replaceable for tests /
# 模块级辅助函数使用的管理器；测试可替换
def manager():
    return _manager


def set_manager(new_manager):
    global _manager
    _manager = new_manager


def tr(key, **kwargs):
    return _manager.t(key, **kwargs)


def set_language(lang):
    _manager.set_language(lang)


def current_language():
    return _manager.current_lang


def available_languages():
    return _manager.available_languages()


__all__ = [
    "DEFAULT_LANG",
    "FALLBACK_LANG",
    "LanguageManager",
    "available_languages",
    "current_language",
    "manager",
    "set_language",
    "set_manager",
    "tr",
]
