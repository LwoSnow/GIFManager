"""Shell views: one class per place the user can be.

外壳视图：用户可以所在的每个位置对应一个类。
"""
from gifmanager.frontend.qt.views.base import PlaceholderView, View
from gifmanager.frontend.qt.views.library import LibraryView

__all__ = ["LibraryView", "PlaceholderView", "View"]
