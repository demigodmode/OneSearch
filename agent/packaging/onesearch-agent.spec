# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["entry.py"],
    pathex=[".."],
    datas=[
        ("../onesearch_agent/release_public_key.txt", "onesearch_agent"),
        ("../onesearch_agent/onesearch-agent.service", "onesearch_agent"),
    ],
    hiddenimports=["win32serviceutil", "win32service", "win32event", "win32crypt", "win32security", "ntsecuritycon"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="onesearch-agent", console=True)
b = Analysis(["updater_entry.py"], pathex=[".."])
updater = EXE(PYZ(b.pure), b.scripts, b.binaries, b.datas, name="onesearch-agent-updater", console=True)
