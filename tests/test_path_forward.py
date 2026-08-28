import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.path_forward import _url_to_path


def test_url_to_path_local():
    assert _url_to_path("file:///C:/Users/x/Documents").lower() == "c:\\users\\x\\documents"


def test_url_to_path_local_drive():
    assert _url_to_path("file://C:/foo/bar").lower() == "c:\\foo\\bar"


def test_url_to_path_unc():
    assert _url_to_path("file://server/share/path").lower() == "\\\\server\\share\\path"


def test_url_to_path_encoded():
    assert _url_to_path("file:///C:/My%20Documents/a").lower() == "c:\\my documents\\a"