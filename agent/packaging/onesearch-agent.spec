# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["agent/packaging/entry.py"],
    pathex=["agent"],
    datas=[("agent/onesearch_agent/release_public_key.txt", "onesearch_agent"), ("agent/packaging/onesearch-agent.service", "packaging")],
    hiddenimports=["win32serviceutil", "win32service", "win32event", "win32crypt", "win32security", "ntsecuritycon"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="onesearch-agent", console=True)
b = Analysis(["agent/packaging/updater_entry.py"], pathex=["agent"])
updater = EXE(PYZ(b.pure), b.scripts, b.binaries, b.datas, name="onesearch-agent-updater", console=True)
