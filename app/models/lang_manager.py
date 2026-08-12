"""Multi-language management Load translation files
多语言管理 加载翻译文件"""
import json
import os


class LangManager:
    # Load the translation file in the language directory and provide the t(key) method
    # 加载 language/ 目录下的翻译文件，提供 t(key) 方法

    def __init__(self):
        self._texts = {}
        self._lang = "zh_CN"
        self._load("zh_CN")

    def _lang_dir(self):
        d = os.path.dirname(os.path.abspath(__file__))  # app/models
        d = os.path.dirname(d)  # app
        d = os.path.dirname(d)  # root
        return os.path.join(d, "language")

    def _load(self, lang):
        # Load en_US as a fallback dictionary first, then let the active
        # language override it, so missing keys never show raw key names.
        # 先加载 en_US 兜底字典，当前语言再覆盖；缺失键不会显示键名
        fp = os.path.join(self._lang_dir(), f"{lang}.json")
        self._texts = {}
        en_fp = os.path.join(self._lang_dir(), "en_US.json")
        if os.path.isfile(en_fp) and lang != "en_US":
            with open(en_fp, "r", encoding="utf-8") as f:
                self._texts.update(json.load(f))
        if os.path.isfile(fp):
            with open(fp, "r", encoding="utf-8") as f:
                self._texts.update(json.load(f))
            self._lang = lang

    def t(self, key, **kwargs):
        text = self._texts.get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text

    def available_languages(self):
        langs = []
        d = self._lang_dir()
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".json"):
                    langs.append(fn[:-5])
        return sorted(langs)

    @property
    def current_lang(self):
        return self._lang

    def set_language(self, lang):
        self._load(lang)


# Global singleton / 全局单例
_lang = LangManager()


def tr(key, **kwargs):
    return _lang.t(key, **kwargs)


def set_language(lang):
    _lang.set_language(lang)


def current_language():
    return _lang.current_lang


def available_languages():
    return _lang.available_languages()
