"""derive_theme_variants：复刻 qfluentwidgets ThemeColor 的 HSV 派生语义。

黄金值全部由 PySide6 QColor 实测定值（与 qfluentwidgets/common/style_sheet.py
ThemeColor.color() 系数表一一对应），锁定算法语义：hue 恒定、暗色分支 v=1
重建、系数表集中。防止将来改系数导致状态色方向漂移。
"""
import pytest

from core.theme.tokens import derive_theme_variants
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_VARIANTS = ["primary", "dark1", "dark2", "dark3", "light1", "light2", "light3"]

# 黄金值矩阵：seed -> 主题 -> variant -> 派生 hex（小写，QColor.name() 格式）
_GOLDEN = {
    "#009faa": {
        True: {"primary": "#29f1ff", "dark1": "#25d9e6", "dark2": "#25c6d1",
               "dark3": "#24a9b3", "light1": "#3af2ff", "light2": "#58f4ff",
               "light3": "#74f6ff"},
        False: {"primary": "#009faa", "dark1": "#007780", "dark2": "#005055",
                "dark3": "#004044", "light1": "#00a7b3", "light2": "#2daab3",
                "light3": "#3eabb3"},
    },
    "#1178e0": {
        True: {"primary": "#399cff", "dark1": "#338ce6", "dark2": "#3381d1",
               "dark3": "#2f70b3", "light1": "#49a4ff", "light2": "#65b1ff",
               "light3": "#7ebeff"},
        False: {"primary": "#1178e0", "dark1": "#0d5aa8", "dark2": "#033970",
                "dark3": "#002d5a", "light1": "#127eeb", "light2": "#4899eb",
                "light3": "#5ea4eb"},
    },
}


@pytest.mark.parametrize("seed", ["#009faa", "#1178e0"])
@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("variant", _VARIANTS)
def test_golden_values(seed, dark, variant):
    """黄金值锁定：与 qfluentwidgets ThemeColor 算法输出完全一致。"""
    assert derive_theme_variants(seed, dark, variant) == _GOLDEN[seed][dark][variant]


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("variant", _VARIANTS)
def test_hue_is_preserved(dark, variant):
    """派生色必须保持种子 hue（饱和度/明度平移，色相不变）。"""
    h0 = QtGui.QColor("#009faa").hueF()
    got = QtGui.QColor(derive_theme_variants("#009faa", dark, variant)).hueF()
    # QColor 内部 16-bit 量化经 fromHsvF 往返有 ~2e-4 舍入，属正常（qfluentwidgets 同款）
    assert got == pytest.approx(h0, abs=1e-3)


def test_invalid_variant_raises():
    """非法 variant 必须抛 ValueError（防拼错导致颜色静默不变）。"""
    with pytest.raises(ValueError):
        derive_theme_variants("#009faa", True, "bogus")
    with pytest.raises(ValueError):
        derive_theme_variants("#009faa", False, "")


@pytest.mark.parametrize("dark", [True, False])
def test_dark_primary_rebuilds_value(dark):
    """暗色分支 PRIMARY 必须 v=1 重建（qfluentwidgets 语义），亮色分支保持种子。"""
    got = derive_theme_variants("#009faa", dark, "primary")
    assert QtGui.QColor(got).valueF() == pytest.approx(1.0 if dark else 0.6667, abs=0.001)