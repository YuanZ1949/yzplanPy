r"""right_menu.widgets.restore_dialog：「一键还原」的事前预览对话框。

一键还原是本模块**唯一会同时动四类注册表写**的动作（隐藏的右键项 / 隐藏的「新建」菜单项 /
自定义菜单项 / YZplan 右键子菜单，外加经典菜单总开关），且多数不可逆。故在起线程之前先把
「将要撤销什么」逐条数给用户看：读一次账本 `store.load()`，把四类条目的条数列出来，用户点
「还原」才继续——确认框（`widgets.confirm`）只能塞一段纯文本，塞不下逐类计数。

**只读账本，不读注册表、也不接 backend**：这一层要回答的是「YZplan 记下了多少改动」，答案
全在本地 JSON 里。注册表的实况（经典菜单此刻是不是 `enabled`）只有真去还原时才会被读到，
那属于 `store_restore.restore_all` 的判断——预览因此只给一条**静态说明**「若经典菜单处于
开启状态也会一并关闭」，不假装自己知道此刻的实况（说错了比不说更糟）。

**空账本也要说清楚**：`restore_all` 对空账本返回 `{"ok": True, "report": []}`（没东西可还原
不是错误），但对话框必须在用户点下「还原」之前就显示「没有可还原的改动」，否则用户会以为
按钮坏了。本对话框不替调用方禁用「还原」——那是调用方按预览结果决定的事。

本文件只 import 账本（`store`，Qt-free 且「永不抛」），不碰 `ops` / `store_restore` /
`elevate`；账本路径在**调用时**读（`rm_store.load()`），测试 monkeypatch `STATE_PATH` 即可
隔离到 `tmp_path`。逐类计数与文案全在 `preview_lines` 这个纯函数里，测试可直接断言。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label

from .. import store as rm_store

_, QtCore, QtGui, QtWidgets = import_qt()

#: 账本三类「逐条撤销」的桶 → 展示名（yzmenu 是整棵子树，见 preview_lines 单独处理）
_BUCKETS = (("disabled", "已隐藏的右键项"),
            ("shellnew_hidden", "已隐藏的「新建」菜单项"),
            ("custom_items", "自定义菜单项"))
#: 静态说明：经典菜单的联动。本层读不到注册表实况，故只写「若…」而不写「当前…」
NOTE_CLASSIC = "若经典菜单处于开启状态也会一并关闭。"
#: yzmenu 段的展示名
_YZMENU_TITLE = "YZplan 右键子菜单"


def _count(state, key):
    """账本某桶的条数；键缺失 / 形状不对一律当 0（「那一类没有要还原的东西」）。"""
    items = state.get(key) if isinstance(state, dict) else None
    return len(items) if isinstance(items, list) else 0


def _yzmenu_installed(state):
    """账本 yzmenu 段的 `installed` → bool；段缺失 / 形状不对当 False（未安装）。"""
    node = state.get("yzmenu") if isinstance(state, dict) else None
    return bool(node.get("installed")) if isinstance(node, dict) else False


def preview_lines(state):
    """账本 dict → 预览行文本列表（纯函数：不碰注册表、不起线程、不抛异常）。

    末行是「共 N 条」汇总或空账本的兜底文案——空账本时对话框要让用户明白按钮没坏，而不是
    让他以为点「还原」没反应。yzmenu 记 1 条（整棵子树一次卸掉），不按动作数计。"""
    rows = [f"{title}：{_count(state, key)} 条" for key, title in _BUCKETS]
    installed = _yzmenu_installed(state)
    rows.append(f"{_YZMENU_TITLE}：{'已安装（将卸载）' if installed else '未安装'}")
    total = sum(_count(state, key) for key, _ in _BUCKETS) + (1 if installed else 0)
    rows.append(f"共 {total} 条改动将被撤销。" if total else "账本里没有可还原的改动。")
    return rows


def _read_state():
    """读一次账本；任何异常都降级成空账本（对话框打不开比报错更难排查）。"""
    try:
        return rm_store.load() or {}
    except Exception:                       # noqa: BLE001 - store 的「永不抛」是契约，不是保证
        return {}


class RestoreDialog(QtWidgets.QDialog):
    """一键还原的事前预览：逐类列出将被撤销的条数 + 「还原」/「取消」。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("一键还原")
        self.setModal(True)
        sz = sizing()
        margin = sz["dialog_margin"] // 2
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.setSpacing(sz["dialog_spacing"])
        head = make_label("下列改动将被逐条撤销：", role="caption", parent=self)
        head.setWordWrap(True)
        lay.addWidget(head)
        for text in preview_lines(_read_state()) + [NOTE_CLASSIC]:
            label = make_label(text, parent=self)
            label.setWordWrap(True)
            lay.addWidget(label)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = make_button("取消", parent=self)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = make_button("还原", kind="primary", parent=self)
        self.btn_ok.clicked.connect(self.accept)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_ok)
        lay.addLayout(buttons)
