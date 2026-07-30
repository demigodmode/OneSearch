# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["agent/packaging/entry.py"],
    pathex=["agent"],
    datas=[("agent/onesearch_agent/release_public_key.txt", "onesearch_agent")],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="onesearch-agent", console=True)
