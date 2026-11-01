"""Settings persistence, independent of any toolkit.

`QSettings` was the only settings store before the refactor, which tied
persistence to Qt and to a Windows registry location. A plain JSON document is
portable, inspectable, easy to back up, and works identically in a headless
test. The interface is narrow enough that a `QSettings`-backed store can be
dropped in for a Qt build that wants native storage.

设置持久化，与任何工具包无关。

重构前 `QSettings` 是唯一的设置存储，把持久化绑到了 Qt 和 Windows 注册表位置。
纯 JSON 文档可移植、可直接查看、便于备份，在无界面测试中表现完全一致。接口足够窄，
因此希望使用原生存储的 Qt 构建可以换入一个基于 `QSettings` 的实现。
"""
import json
import logging
import os
import tempfile
import threading

log = logging.getLogger("GIFManager")

# Settings file name under the data directory / 数据目录下的设置文件名
SETTINGS_FILENAME = "settings.json"

# Indent for the written document, because a user-inspectable file is the point
# of choosing JSON. / 写出文档的缩进——选择 JSON 的意义就在于文件可读。
_INDENT = 4


class SettingsStore:
    # Interface every settings store implements.
    # 每个设置存储实现的接口。
    def read_all(self):
        raise NotImplementedError

    def write_many(self, values):
        raise NotImplementedError

    def sync(self):
        return True


class MemorySettingsStore(SettingsStore):
    # In-memory store for tests and for a session that must not persist.
    # 用于测试以及不应持久化的会话的内存存储。
    def __init__(self, initial=None):
        self._values = dict(initial or {})
        self._lock = threading.RLock()

    def read_all(self):
        with self._lock:
            return dict(self._values)

    def write_many(self, values):
        with self._lock:
            self._values.update(dict(values))
        return True

    def sync(self):
        return True


class JsonSettingsStore(SettingsStore):
    # Settings as a JSON document on disk.
    #
    # Writes are atomic: the document is written to a sibling temporary file and
    # then replaced, so a crash or a power loss mid-write can never leave a
    # truncated settings file that makes the application lose the user's whole
    # configuration.
    # 设置以磁盘上的 JSON 文档保存。
    #
    # 写入是原子的：先写到同目录的临时文件再替换，因此写入过程中的崩溃或断电绝不会
    # 留下被截断的设置文件，使用户丢掉整份配置。
    def __init__(self, path=None):
        self._path = path
        self._lock = threading.RLock()
        self._cache = None

    @property
    def path(self):
        if self._path is None:
            from gifmanager.core import paths

            self._path = os.path.join(paths.data_dir(), SETTINGS_FILENAME)
        return self._path

    def read_all(self):
        with self._lock:
            if self._cache is not None:
                return dict(self._cache)
            self._cache = self._read_file()
            return dict(self._cache)

    def _read_file(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle, object_hook=_json_object_hook)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            # A corrupt or unreadable settings file must not stop the
            # application: the caller falls back to defaults, and the file is
            # left untouched so the user can inspect it.
            # 损坏或不可读的设置文件不能阻止程序运行：调用方回退默认值，且文件保持
            # 原样，便于用户检查。
            log.warning("settings: cannot read %s -> %s (using defaults)",
                        self.path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def write_many(self, values):
        with self._lock:
            current = dict(self._cache if self._cache is not None
                           else self._read_file())
            current.update(dict(values))
            if not self._write_file(current):
                return False
            self._cache = current
            return True

    def _write_file(self, data):
        directory = os.path.dirname(os.path.abspath(self.path))
        try:
            os.makedirs(directory, exist_ok=True)
            handle, temp_path = tempfile.mkstemp(
                dir=directory, prefix=".settings-", suffix=".tmp")
        except OSError as exc:
            log.warning("settings: cannot prepare a write in %s -> %s",
                        directory, exc)
            return False
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=_INDENT, ensure_ascii=False,
                          sort_keys=True, default=_json_default)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
            return True
        except (OSError, TypeError, ValueError) as exc:
            log.warning("settings: cannot write %s -> %s", self.path, exc)
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False

    def sync(self):
        return True

    def invalidate(self):
        # Drop the cache so the next read comes from disk /
        # 丢弃缓存，使下次读取来自磁盘
        with self._lock:
            self._cache = None


def _json_default(value):
    # Serialise the few non-JSON values a setting may hold. Bytes (the window
    # geometry blob) become a hex string so the document stays plain text.
    # 序列化设置可能持有的少数非 JSON 值。字节（窗口几何数据）转为十六进制字符串，
    # 使文档保持纯文本。
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes__": bytes(value).hex()}
    return str(value)


def _json_object_hook(mapping):
    # Reverse of `_json_default` for the tagged byte strings /
    # `_json_default` 中带标记字节串的逆变换
    if set(mapping) == {"__bytes__"}:
        try:
            return bytes.fromhex(mapping["__bytes__"])
        except (TypeError, ValueError):
            return None
    return mapping
