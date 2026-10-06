"""right_menu.widgets.page_tabs.classic_tab：Windows 11 右键菜单「经典/新版」总开关。

本 Tab 是 `classic`（纯逻辑层：读 `InprocServer32` 默认值得三态 + 两个写动作 + 重启资源
管理器）的薄壳，只有一块卡：当前风格胶囊 + 「切换到经典菜单」+「重启资源管理器」。

**读同步、写异步**：状态读是一次 HKCU 取值（毫秒级；`Win32Backend`「永不抛」，读不到就
降级成 None），为它起 QThread 只会多一层悬挂线程风险——与 `home_widget.tick` 同一判断，故
`refresh()` 直接同步读，且**构造尾就调一次**（标签一打开即显示当前风格）。两个写动作一律
经 `workers.TaskGroup`：`classic_set_worker` 落地注册表、`restart_explorer` 要 taskkill 再
start（阻塞数秒），都绝不能进 UI 线程。

**`unknown` 态不隐藏也不假装确定**：这个 CLSID 是微软文档化的 COM 注册位，别家软件可能在
同一位上注册了真正的实现，`get_classic_state` 据此返回 `unknown`。UI 只显示「未知状态」，
切换按钮照常给——要不要覆盖对方那一格是用户的决定，本层不替他做「保险」的猜测。

**按钮文字跟随状态**：`enabled` 时「切换到经典菜单」必须变成「恢复新版菜单」。文案不跟着
变的话，同一个按钮会让用户以为在重复开启，而真发出去的是 `disable_classic`——那会整棵删
掉 CLSID 子树，把别人（乃至系统自己）的注册一并抹掉。

**写后补刷推迟到 idle**：`on_ok` 跑在任务 settled **之前**（此刻 group 仍 busy），故成功
只置 `_pending_refresh`，真正的 `refresh()` 由 owner 接的 `on_idle()` 执行——与 `scan_tab`
/ `shellnew_tab` 同一条链。

**`confirm_fn` 是可测性缝**：模态确认框在离屏测试里会挂起，故每个会弹框的公开方法都开一个
注入参数，测试传恒真/恒假函数即可把「点了确定」与「点了取消」两条路径都钉住。

页面是 backend 的单一来源：本 Tab 一律靠 `backend=` 注入（缺省才惰性建 `Win32Backend`），
测试注入 `FakeRegistry` 即可零真实注册表读写。`classic` / `workers` 一律**调用时取模块属
性**（`classic.restart_explorer()` 而非 `from ... import restart_explorer`），否则测试的
monkeypatch 拦不到。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label, make_status_chip

from ... import classic, workers
from ...registry_backend import Win32Backend
from .. import confirm, make_card_block, notify

_, QtCore, QtGui, QtWidgets = import_qt()

#: 构造期的胶囊占位文案（`refresh()` 立刻覆盖它）
CHIP_INIT = "未读取"
#: `get_classic_state` 三态 → (chip 文案, chip 色种)。缺键落「未知状态」，与 home_widget 同口径。
_STATE_CHIP = {"enabled": ("经典菜单", "warning"),
               "disabled": ("新版菜单", "success"),
               "unknown": ("未知状态", "info")}
_STATE_CHIP_FALLBACK = ("未知状态", "info")
#: 三态 → 「切换」按钮文案。状态决定动作方向（开 / 还原），文案必须跟着变。
_TOGGLE_TEXT = {"enabled": "恢复新版菜单"}
_TOGGLE_TEXT_FALLBACK = "切换到经典菜单"
#: 底部提示的初始文案
HINT_IDLE = "切换只改注册表、不自动重启；改完请点下方「重启资源管理器」使其生效。"
#: 卡内两条固定说明（第一句说清「为什么不立即生效」，第二句先给重启的代价）
_NOTE_EFFECT = "切换只写入一个注册表位置，写完不会立刻生效——必须重启资源管理器才看得到。"
_NOTE_RESTART = "「重启资源管理器」会强制结束并重启 explorer，所有已打开的资源管理器窗口会关闭。"
#: group 忙时的统一提示
HINT_BUSY = "上一项任务还在跑，请等它结束再操作。"


class ClassicTab(QtWidgets.QWidget):
    """经典右键菜单的当前风格、切换开关与重启资源管理器。"""

    def __init__(self, owner, group, *, parent=None, page=None, backend=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._page = page
        self._backend = backend if backend is not None else Win32Backend()
        self._pending_refresh = False
        self._chip_kind = "info"
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_card())
        root.addStretch(1)
        self.hint = make_label(HINT_IDLE, role="caption", parent=self)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        # 构造尾同步渲染一次：状态读是毫秒级 HKCU 取值，不起线程（见模块 docstring）
        self.refresh()

    # ── 组装 ────────────────────────────────────────────────────
    def _build_card(self):
        card, lay = make_card_block("经典菜单", parent=self)
        self._chip_host = card
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        row.addWidget(make_label("当前风格", role="caption", parent=card))
        self.chip = make_status_chip(CHIP_INIT, kind="info", parent=card)
        row.addWidget(self.chip)
        self.btn_toggle = make_button("切换到经典菜单", kind="primary", parent=card)
        self.btn_toggle.clicked.connect(lambda: self.toggle())
        row.addWidget(self.btn_toggle)
        row.addStretch(1)
        lay.addLayout(row)
        for text in (_NOTE_EFFECT, _NOTE_RESTART):
            note = make_label(text, role="caption", parent=card)
            note.setWordWrap(True)
            lay.addWidget(note)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(sizing()["radius_sm"])
        self.btn_restart = make_button("重启资源管理器", kind="danger", parent=card)
        self.btn_restart.clicked.connect(lambda: self.restart_explorer())
        btn_row.addWidget(self.btn_restart)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        self._chip_row = row
        return card

    # ── 渲染 ────────────────────────────────────────────────────
    def refresh(self, *_args):
        """同步重读一次经典状态并刷新胶囊与切换按钮文案（不起线程）。"""
        return self._apply_state(classic.get_classic_state(self._backend))

    def _apply_state(self, state):
        """三态 → (胶囊文案/色种, 切换按钮文案)。返回传入的 state（便于测试与调用方核对）。"""
        text, kind = _STATE_CHIP.get(state, _STATE_CHIP_FALLBACK)
        self._set_chip(text, kind)
        self.btn_toggle.setText(_TOGGLE_TEXT.get(state, _TOGGLE_TEXT_FALLBACK))
        return state

    def _set_chip(self, text, kind):
        """换胶囊：色种没变只改文案（`make_status_chip` 把色值写死在样式里，无法就地换色）。

        色种变了就换一枚新胶囊并**原位顶掉**旧的——**色值只由工厂决定**，本文件
        既不拼 QSS 也不定义私有调色板（AGENTS.md 规则 2/4）。

        交接走 `takeAt` + `insertWidget` 而**不是 `replaceWidget`**：QLayout 两种 API 都把
        旧 item 的所有权交给调用方，但 PySide6 的 `QLayoutItem` **不是 QObject**（既无
        `deleteLater` 也无 `delete`，`replaceWidget` 的返回值无处可交，只能靠引用一断即释
        放——实测丢弃引用后 60 次换色种只剩 1 个 QWidgetItem，即 PySide6 已把所有权给
        Python）。`takeAt` 则是本包 `reset_chips` 的既有安全口径：`takeAt` 出来的 item 把
        旧胶囊控件本体一并交出，直接 `deleteLater()`，item 随引用释放。`takeAt` 会腾出空
        位，故按原下标插回——胶囊（紧跟「当前风格」标签）不会漂到行尾 stretch 之后。
        """
        if self.chip is not None and self._chip_kind == kind:
            self.chip.setText(text)
            return
        old, self.chip = self.chip, make_status_chip(text, kind=kind,
                                                      parent=self._chip_host)
        self._chip_kind = kind
        index = self._chip_row.indexOf(old)      # 恒 ≥ 0：胶囊建在行内（见 _build_card）
        item = self._chip_row.takeAt(index)
        if item is not None and item.widget() is not None:
            item.widget().deleteLater()
        del item                                 # item 本体非 QObject：断引用即释放
        self._chip_row.insertWidget(index, self.chip)

    # ── 切换风格 ────────────────────────────────────────────────
    def toggle(self, *, confirm_fn=None):
        """按当前状态切换经典 / 新版菜单 → 确认后进线程。取消或 group 忙返回 False。

        `confirm_fn` 是可测性缝（模态框在离屏测试里会挂起）；缺省走 `confirm`。方向由状态
        决定：`enabled` 之外一律当「开经典」——`unknown` 也给按钮，由用户在确认框里决定。
        """
        enable = classic.get_classic_state(self._backend) != "enabled"
        ask = confirm_fn or (lambda *a, **k: confirm(
            self, "切换经典菜单",
            "将切换 Windows 11 右键菜单为经典样式（或还原为新版样式）。是否继续？",
            ok_text="切换"))
        if ask() is False:
            return False
        started = self._group.start(
            lambda ctx: workers.classic_set_worker(ctx, self._backend, enable),
            on_ok=self._on_toggle_ok, on_err=self._on_failed, label="classic:set")
        if not started:
            self.hint.setText(HINT_BUSY)
            return False
        self.btn_toggle.setEnabled(False)
        self.hint.setText("正在切换为经典菜单…" if enable else "正在恢复新版菜单…")
        return True

    def _on_toggle_ok(self, result):
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        detail = (result.get("detail") or "") if isinstance(result, dict) else ""
        notify(self, "已切换" if ok else "切换失败", detail, error=not ok)
        self.hint.setText(detail or ("已切换。" if ok else "切换失败。"))
        # 成功才补刷：胶囊此刻还停在上一次的状态。真正的刷新推迟到 idle（见 on_idle）——
        # on_ok 跑在任务 settled **之前**，此刻 group 仍 busy。
        self._pending_refresh = ok

    # ── 重启资源管理器 ──────────────────────────────────────────
    def restart_explorer(self, *, confirm_fn=None):
        """强制结束并重启 explorer 使改动生效 → 确认后进线程。取消或 group 忙返回 False。

        走 `group.start` 而非直接调用：`restart_explorer` 会 taskkill 再 start（阻塞数秒），
        放 UI 线程会让窗口卡死。`confirm_fn` 同 `toggle`。
        """
        ask = confirm_fn or (lambda *a, **k: confirm(
            self, "重启资源管理器",
            "将强制结束并重启资源管理器，所有资源管理器窗口会关闭。是否继续？",
            ok_text="重启"))
        if ask() is False:
            return False
        started = self._group.start(
            lambda ctx: classic.restart_explorer(),
            on_ok=self._on_restart_ok, on_err=self._on_failed, label="classic:restart")
        if not started:
            self.hint.setText(HINT_BUSY)
            return False
        self.btn_restart.setEnabled(False)
        self.hint.setText("正在重启资源管理器…")
        return True

    def _on_restart_ok(self, result):
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        detail = (result.get("detail") or "") if isinstance(result, dict) else ""
        notify(self, "已重启" if ok else "重启失败", detail, error=not ok)
        self.hint.setText(detail or ("已重启资源管理器。" if ok else "重启失败。"))

    # ── 失败与状态 ──────────────────────────────────────────────
    def _on_failed(self, kind, text):
        self.hint.setText(text.replace("\n", " "))
        notify(self, "操作失败", text, error=True)

    def on_idle(self):
        """一轮任务结束（owner 接 `group.idle`）：解禁按钮，补刷切换后的胶囊。"""
        try:
            busy = self._group.busy
            self.btn_toggle.setEnabled(not busy)
            self.btn_restart.setEnabled(not busy)
            if self._pending_refresh:
                self._pending_refresh = False
                self.refresh()
        except RuntimeError:                 # C++ 对象已析构
            pass
