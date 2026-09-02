"""在项目根目录创建 YZplan.lnk 快捷方式，指向 pythonw.exe 无控制台启动。"""
import os
import sys

try:
    import win32com.client
except ImportError:
    print("需要 pywin32：pip install pywin32")
    sys.exit(1)


def create_shortcut():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_pythonw = os.path.join(project_dir, ".venv", "Scripts", "pythonw.exe")
    main_script = os.path.join(project_dir, "main.py")
    shortcut_path = os.path.join(project_dir, "YZplan.lnk")

    if not os.path.exists(venv_pythonw):
        print(f"[ERROR] pythonw.exe 不存在: {venv_pythonw}")
        sys.exit(1)
    if not os.path.exists(main_script):
        print(f"[ERROR] main.py 不存在: {main_script}")
        sys.exit(1)

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = venv_pythonw
    shortcut.Arguments = f'"{main_script}"'
    shortcut.WorkingDirectory = project_dir
    shortcut.Description = "YZplan 无控制台启动"
    shortcut.WindowStyle = 7
    shortcut.save()

    print(f"[OK] 快捷方式已创建: {shortcut_path}")
    print(f"     目标: {venv_pythonw}")
    print(f"     参数: \"{main_script}\"")


if __name__ == "__main__":
    create_shortcut()
